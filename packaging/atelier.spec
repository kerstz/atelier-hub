# PyInstaller spec (onedir). Build: scripts/build-win.ps1
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = collect_submodules("atelier") + collect_submodules("uvicorn") + ["webview.platforms.edgechromium", "tkinter"]
datas = [("../static", "static"), ("../config.toml", "."), ("../atelier/voicelive_worker.py", "atelier"),
         ("../atelier/strip_images.lua", "atelier")]
for pkg in ("docx", "pptx", "openpyxl"):
    datas += collect_data_files(pkg)

a = Analysis(["../scripts/atelier_win.py"], pathex=[".."], datas=datas, hiddenimports=hidden, excludes=["pytest"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Atelier", console=False, icon="atelier.ico")
coll = COLLECT(exe, a.binaries, a.datas, name="Atelier")
