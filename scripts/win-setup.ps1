# Installe les outils externes d'Atelier sous Windows (winget + téléchargements GitHub). Affiche le plan, demande confirmation.
#   powershell -ExecutionPolicy Bypass -File scripts\win-setup.ps1 [-Tier minimal|standard|full] [-Yes] [-Models] [-NoWhisper]
# minimal  = ffmpeg, yt-dlp, Ollama, uv                      (traduire, YouTube, sous-titres existants)
# standard = + poppler, tesseract, pandoc, LibreOffice, whisper.cpp, pdf2zh-next, ocrmypdf   (défaut)
# full     = + calibre, piper, rembg, demucs, Real-ESRGAN, DeepFilterNet
# -Models  = télécharge aussi les modèles Ollama recommandés pour cette machine
param([ValidateSet("minimal","standard","full")][string]$Tier = "standard", [switch]$Yes, [switch]$Models, [switch]$NoWhisper)
$ErrorActionPreference = "Continue"
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$opt = Join-Path $env:LOCALAPPDATA "Atelier\opt"
$bin = Join-Path $env:LOCALAPPDATA "Atelier\bin"
New-Item -ItemType Directory -Force $opt, $bin | Out-Null
function Has($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Refresh-Path { $env:PATH = [Environment]::GetEnvironmentVariable("PATH","Machine") + ";" + [Environment]::GetEnvironmentVariable("PATH","User") + ";$env:USERPROFILE\.local\bin" }
function Get-Asset($repo, $rx) {
  $rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ "User-Agent" = "atelier" }
  $a = $rel.assets | Where-Object { $_.name -match $rx } | Select-Object -First 1
  if (-not $a) { throw "asset introuvable: $repo /$rx/" }
  $a
}
function Fetch-Zip($repo, $rx, $dest) {
  $a = Get-Asset $repo $rx
  $zip = Join-Path $env:TEMP $a.name
  Write-Host "  $($a.name)"
  Invoke-WebRequest $a.browser_download_url -OutFile $zip
  $tmp = Join-Path $env:TEMP ("atl_" + [guid]::NewGuid().ToString("N"))
  Expand-Archive $zip $tmp -Force
  New-Item -ItemType Directory -Force $dest | Out-Null
  $inner = Get-ChildItem $tmp -Directory
  $src = if ($inner.Count -eq 1 -and -not (Get-ChildItem $tmp -File)) { $inner[0].FullName } else { $tmp }
  Copy-Item "$src\*" $dest -Recurse -Force
  Remove-Item $tmp, $zip -Recurse -Force
}

$winget = [ordered]@{ ffmpeg = "Gyan.FFmpeg"; "yt-dlp" = "yt-dlp.yt-dlp"; ollama = "Ollama.Ollama"; uv = "astral-sh.uv"; git = "Git.Git" }
if ($Tier -ne "minimal") { $winget += @{ pdftotext = "oschwartz10612.Poppler"; tesseract = "UB-Mannheim.TesseractOCR"; pandoc = "JohnMacFarlane.Pandoc"; soffice = "TheDocumentFoundation.LibreOffice" } }
if ($Tier -eq "full") { $winget += @{ "ebook-convert" = "calibre.calibre" } }
$uvtools = @(); if ($Tier -ne "minimal") { $uvtools += "pdf2zh-next", "ocrmypdf" }; if ($Tier -eq "full") { $uvtools += "piper-tts", "rembg[cpu,cli]", "demucs" }
$whisperDir = Join-Path $opt "whisper.cpp"
$nvidia = Has nvidia-smi

Write-Host "Plan ($Tier):"
$todo = @($winget.Keys | Where-Object { -not (Has $_) -and -not (($_ -eq "soffice") -and (Test-Path "$env:ProgramFiles\LibreOffice\program\soffice.exe")) -and -not (($_ -eq "tesseract") -and (Test-Path "$env:ProgramFiles\Tesseract-OCR\tesseract.exe")) -and -not (($_ -eq "ebook-convert") -and (Test-Path "$env:ProgramFiles\Calibre2\ebook-convert.exe")) })
$todo | ForEach-Object { Write-Host "  winget install $($winget[$_])" }
$uvtools | ForEach-Object { Write-Host "  uv tool install $_" }
if ($Tier -ne "minimal" -and -not $NoWhisper -and -not (Test-Path "$whisperDir\bin\whisper-cli.exe")) { Write-Host "  whisper.cpp ($(if ($nvidia) {'CUDA'} else {'CPU'})) + modèle large-v3-turbo (~1,6 Go)" }
if ($Tier -eq "full") { Write-Host "  Real-ESRGAN (ncnn-vulkan), DeepFilterNet (deep-filter.exe)" }
if ($Tier -ne "minimal") {
  # le paquet Tesseract winget n'embarque que l'anglais: langues OCR dans un dossier à nous (TESSDATA_PREFIX)
  $td = Join-Path $env:LOCALAPPDATA "Atelier\tessdata"
  New-Item -ItemType Directory -Force $td | Out-Null
  foreach ($l in "eng", "fra", "osd") {
    $f = Join-Path $td "$l.traineddata"
    if (-not (Test-Path $f)) { Invoke-WebRequest "https://github.com/tesseract-ocr/tessdata_fast/raw/main/$l.traineddata" -OutFile "$f.part"; Move-Item "$f.part" $f }
  }
  [Environment]::SetEnvironmentVariable("TESSDATA_PREFIX", $td, "User")
}
if ($Tier -ne "minimal") { Write-Host "  Java + LanguageTool (correcteur FR, ~250 Mo)" }
if ($Models) { Write-Host "  modèles Ollama recommandés (python -m atelier.hw --models)" }
if (-not $todo -and -not $uvtools -and -not $Models) { Write-Host "  rien à faire" }
if (-not $Yes -and (Read-Host "Continuer ? [o/N]") -notmatch '^[oOyY]') { exit 0 }

