#!/usr/bin/env bash
# bitstring 5 casse babeldoc; un `uv tool upgrade pdf2zh-next` le remet.
set -euo pipefail
py="$HOME/.local/share/uv/tools/pdf2zh-next/bin/python"
if [ ! -x "$py" ]; then
  uv tool install --python 3.12 pdf2zh-next
fi
cur="$("$py" -c 'import importlib.metadata as m; print(m.version("bitstring"))' 2>/dev/null || echo none)"
case "$cur" in
  4.*|3.*) echo "bitstring $cur ok"; exit 0 ;;
esac
uv pip install --quiet --python "$py" "bitstring<5"
"$py" -c 'import babeldoc' && echo "bitstring fixé, babeldoc import ok"
