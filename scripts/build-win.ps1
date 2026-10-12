# Build the Windows app: dist\Atelier\Atelier.exe (+ Atelier-Setup.exe if Inno Setup is installed).
# Run from the repo root in PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\build-win.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot)
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw "uv introuvable: winget install astral-sh.uv" }
if (-not (Test-Path packaging\atelier.ico)) {
  uv run --with pillow python -c "from PIL import Image; Image.new('RGBA',(256,256),(37,99,235,255)).save('packaging/atelier.ico')"
}
uv run --with pyinstaller --with pywebview pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\atelier.spec
$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) { $iscc = Get-Item "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" -ErrorAction SilentlyContinue }
if ($iscc) { & $iscc.Source packaging\atelier.iss } else { Write-Host "Inno Setup absent: dossier dist\Atelier utilisable tel quel (zip portable)." }
