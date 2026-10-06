# Entire project walkthrough

## 1. What we built

`llm-inference-platform` demonstrates how to serve and operate an open-weight LLM.
It uses pretrained weights; we did not train a foundation model or fine-tune this checkpoint.

The model is Qwen2.5 7B Instruct in an MLX 4-bit format. vLLM-Metal loads it, tokenizes
requests, runs GPU inference, manages the KV cache and scheduling, and streams generated tokens.
Our Python gateway controls access and load, forwards requests, and records operational metrics.

Code: https://github.com/sunilmehta-si/llm-inference-platform
Local directory: `/Users/sunil/sunilmehta-si-github/llm-inference-platform`.

## 2. What is actually deployed

| Service | Runs where | Local URL | Purpose |
|---|---|---|---|
| Python gateway | Native macOS Python process | http://127.0.0.1:8000 | API boundary, auth, streaming, limits, metrics |
| Browser chat | Static HTML/CSS/JavaScript served by the gateway | http://127.0.0.1:8000/ | Enter questions and see streamed answers |
| Swagger UI | Served by the gateway | http://127.0.0.1:8000/docs | Browser interface for API requests |
| vLLM-Metal | Native macOS process / Apple GPU | http://127.0.0.1:8001 | Actual model inference |
| Prometheus | Docker Desktop container | http://127.0.0.1:9090 | Scrapes engine/gateway metrics and evaluates alerts |
| Grafana | Docker Desktop container | http://127.0.0.1:3000 | Provisioned inference dashboard |
| GitHub Actions | GitHub-hosted Linux runners | Repository Actions tab | Tests, Helm checks, gateway container build |

The public deployment is the **source repository and profile links**. There is no public inference
endpoint, cloud GPU deployment, Kubernetes installation, or paid cloud resource. Helm templates
are prepared and rendered; NVIDIA runtime execution remains unvalidated.

## 3. How setup works

```bash
cd /Users/sunil/sunilmehta-si-github/llm-inference-platform
make setup
make key
```

`make setup` creates `.venv`, installs the package and test tools using tested dependency constraints.
`make key` creates a private `.env` with a random key; if `.env` exists, it leaves it unchanged.
Both `.env` and `.venv` are ignored by Git. Do not rerun key creation expecting it to rotate a key.

Install the native engine once using the explicit Homebrew tap shown in the README.
The model is downloaded on its first launch, then reused from the local Hugging Face cache.
The startup script uses the ordinary HTTP downloader because the initial Xet transfer stalled
on this machine's connection. You can opt into Xet by setting `HF_HUB_DISABLE_XET=0`.

## 4. Start the model and gateway

Terminal A:

```bash
cd /Users/sunil/sunilmehta-si-github/llm-inference-platform
make engine
```

Wait for model loading, Metal kernel initialization, and API startup. Cached weights make later
starts faster, but model/kernel initialization still takes time. The startup script requests a
4096-token context and at most four active sequences. `MODEL_REVISION` can pin a checkpoint.

Terminal B:

```bash
cd /Users/sunil/sunilmehta-si-github/llm-inference-platform
make gateway
```

The gateway requires the key and reads `.env` at startup. It uses one worker because admission
and rate limits are process-local. If a port is already occupied by this demo, use its running
service or stop it before launching another process.

## 5. Test inference from the browser

Open **http://127.0.0.1:8000/** for the chat frontend.

1. In the left panel, paste the `GATEWAY_API_KEY` value from your local `.env` file.
2. Wait for **Model ready** in the runtime status.
3. Type a question in the large message box at the bottom right.
4. Click **Send message** or press Enter. Shift + Enter inserts a newline.
5. Watch the answer stream and inspect first-token time, total time, and output tokens.

The frontend offers sample questions, output-token and temperature controls, **Stop**, and
**Clear chat**. It keeps conversation history and the key only in page memory; reload clears
them. Partial/failed answers are not added to model conversation history. Model-generated
content is rendered as text to avoid executing generated HTML. The page uses no external
JavaScript libraries and is included in the gateway package/container.

For lower-level API inspection, use Swagger:

Open http://127.0.0.1:8000/docs.

