# PyInstaller spec (onedir). Build: scripts/build-win.ps1
import os
import pathlib
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# collect_submodules("atelier") finds nothing here (package not importable at spec time): list the files
# voicelive_worker runs in the Seed-VC venv (data file below): analysing it would drag torch/librosa in if installed
hidden = [f"atelier.{p.stem}" for p in pathlib.Path(SPECPATH, "..", "atelier").glob("*.py") if p.stem not in ("__init__", "voicelive_worker")] + ["atelier"]
hidden += collect_submodules("uvicorn")
# CPU engine (NLLB): optional import in engines.py, a frozen app can't pip install it later -> build with --with ctranslate2 --with sentencepiece
hidden += ["ctranslate2", "sentencepiece"]
if sys.platform == "win32":
    hidden += ["webview.platforms.edgechromium", "tkinter", "sounddevice"]
datas = [("../static", "static"), ("../config.toml", "."), ("../atelier/voicelive_worker.py", "atelier"),
         ("../atelier/strip_images.lua", "atelier"), ("../atelier/winaudio.py", "atelier"), ("../pyproject.toml", ".")]
for pkg in ("docx", "pptx", "openpyxl"):
    datas += collect_data_files(pkg)

a = Analysis(["../scripts/atelier_win.py"], pathex=[os.path.abspath(os.path.join(SPECPATH, ".."))], datas=datas, hiddenimports=hidden, excludes=["pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Atelier", console=False, icon="atelier.ico" if sys.platform == "win32" else None)
coll = COLLECT(exe, a.binaries, a.datas, name="Atelier")
