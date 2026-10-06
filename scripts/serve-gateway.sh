#!/usr/bin/env bash
set -euo pipefail
set -a
source .env
set +a
exec .venv/bin/uvicorn gateway.app:create_app --factory \
  --host "${GATEWAY_HOST:-127.0.0.1}" --port 8000 --workers 1
