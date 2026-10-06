#!/usr/bin/env bash
set -euo pipefail
# Use the ordinary HTTP downloader for predictable downloads on local networks.
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
if [[ -f .env ]]; then
  set -a
  source .env
  set +a
fi
exec vllm serve "${MODEL_ID:-mlx-community/Qwen2.5-7B-Instruct-4bit}" \
  --host 127.0.0.1 --port 8001 \
  --max-model-len 4096 --max-num-seqs 4
