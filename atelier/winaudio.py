"""Raw PCM <-> audio devices through PortAudio (sounddevice), the Windows stand-in for parec/pacat/pw-loopback.
  winaudio rec  --device NAME --rate N [--format int16|float32]   -> PCM on stdout
  winaudio play --device NAME --rate N [--format ...]             <- PCM on stdin
  winaudio dsp  --source NAME --sink NAME --af CHAIN --ffmpeg BIN  mic -> ffmpeg filters -> sink (live effects)
  winaudio list                                                   -> JSON {inputs, outputs}
Standalone on purpose (stdlib + sounddevice): also runs inside the Seed-VC venv. The virtual mic is VB-Audio Cable."""
import argparse
import json
import os
import subprocess
import sys
import threading

VIRTUAL_SINK = "CABLE Input"
VIRTUAL_MIC = "CABLE Output (VB-Audio Virtual Cable)"


def _devices(sd) -> list[dict]:
    return [{**d, "index": i} for i, d in enumerate(sd.query_devices())]


def pick(devs: list[dict], name: str, kind: str) -> int | None:
    """Device index by case-insensitive substring; ''/'default' -> None (system default)."""
    if not name or name == "default":
        return None
    ch = "max_input_channels" if kind == "input" else "max_output_channels"
    for d in devs:
        if d[ch] > 0 and name.lower() in d["name"].lower():
            return d["index"]
    raise RuntimeError(f"périphérique audio introuvable: {name}")


def listing(devs: list[dict]) -> dict:
    def names(ch):
        seen: list[str] = []
        for d in devs:
            if d[ch] > 0 and d["name"] not in seen:
                seen.append(d["name"])
        return seen
    return {"inputs": names("max_input_channels"), "outputs": names("max_output_channels")}


def _stream_io(sd, a, kind: str):
    devs = _devices(sd)
    idx = pick(devs, a.device, kind)
    cls = sd.RawInputStream if kind == "input" else sd.RawOutputStream
    return cls(samplerate=a.rate, channels=1, dtype=a.format, device=idx, latency="low")


def rec(sd, a) -> None:
    out = sys.stdout.buffer
    frame = 4 if a.format == "float32" else 2
    with _stream_io(sd, a, "input") as s:
        while True:
            data, _ = s.read(max(a.rate // 50, 256))
            out.write(bytes(data))
            out.flush()
            if len(data) < frame:
                break


def play(sd, a) -> None:
    src = sys.stdin.buffer
    with _stream_io(sd, a, "output") as s:
        while chunk := src.read(4096):
            s.write(chunk)


def dsp(sd, a) -> None:
    devs = _devices(sd)
    cin, cout = pick(devs, a.source, "input"), pick(devs, a.sink or VIRTUAL_SINK, "output")
    ff = subprocess.Popen([a.ffmpeg, "-hide_banner", "-loglevel", "error", "-fflags", "nobuffer",
                           "-flags", "low_delay", "-f", "s16le", "-ar", "48000", "-ac", "1", "-i", "pipe:0", "-af", a.af,
                           "-ar", "48000", "-ac", "1", "-f", "s16le", "pipe:1"],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          creationflags=0x08000000 if os.name == "nt" else 0)

    def feed() -> None:
        try:
            with sd.RawInputStream(samplerate=48000, channels=1, dtype="int16", device=cin, latency="low") as s:
                while True:
                    data, _ = s.read(960)
                    ff.stdin.write(bytes(data))
                    ff.stdin.flush()
        except (OSError, ValueError):
            pass

    threading.Thread(target=feed, daemon=True).start()
    with sd.RawOutputStream(samplerate=48000, channels=1, dtype="int16", device=cout, latency="low") as o:
        while chunk := ff.stdout.read(1920):
            o.write(chunk)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="winaudio")
    ap.add_argument("op", choices=["rec", "play", "dsp", "list"])
    ap.add_argument("--device", default="")
    ap.add_argument("--rate", type=int, default=48000)
    ap.add_argument("--format", choices=["int16", "float32"], default="int16")
    ap.add_argument("--source", default="")
    ap.add_argument("--sink", default="")
    ap.add_argument("--af", default="anull")
    ap.add_argument("--ffmpeg", default="ffmpeg")
    a = ap.parse_args(argv)
    try:
        import sounddevice as sd
    except Exception as e:
        print(f"sounddevice indisponible: {e}", file=sys.stderr)
        return 2
    try:
        if a.op == "list":
            print(json.dumps(listing(_devices(sd))))
        else:
            {"rec": rec, "play": play, "dsp": dsp}[a.op](sd, a)
    except (RuntimeError, OSError, KeyboardInterrupt, BrokenPipeError) as e:
        print(f"winaudio: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
