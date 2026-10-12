# Build the Windows app: dist\Atelier\Atelier.exe (+ dist\Atelier-Setup.exe if Inno Setup 6 is installed).
# PowerShell, from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\build-win.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv introuvable: winget install astral-sh.uv" }
uv run --with pillow python packaging\make_icon.py
uv run --with pyinstaller --with pywebview --with sounddevice pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\atelier.spec
if ($LASTEXITCODE) { throw "PyInstaller a échoué" }
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($iscc) { $iscc = $iscc.Source } elseif (Test-Path "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") { $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" } else { $iscc = $null }
if ($iscc) { & $iscc packaging\atelier.iss } else { Write-Host "Inno Setup absent: dist\Atelier est utilisable tel quel (zip portable)." }
