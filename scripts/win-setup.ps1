# Installs missing external tools with winget. Prints the plan first; nothing is installed without -Yes or a prompt.
param([switch]$Yes)
$tools = [ordered]@{ "ffmpeg" = "Gyan.FFmpeg"; "yt-dlp" = "yt-dlp.yt-dlp"; "ollama" = "Ollama.Ollama" }
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { Write-Host "winget introuvable (Windows 10 1809+ / App Installer)."; exit 1 }
$todo = @($tools.Keys | Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) })
if (-not $todo) { Write-Host "Tout est déjà installé."; exit 0 }
Write-Host "À installer:"; $todo | ForEach-Object { Write-Host "  winget install $($tools[$_])" }
if (-not $Yes -and (Read-Host "Continuer ? [o/N]") -notmatch '^[oOyY]') { exit 0 }
foreach ($t in $todo) { winget install --id $tools[$t] -e --accept-package-agreements --accept-source-agreements }
Write-Host "Whisper (transcription): zip Windows sur github.com/ggml-org/whisper.cpp/releases, puis [whisper] bin/model dans $env:APPDATA\Atelier\config.toml"
Write-Host "Modèles Ollama: ollama pull translategemma:12b   (voir: Système > Matériel)"
