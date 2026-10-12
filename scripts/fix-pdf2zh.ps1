# bitstring 5 casse babeldoc; un `uv tool upgrade pdf2zh-next` le remet.
$ErrorActionPreference = "Stop"
$dir = (uv tool dir).Trim()
$py = Join-Path $dir "pdf2zh-next\Scripts\python.exe"
if (-not (Test-Path $py)) { uv tool install --python 3.12 pdf2zh-next }
$cur = & $py -c "import importlib.metadata as m; print(m.version('bitstring'))" 2>$null
if ($cur -match '^[34]\.') { Write-Host "bitstring $cur ok"; exit 0 }
uv pip install --quiet --python $py "bitstring<5"
& $py -c "import babeldoc" 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "bitstring fixé, babeldoc import ok" }