if ($todo -and -not (Has winget)) { Write-Host "winget introuvable (App Installer, Windows 10 1809+)"; exit 1 }
foreach ($t in $todo) { winget install --id $winget[$t] -e --accept-package-agreements --accept-source-agreements; if ($LASTEXITCODE) { Write-Warning "échec: $($winget[$t])" } }
Refresh-Path

foreach ($u in $uvtools) { if (Has uv) { uv tool install --python 3.12 $u; if ($LASTEXITCODE) { Write-Warning "échec: uv tool install $u" } } }
if ((Has uv) -and ($uvtools -contains "pdf2zh-next")) { & "$PSScriptRoot\fix-pdf2zh.ps1" }

if ($Tier -ne "minimal" -and -not $NoWhisper -and -not (Test-Path "$whisperDir\bin\whisper-cli.exe")) {
  $rx = if ($nvidia) { '^whisper-cublas-.*-bin-x64\.zip$' } else { '^whisper-bin-x64\.zip$' }
  try {
    Fetch-Zip "ggml-org/whisper.cpp" $rx "$whisperDir\bin"
    $cli = Get-ChildItem "$whisperDir\bin" -Recurse -Filter "whisper-cli.exe" | Select-Object -First 1
    if ($cli -and $cli.DirectoryName -ne "$whisperDir\bin") { Copy-Item "$($cli.DirectoryName)\*" "$whisperDir\bin" -Recurse -Force }
  } catch { Write-Warning "whisper.cpp: $_" }
  $model = "$whisperDir\models\ggml-large-v3-turbo.bin"
  New-Item -ItemType Directory -Force (Split-Path $model) | Out-Null
  if (-not (Test-Path $model)) { Invoke-WebRequest "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin" -OutFile "$model.part"; Move-Item "$model.part" $model }
}
if ($Tier -eq "full") {
  try { if (-not (Test-Path "$opt\realesrgan\realesrgan-ncnn-vulkan.exe")) { Fetch-Zip "xinntao/Real-ESRGAN" 'realesrgan-ncnn-vulkan.*windows\.zip$' "$opt\realesrgan" } } catch { Write-Warning "Real-ESRGAN: $_" }
  try {
    if (-not (Test-Path "$bin\deep-filter.exe")) { $a = Get-Asset "Rikorose/DeepFilterNet" 'x86_64-pc-windows-msvc\.exe$'; Invoke-WebRequest $a.browser_download_url -OutFile "$bin\deep-filter.exe" }
  } catch { Write-Warning "DeepFilterNet: $_" }
}
if ($Models) {
  $exe = @("$PSScriptRoot\..\Atelier.exe", "$PSScriptRoot\Atelier.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
  if ($exe -and (Has ollama)) {
    $out = Join-Path $env:TEMP "atelier-models.txt"
    Start-Process $exe -ArgumentList "--hw-models", "`"$out`"" -Wait
    Get-Content $out | Where-Object { $_ } | ForEach-Object { ollama pull $_ }
  } else { Write-Warning "Ollama ou Atelier.exe introuvable: ollama pull translategemma:12b" }
}
if ($Tier -ne "minimal") {
  try { & "$PSScriptRoot\get-languagetool.ps1" } catch { Write-Warning "LanguageTool (correcteur FR): $_" }
}
Write-Host ""
Write-Host "Voix en direct: installer VB-Audio Cable (https://vb-audio.com/Cable/), puis scripts\voice-setup.ps1 pour la voix IA."
Write-Host "Terminé. Relancer Atelier (Système > Dépendances montre ce qui manque)."