1. Expand `GET /readyz`, click **Try it out**, then **Execute**. Expect `200` and `status: ready`.
2. Expand `POST /v1/chat/completions` and click **Try it out**.
3. In the `authorization` header field, enter `Bearer ` followed by your local `.env` key.
4. Replace the example body with:

```json
{
  "model": "mlx-community/Qwen2.5-7B-Instruct-4bit",
  "messages": [{"role": "user", "content": "Explain KV caching in three short sentences."}],
  "max_tokens": 128,
  "temperature": 0.2,
  "stream": false
}
```

5. Click **Execute**. Read the answer in `choices[0].message.content` and the token counts in `usage`.

Use `stream: false` in Swagger for a straightforward complete response. Streaming is easier to
inspect using the README's `curl -N` command or a dedicated chat client.

Swagger is the API documentation UI; the separate chat frontend is served at `/`.
Neither page exposes the configured key itself.
The example key appears only in `.env.example`; `make key` generates a real private value locally.

## 6. Follow a request through the system

```mermaid
sequenceDiagram
    participant User as Browser / client
    participant API as Gateway
    participant Engine as vLLM-Metal
    participant GPU as Apple GPU
    User->>API: Chat request + bearer key
    API->>API: Validate body, model, output limit, rate, capacity
    API->>Engine: Forward accepted request
    Engine->>GPU: Prefill prompt and decode tokens
    GPU-->>Engine: Model outputs
    Engine-->>API: JSON or SSE + reported usage
    API-->>User: Answer / streamed tokens
    API->>API: Record outcome, latency, tokens; release slot
```

The gateway returns `401` for an invalid key, `400/422` for rejected input, `413` for an oversized
body, `429` for rate/capacity limits, `502` for upstream failures, and `504` for upstream timeout.
After streaming starts, errors appear in the SSE stream because HTTP headers are already sent.

## 7. Start and check monitoring

```bash
make observability
```

Open http://127.0.0.1:9090/targets. Both `gateway` and `engine` should be UP once the model is ready.
Prometheus scrapes every five seconds. Engine startup can show DOWN until its API is running.

Open http://127.0.0.1:3000/d/llm-inference/llm-inference-gateway.
The dashboard is provisioned automatically; anonymous access is read-only and ports are bound
to loopback. It displays inflight requests, success/error rates, p95 first-token/completion
latency, reported token rate, and rejected requests. Generate requests, then allow a scrape
interval for updates. Quiet periods or no requests can leave histogram panels empty.

This dashboard measures inference-service behavior. It does not claim NVIDIA GPU utilization,
CUDA VRAM, Apple GPU power consumption, or model accuracy.

## 8. Run reproducible benchmarks

```bash
bash scripts/run-benchmark.sh \
  --backend 'vllm-metal 0.30.0 / vLLM 0.30.0' \
  --model-revision c26a38f6a37d0a51b4e9a1eb3026530fa35d9fed \
  --requests 12 --concurrency 1 --max-tokens 128 \
  --output benchmarks/mac-concurrency-1.json
```

Repeat with concurrency 4 and a different output filename. The command loads `.env` without
printing the key, warms up, sends a bounded concurrent workload, inspects SSE, and writes raw
measurements plus hardware/configuration metadata. It exits with failure if any measured request
fails. See the existing [measured results](../benchmarks/README.md) for the actual tradeoff observed.

## 9. Understand automation and containers

`make check` runs Python lint, formatting checks, operational regression tests, and Helm lint/
rendering for both deployment profiles. Tests use a deterministic backend so ordinary GitHub
runners do not need a GPU. GitHub Actions also builds the gateway Docker image on Linux.

The gateway container is portable; model weights and API credentials are excluded from its
build context. The Mac model engine stays native to access Metal. The optional NVIDIA chart
instead runs an NVIDIA vLLM image on a Linux GPU node. See [deployment](deployment.md).

## 10. Stop and restart

Stop the model/gateway with Ctrl-C in their terminals. Stop the monitoring containers with:

```bash
make stop-observability
```

Weights stay cached, and the public repository remains available. Restart by repeating the
engine, gateway, and monitoring commands. Consult [runbooks](runbooks.md) for failures and recovery.
