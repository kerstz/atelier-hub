# Fabrique les échantillons de référence des voix du catalogue avec Piper (local). Une voix introuvable est sautée.
# Licences: docs/VOICES.md. Options: -Only ID, -DryRun
param([string]$Only = "", [switch]$DryRun)
$ErrorActionPreference = "Continue"
$dir = Join-Path $env:LOCALAPPDATA "Atelier\voices"
$piperDir = Join-Path $env:LOCALAPPDATA "Atelier\piper"
New-Item -ItemType Directory -Force $dir, $piperDir | Out-Null
$fr = "Bonjour, je vous présente aujourd'hui une voix naturelle. Elle parle posément, avec des phrases de longueurs différentes. Le soleil se couche doucement derrière les collines, et les oiseaux rentrent au nid."
$en = "Good evening, and welcome. Tonight I would like to tell you a short story, spoken slowly and clearly. The river runs quietly past the old mill, and the lanterns are lit along the shore."
# id | voix piper | locuteur | demi-tons | langue
$table = @(
 "femme-claire|fr_FR-siwis-medium||0|fr", "femme-chaleureuse|fr_FR-upmc-medium|0|0|fr", "femme-posee|fr_FR-mls-medium|12|-1|fr",
 "homme-pose|fr_FR-tom-medium||0|fr", "homme-grave|fr_FR-tom-medium||-3|fr", "homme-jeune|fr_FR-mls-medium|82|1|fr",
 "homme-narrateur|fr_FR-mls-medium|5|0|fr", "voix-aigue|fr_FR-upmc-medium|0|3|fr", "voix-agee|fr_FR-upmc-medium|1|-1|fr",
 "anonyme|fr_FR-mls-medium|42|0|fr", "en-femme-claire|en_US-lessac-medium||0|en", "en-femme-chaleureuse|en_GB-jenny_dioco-medium||0|en",
 "en-homme-pose|en_US-ryan-high||0|en", "en-homme-grave|en_US-ryan-high||-3|en", "narrateur-en|en_GB-alan-medium||0|en")
$ok = 0; $skip = 0
foreach ($row in $table) {
  $id, $voice, $spk, $st, $lang = $row.Split("|")
  if ($Only -and $Only -ne $id) { continue }
  Write-Host "$id <- $voice $spk $st dt"
  if ($DryRun) { continue }
  $onnx = Join-Path $piperDir "$voice.onnx"
  if (-not (Test-Path $onnx)) { uv tool run --from piper-tts python -m piper.download_voices $voice --download-dir $piperDir *> $null }
  if (-not (Test-Path $onnx)) { Write-Warning "saut: voix $voice introuvable"; $skip++; continue }
  $tmp = Join-Path $env:TEMP "$id.wav"
  $txt = if ($lang -eq "en") { $en } else { $fr }
  $pargs = @("-m", $onnx, "-f", $tmp); if ($spk) { $pargs += "--speaker", $spk }
  $txt | piper @pargs 2>$null | Out-Null
  if (-not (Test-Path $tmp)) { Write-Warning "saut: piper a échoué"; $skip++; continue }
  $af = "anull"; if ($st -and [int]$st -ne 0) { $af = "rubberband=pitch={0}:formant=preserved" -f ([math]::Pow(2, [int]$st / 12).ToString("0.0000", [cultureinfo]::InvariantCulture)) }
  ffmpeg -nostdin -loglevel error -y -i $tmp -af $af -ar 22050 -ac 1 -c:a pcm_s16le (Join-Path $dir "$id.wav")
  if ($LASTEXITCODE -eq 0) { $ok++ } else { $skip++ }
  Remove-Item $tmp -Force
}
Write-Host "références: $ok créées, $skip sautées -> $dir"
