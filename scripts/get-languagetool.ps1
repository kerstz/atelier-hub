# Installe Java (winget) et LanguageTool (LGPL-2.1, ~250 Mo) pour le Correcteur d'Atelier.
#   powershell -ExecutionPolicy Bypass -File scripts\get-languagetool.ps1 [-Version 6.6]
param([string]$Version = "6.6")
$ErrorActionPreference = "Stop"
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$dest = Join-Path $env:LOCALAPPDATA "Atelier\languagetool"
if (-not (Get-Command java -ErrorAction SilentlyContinue)) {
  if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "winget introuvable: installer Java 17+ (https://adoptium.net) puis relancer" }
  winget install --id EclipseAdoptium.Temurin.21.JRE -e --accept-package-agreements --accept-source-agreements
}
New-Item -ItemType Directory -Force $dest | Out-Null
$zip = Join-Path $env:TEMP "LanguageTool-$Version.zip"
Write-Host "LanguageTool $Version (~250 Mo)…"
Invoke-WebRequest "https://languagetool.org/download/LanguageTool-$Version.zip" -OutFile $zip
Expand-Archive $zip $dest -Force
Remove-Item $zip -Force
if (-not (Test-Path "$dest\LanguageTool-$Version\languagetool-server.jar")) { throw "archive inattendue" }
Write-Host "ok: $dest\LanguageTool-$Version. Relancer Atelier (Java neuf: rouvrir la session si besoin)."
