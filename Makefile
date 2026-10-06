PYTHON ?= python3.13
VENV := .venv/bin

.PHONY: setup key engine gateway test lint check benchmark observability stop-observability helm-check
setup:
	$(PYTHON) -m venv .venv
	$(VENV)/python -m pip install -c requirements-tested.txt -e '.[dev]'

key:
	$(VENV)/python scripts/init_env.py

engine:
	bash scripts/serve-metal.sh

gateway:
	bash scripts/serve-gateway.sh

test:
	$(VENV)/python -m pytest -q

lint:
	$(VENV)/ruff check .
	$(VENV)/ruff format --check .

check: lint test helm-check

helm-check:
	helm lint deploy/helm/inference --set gateway.existingSecret=inference-gateway-key
	helm template inference deploy/helm/inference --set gateway.existingSecret=inference-gateway-key >/dev/null
	helm template inference deploy/helm/inference -f deploy/helm/inference/values-nvidia.yaml --set gateway.existingSecret=inference-gateway-key >/dev/null

benchmark:
	$(VENV)/python -m scripts.benchmark --backend "$${BACKEND_VERSION:?Set BACKEND_VERSION}" --output benchmarks/local.json

report:
	$(VENV)/python -m scripts.report

observability:
	docker compose -f deploy/compose.yaml up -d

stop-observability:
	docker compose -f deploy/compose.yaml down
