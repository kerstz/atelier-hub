#!/usr/bin/env bash
# Rejoue tous les smokes et résume. --quick saute 3/4/5 (réseau YouTube, whisper, PDF: longs).
# Usage: scripts/smoke-all.sh [--quick] [N ...]   (N = numéros de phase à jouer, ex: 10 11)
cd "$(dirname "$0")/.."
quick=0; only=()
for a in "$@"; do case $a in --quick) quick=1 ;; [0-9]*) only+=("$a") ;; *) echo "option inconnue: $a" >&2; exit 64 ;; esac; done
scripts=(smoke.sh smoke2.sh smoke3.sh smoke4.sh smoke5.sh smoke6.sh smoke7.sh smoke9.sh smoke10.sh smoke11.sh smoke12.sh smoke13.sh smoke14.sh smoke15.sh smoke16.sh smoke17.sh smoke18.sh)
slow=" 3 4 5 "
tot_ok=0; tot_fail=0; tot_skip=0; bad=()
printf '%-12s %5s %5s %5s  %s\n' script ok FAIL skip temps
for s in "${scripts[@]}"; do
  n=${s#smoke}; n=${n%.sh}; n=${n:-1}
  [ ${#only[@]} -gt 0 ] && [[ " ${only[*]} " != *" $n "* ]] && continue
  if [ $quick = 1 ] && [[ "$slow" == *" $n "* ]]; then printf '%-12s %s\n' "$s" "(sauté: --quick)"; continue; fi
  out=$(mktemp); t0=$(date +%s)
  timeout 900 bash "scripts/$s" >"$out" 2>&1; rc=$?
  ok=$(grep -c '^ok ' "$out"); ko=$(grep -c '^FAIL' "$out"); sk=$(grep -Eic '^skip|ignoré' "$out")
  printf '%-12s %5s %5s %5s  %ss%s\n' "$s" "$ok" "$ko" "$sk" $(( $(date +%s) - t0 )) "$([ $rc = 124 ] && echo ' TIMEOUT')"
  tot_ok=$((tot_ok+ok)); tot_fail=$((tot_fail+ko)); tot_skip=$((tot_skip+sk))
  if [ $ko -gt 0 ] || [ $rc -ne 0 ]; then bad+=("$s"); grep '^FAIL' "$out" | sed 's/^/     /'; [ $ko = 0 ] && tail -3 "$out" | sed 's/^/     /'; fi
  rm -f "$out"
done
echo "---"
echo "total: $tot_ok ok, $tot_fail FAIL, $tot_skip skip"
[ ${#bad[@]} -eq 0 ] && echo "TOUT OK" || { echo "À REVOIR: ${bad[*]}"; exit 1; }
