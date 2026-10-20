#!/usr/bin/env bash
# Reproducibly produce the GGUF files published in the Hugging Face model repo.
#
#   ./hf_model/quantize.sh            # writes hf_model/work/out/*.gguf
#
# Inputs are pinned: base checkpoint revision and llama.cpp commit.
set -euo pipefail

BASE_MODEL="Qwen/Qwen3-1.7B"
BASE_REVISION="70d244cc86ccca08cf5af4e1e306ecf908b1ad5e"
LLAMA_CPP_REF="${LLAMA_CPP_REF:-b11755}"  # llama.cpp release tag; recorded in the model card

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$HERE/work"
mkdir -p "$WORK/out"
cd "$WORK"

if [ ! -d llama.cpp ]; then
  git clone --depth 1 --branch "$LLAMA_CPP_REF" https://github.com/ggml-org/llama.cpp.git
fi

python3 -m venv .venv-quant
. .venv-quant/bin/activate
pip install -q -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt "huggingface_hub>=0.24"

python - <<PY
from huggingface_hub import snapshot_download
snapshot_download("${BASE_MODEL}", revision="${BASE_REVISION}", local_dir="base",
                  allow_patterns=["*.json", "*.safetensors", "*.txt", "LICENSE", "merges.txt", "vocab.json"])
PY

cmake -S llama.cpp -B llama.cpp/build -DGGML_NATIVE=OFF -DLLAMA_CURL=OFF
cmake --build llama.cpp/build --target llama-quantize -j

python llama.cpp/convert_hf_to_gguf.py base --outtype bf16 --outfile out/qwen3-1.7b-bf16.gguf
./llama.cpp/build/bin/llama-quantize out/qwen3-1.7b-bf16.gguf out/qwen3-1.7b-q8_0.gguf Q8_0
./llama.cpp/build/bin/llama-quantize out/qwen3-1.7b-bf16.gguf out/qwen3-1.7b-q4_k_m.gguf Q4_K_M
rm -f out/qwen3-1.7b-bf16.gguf

( cd out && shasum -a 256 *.gguf | tee SHA256SUMS )
echo "llama.cpp ref: $LLAMA_CPP_REF ($(git -C llama.cpp rev-parse HEAD))" | tee out/BUILD_INFO
echo "base: $BASE_MODEL@$BASE_REVISION" | tee -a out/BUILD_INFO
