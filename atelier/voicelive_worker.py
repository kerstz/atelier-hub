# SPDX-License-Identifier: GPL-3.0-or-later
"""Seed-VC real-time worker. Run with the Seed-VC venv python, cwd = the seed-vc checkout.
Derived from Seed-VC's real-time-gui.py (GPL-3.0, github.com/Plachtaa/seed-vc): it imports that file for
model loading and one-block inference, and re-implements its audio loop on raw parec/pacat pipes.

stdin : JSON lines {"voice": "<ref.wav>", "bypass": bool, "mute": bool, "gate_db": f, "gain_db": f}
stdout: JSON lines {"ready": true, "sr": n, "latency_ms": n} then ~4/s {"in_db","out_db","infer_ms","overruns","speech"}
"""
import argparse
import importlib.util
import json
import math
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import numpy as np

ctl = {"voice": None, "bypass": False, "mute": False, "gate_db": -50.0, "gain_db": 0.0}
ctl_lock = threading.Lock()


def emit(**kw) -> None:
    sys.stdout.write(json.dumps(kw) + "\n")
    sys.stdout.flush()


def stdin_loop() -> None:
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        with ctl_lock:
            ctl.update({k: v for k, v in msg.items() if k in ctl})


def db(x: np.ndarray) -> float:
    return 20 * math.log10(float(np.sqrt(np.mean(np.square(x)))) + 1e-9)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--sink", required=True)
    ap.add_argument("--voice", required=True)
    ap.add_argument("--block", type=float, default=0.18)
    ap.add_argument("--steps", type=int, default=6)
    ap.add_argument("--cfg", type=float, default=0.0)
    ap.add_argument("--gate-db", type=float, default=-50.0)
    ap.add_argument("--extra-right", type=float, default=0.02)
    ap.add_argument("--checkpoint", default="")
    ap.add_argument("--config", default="")
    a = ap.parse_args()
    ctl.update(voice=a.voice, gate_db=a.gate_db)

    import os
    sys.path.insert(0, os.getcwd())
    import librosa
    import torch
    import torch.nn.functional as F

    spec = importlib.util.spec_from_file_location("rtg", "real-time-gui.py")
    rtg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rtg)
    rtg.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    dev = rtg.device
    model_set = rtg.load_models(SimpleNamespace(
        fp16=dev.type != "cpu", checkpoint_path=a.checkpoint or None, config_path=a.config or None, gpu=0))
    sr = model_set[-1]["sampling_rate"]

    zc = sr // 50
    block = int(round(a.block * sr / zc)) * zc
    block_16k = 320 * block // zc
    crossfade = int(round(0.05 * sr / zc)) * zc
    sola_buf_n = min(crossfade, 4 * zc)
    sola_search = zc
    extra_ce, extra_dit = 2.5, 0.5
    extra = int(round(extra_ce * sr / zc)) * zc
    extra_right = int(round(a.extra_right * sr / zc)) * zc
    total = extra + crossfade + sola_search + block + extra_right
    input_wav = torch.zeros(total, device=dev, dtype=torch.float32)
    input_res = torch.zeros(320 * total // zc, device=dev, dtype=torch.float32)
    sola_buffer = torch.zeros(sola_buf_n, device=dev, dtype=torch.float32)
    skip_head, skip_tail = extra // zc, extra_right // zc
    return_length = (block + sola_buf_n + sola_search) // zc
    fade_in = torch.sin(0.5 * math.pi * torch.linspace(0.0, 1.0, steps=sola_buf_n, device=dev)) ** 2
    fade_out = 1 - fade_in
    ones = torch.ones(1, 1, sola_buf_n, device=dev)

    refs: dict[str, np.ndarray] = {}

    def ref(path: str) -> np.ndarray:
        if path not in refs:
            refs[path] = librosa.load(path, sr=sr)[0]
        return refs[path]

    def infer(path: str) -> torch.Tensor:
        return rtg.custom_infer(model_set, ref(path), path, input_res, block_16k, skip_head, skip_tail, return_length,
                                a.steps, a.cfg, 3.0, extra_ce - extra_dit)

    silent = np.zeros(block, dtype=np.float32)
    bytes_block = block * 4
    rate = ["--raw", "--format=float32le", f"--rate={sr}", "--channels=1", "--latency-msec=20"]
    rec = subprocess.Popen(["parec", "-d", a.source, *rate], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    play = subprocess.Popen(["pacat", "-d", a.sink, *rate], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    threading.Thread(target=stdin_loop, daemon=True).start()

    # warm-up: first MIOpen/kernel compile happens here, not on the first words
    with torch.no_grad():
        infer(ctl["voice"])
    emit(ready=True, sr=sr, latency_ms=int(1000 * (a.block + a.extra_right) + 100))

    hold_blocks = max(2, int(math.ceil(1.0 / a.block)))
    hold = 0
    overruns = 0
    last_stat = 0.0
    infer_ms = 0.0
    try:
        while True:
            raw = rec.stdout.read(bytes_block)
            if len(raw) < bytes_block:
                break
            x = np.frombuffer(raw, dtype=np.float32)
            with ctl_lock:
                c = dict(ctl)
            in_db = db(x)
            speech = in_db > c["gate_db"]
            hold = hold_blocks if speech else max(0, hold - 1)

            input_wav[:-block] = input_wav[block:].clone()
            input_wav[-block:] = torch.from_numpy(x).to(dev)
            input_res[:-block_16k] = input_res[block_16k:].clone()
            tail = input_wav[-block - 2 * zc:].cpu().numpy()
            res16 = librosa.resample(tail, orig_sr=sr, target_sr=16000)[320:]
            input_res[-320 * (block // zc + 1):] = torch.from_numpy(res16).to(dev)

            t0 = time.perf_counter()
            if c["bypass"]:
                infer_wav = input_wav[extra:].clone()
            elif hold > 0:
                infer_wav = infer(c["voice"]).float()
            else:
                infer_wav = torch.zeros_like(input_wav[extra:])
            infer_ms = (time.perf_counter() - t0) * 1000
            if infer_ms > a.block * 1000:
                overruns += 1

            conv_input = infer_wav[None, None, :sola_buf_n + sola_search]
            nom = F.conv1d(conv_input, sola_buffer[None, None, :])
            den = torch.sqrt(F.conv1d(conv_input ** 2, ones) + 1e-8)
            t = nom[0, 0] / den[0, 0]
            off = int(torch.argmax(t).item()) if t.numel() > 1 else 0
            infer_wav = infer_wav[off:]
            infer_wav[:sola_buf_n] *= fade_in
            infer_wav[:sola_buf_n] += sola_buffer * fade_out
            sola_buffer[:] = infer_wav[block:block + sola_buf_n]
            out = infer_wav[:block].cpu().numpy()
            if c["mute"]:
                out = silent
            elif c["gain_db"]:
                out = out * (10 ** (c["gain_db"] / 20))
            play.stdin.write(np.clip(out, -1.0, 1.0).astype(np.float32).tobytes())
            play.stdin.flush()

            if time.time() - last_stat > 0.25:
                last_stat = time.time()
                emit(in_db=round(in_db, 1), out_db=round(db(out), 1), infer_ms=int(infer_ms), overruns=overruns, speech=bool(hold))
    finally:
        for p in (rec, play):
            try:
                p.kill()
            except OSError:
                pass


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        pass
