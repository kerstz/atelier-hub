#!/usr/bin/env bash
# Fabrique les échantillons de référence des 10 voix du catalogue avec Piper (déjà installé), en local.
# Noms et locuteurs vérifiés dans rhasspy/piper-voices (2026-10-12); genres MLS déduits de la F0. Licences: docs/VOICES.md.
# Une voix introuvable est sautée, pas fatale.
# Options: --piper (défaut), --dry-run, --dir DIR, --only ID
set -u
dry=0; only=""
DIR="${ATELIER_VOICES_DIR:-$HOME/.local/share/atelier/voices}"
PIPER_DIR="${ATELIER_PIPER_DIR:-$HOME/.local/share/piper}"
while [ $# -gt 0 ]; do
  case $1 in
    --piper) ;;
    --dry-run) dry=1;;
    --dir) DIR=$2; shift;;
    --only) only=$2; shift;;
    -h|--help) sed -n 2,5p "$0"; exit 0;;
    *) echo "option inconnue: $1" >&2; exit 64;;
  esac; shift
done
FR="Bonjour, je vous présente aujourd'hui une voix naturelle. Elle parle posément, avec des phrases de longueurs différentes. Le soleil se couche doucement derrière les collines, et les oiseaux rentrent au nid. Demain matin, nous reprendrons la route avant l'aube."
EN="Good evening, and welcome. Tonight I would like to tell you a short story, spoken slowly and clearly. The river runs quietly past the old mill, and the lanterns are lit along the shore. Tomorrow we travel on before sunrise."
# id | voix piper | locuteur | demi-tons (référence décalée) | langue
TABLE="femme-claire|fr_FR-siwis-medium||0|fr
femme-chaleureuse|fr_FR-upmc-medium|0|0|fr
femme-posee|fr_FR-mls-medium|12|-1|fr
homme-pose|fr_FR-tom-medium||0|fr
homme-grave|fr_FR-tom-medium||-3|fr
homme-jeune|fr_FR-mls-medium|82|1|fr
homme-narrateur|fr_FR-mls-medium|5|0|fr
voix-aigue|fr_FR-upmc-medium|0|3|fr
voix-agee|fr_FR-upmc-medium|1|-1|fr
anonyme|fr_FR-mls-medium|42|0|fr
en-femme-claire|en_US-lessac-medium||0|en
en-femme-chaleureuse|en_GB-jenny_dioco-medium||0|en
en-homme-pose|en_US-ryan-high||0|en
en-homme-grave|en_US-ryan-high||-3|en
narrateur-en|en_GB-alan-medium||0|en"
PIPER=${ATELIER_PIPER_BIN:-piper}
mkdir -p "$DIR"
ok=0; skip=0
while IFS='|' read -r id voice spk st lang; do
  [ -n "$only" ] && [ "$only" != "$id" ] && continue
  echo "$id <- $voice${spk:+ (locuteur $spk)}${st:+ ${st} dt}"
  [ $dry = 1 ] && continue
  onnx="$PIPER_DIR/$voice.onnx"
  if [ ! -f "$onnx" ]; then
    uv tool run --from piper-tts python -m piper.download_voices "$voice" --download-dir "$PIPER_DIR" >/dev/null 2>&1 || true
  fi
  if [ ! -f "$onnx" ]; then echo "  saut: voix $voice introuvable" >&2; skip=$((skip+1)); continue; fi
  txt=$FR; [ "$lang" = en ] && txt=$EN
  tmp=$(mktemp --suffix=.wav)
  args=(-m "$onnx" -f "$tmp"); [ -n "$spk" ] && args+=(--speaker "$spk")
  if ! printf '%s' "$txt" | "$PIPER" "${args[@]}" >/dev/null 2>&1; then echo "  saut: piper a échoué" >&2; skip=$((skip+1)); rm -f "$tmp"; continue; fi
  af="anull"
  if [ "${st:-0}" != 0 ]; then af=$(python3 -c "print(f'rubberband=pitch={2**(${st}/12):.4f}:formant=preserved')"); fi
  ffmpeg -nostdin -loglevel error -y -i "$tmp" -af "$af" -ar 22050 -ac 1 -c:a pcm_s16le "$DIR/$id.wav" && ok=$((ok+1))
  rm -f "$tmp"
done <<< "$TABLE"
echo "références: $ok créées, $skip sautées -> $DIR"
