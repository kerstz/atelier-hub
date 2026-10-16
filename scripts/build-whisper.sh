#!/usr/bin/env bash
set -euo pipefail
dir="$HOME/.local/opt/whisper.cpp"
model="$dir/models/ggml-large-v3-turbo.bin"
fetch_model() {
  [ -s "$model" ] && return 0
  mkdir -p "$dir/models"
  curl -L --fail -C - -o "$model" \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
}
if [ "$(uname)" = Darwin ]; then
  # macOS: Homebrew whisper-cpp (Metal) instead of a Vulkan build; only the model is fetched here
  command -v whisper-cli >/dev/null 2>&1 || { echo "whisper-cli absent: brew install whisper-cpp" >&2; exit 1; }
  fetch_model
  echo "ok: $(command -v whisper-cli) / $model"
  exit 0
fi
mkdir -p "$HOME/.local/opt" "$HOME/.local/bin"
if [ ! -d "$dir/.git" ]; then
  git clone --depth 1 --branch v1.9.4 https://github.com/ggml-org/whisper.cpp "$dir" \
    || git clone --depth 1 https://github.com/ggml-org/whisper.cpp "$dir"
fi
cd "$dir"
echo "build Vulkan: plusieurs minutes (compilation shaders), ne pas interrompre"
cmake -B build -DGGML_VULKAN=1 -DCMAKE_BUILD_TYPE=Release -Wno-dev -Wno-deprecated >/dev/null 2>&1
cmake --build build -j"$(nproc)" --target whisper-cli 2>&1 | grep -E "^\[ *[0-9]+%\].*(Linking|Built target)|error|Error" || true
test -x build/bin/whisper-cli || { echo "build échoué (relancer sans filtre: cmake --build build)"; exit 1; }
ln -sf "$dir/build/bin/whisper-cli" "$HOME/.local/bin/whisper-cli"
fetch_model
echo "ok: $(command -v whisper-cli) / $model"
