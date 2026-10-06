# Inference runbooks

## Model startup or download failure

1. Run `curl -f http://127.0.0.1:8001/v1/models`.
2. Inspect the engine terminal for download errors, unsupported architecture, or memory pressure.
3. Confirm `MODEL_ID` matches the engine's advertised model ID.
4. Start with a supported checkpoint and conservative context/concurrency limits.
5. Restart the gateway after editing `.env`; its configuration is loaded at startup.

`/healthz` only confirms the gateway is alive. `/readyz` checks that the backend advertises the
configured model. Readiness failure is `503`, so Kubernetes will remove the gateway from ready endpoints.

## GPU memory pressure

1. Stop load tests and inspect engine logs and macOS memory pressure.
2. Close unused memory-heavy applications.
3. Reduce `--max-num-seqs`, `--max-model-len`, and the gateway's output-token limit.
4. Use a smaller supported model or quantized checkpoint and rerun smoke/benchmarks.
5. Record the changed configuration. Do not compare its timings as if the configuration were identical.

The Mac has unified memory, not a separate CUDA VRAM pool. This project does not change system
wired-memory limits automatically.

## Requests return 429

- `Inference capacity reached`: active workload reached `MAX_INFLIGHT`.
- `Rate limit reached`: the single-key token bucket is exhausted.
- Honor `Retry-After`, reduce arrival rate, and inspect `llm_rejected_total`.
- Raise limits only after testing memory and latency at the proposed concurrency.

## Requests return 502/504 or a stream contains an error

1. Check `/readyz` and backend logs.
2. Inspect `llm_requests_total{outcome="error"}` and request-duration histograms.
3. Check model context limits, engine overload, and the configured deadline.
4. Retest with a short prompt and low output-token limit.

An SSE error after headers cannot change HTTP 200 to an error status. Clients must inspect SSE
error events and terminal completion. The included benchmark does so.

## Demonstrate a backend outage and recovery

1. With the gateway running, stop the engine using Ctrl-C in its terminal.
2. Confirm `/readyz` returns 503 and a generation request fails with a sanitized backend error.
3. Inspect gateway error metrics.
4. Restart `make engine`, wait for model readiness, and rerun `scripts/smoke.py`.

This is a reversible local failure exercise. Never perform it against a shared deployment.

## Monitoring cannot reach the native Mac processes

Docker Desktop containers use `host.docker.internal` rather than container-local `127.0.0.1`.
Check the target error in Prometheus. If your Docker Desktop setup cannot reach loopback-bound
host services, keep native inference local and run the monitoring processes natively, or use a
deliberately restricted host interface with suitable backend access controls. Do not expose an
unauthenticated engine publicly to solve a scrape connectivity issue.

## Stop the demo

- Ctrl-C in the gateway and engine terminals.
- `make stop-observability` removes the demo monitoring containers.
- Downloaded model weights remain cached for later runs.
