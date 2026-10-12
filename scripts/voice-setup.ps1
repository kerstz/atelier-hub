# Installe Seed-VC (changeur de voix IA, GPL-3.0). Poids ~3-4 Go au préchauffage. -DryRun pour afficher seulement.
# torch: CUDA 12.1 si une carte NVIDIA est présente, sinon CPU (lent; pas de ROCm sous Windows).
param([switch]$DryRun, [switch]$NoWarmup, [string]$TorchIndex = "")
$ErrorActionPreference = "Stop"
$seed = Join-Path $env:LOCALAPPDATA "Atelier\opt\seed-vc"
$venv = Join-Path $env:LOCALAPPDATA "Atelier\seedvc-venv"
$py = Join-Path $venv "Scripts\python.exe"
function Run { Write-Host "+ $args"; if (-not $DryRun) { & $args[0] $args[1..($args.Length-1)]; if ($LASTEXITCODE) { throw "échec: $args" } } }
foreach ($c in "uv", "git", "ffmpeg") { if (-not (Get-Command $c -ErrorAction SilentlyContinue)) { throw "$c introuvable (scripts\win-setup.ps1)" } }
if (-not $TorchIndex) { $TorchIndex = if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { "https://download.pytorch.org/whl/cu121" } else { "https://download.pytorch.org/whl/cpu" } }
if (-not (Test-Path "$seed\.git")) { Run git clone --depth 1 https://github.com/Plachtaa/seed-vc $seed }
if (-not (Test-Path $py)) { Run uv venv --python 3.10 $venv }
Run uv pip install --python $py torch==2.4.0 torchaudio==2.4.0 --index-url $TorchIndex
Run uv pip install --python $py scipy==1.13.1 librosa==0.10.2 "huggingface-hub>=0.28.1" munch==4.0.0 einops==0.8.0 descript-audio-codec==1.0.0 pydub==0.25.1 transformers==4.46.3 soundfile==0.12.1 numpy==1.26.4 hydra-core==1.3.2 pyyaml python-dotenv tqdm accelerate sounddevice==0.5.0 demucs
if (-not $NoWarmup -and -not $DryRun) {
  $t = Join-Path $env:TEMP "atl_vc"; New-Item -ItemType Directory -Force $t | Out-Null
  ffmpeg -loglevel error -y -f lavfi -i "sine=f=220:d=3" -ar 22050 -ac 1 "$t\a.wav"
  ffmpeg -loglevel error -y -f lavfi -i "sine=f=330:d=3" -ar 22050 -ac 1 "$t\b.wav"
  Push-Location $seed; & $py inference.py --source "$t\a.wav" --target "$t\b.wav" --output "$t\o" --diffusion-steps 4; Pop-Location
}
Write-Host "ok. Ensuite: scripts\voice-refs.ps1 ; pour le direct: installer VB-Audio Cable (https://vb-audio.com/Cable/)."
