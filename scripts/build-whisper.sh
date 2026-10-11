#!/usr/bin/env bash
set -euo pipefail
dir="$HOME/.local/opt/whisper.cpp"
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
model="$dir/models/ggml-large-v3-turbo.bin"
if [ ! -s "$model" ]; then
  curl -L --fail -C - -o "$model" \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin
fi
echo "ok: $(command -v whisper-cli) / $model"
