# Architecture and tradeoffs

## Request lifecycle

1. The ASGI layer bounds POST bodies, including bodies without Content-Length.
2. The API validates a bearer key, configured model, request schema, and output limit.
3. A process-local token bucket and inflight counter admit or reject the request.
4. The gateway forwards to a fixed backend origin. Clients cannot choose a backend URL.
5. JSON responses are bounded by a deadline; SSE is inspected while passing bytes downstream.
6. Completion, error, timeout, and cancellation close the upstream response and release capacity.

The body-size limit bounds bytes, not tokenizer context length. vLLM applies the configured
4096-token context limit after tokenization. An upstream validation failure is surfaced as a
sanitized gateway error rather than exposing engine internals.

## Boundary between gateway and model runtime

The gateway does not implement inference kernels, KV cache allocation, model batching,
or GPU scheduling. Those remain engine responsibilities. It adds an operational boundary:
small accepted API, authentication, bounded admission, predictable failure responses, and
low-cardinality telemetry. There is one demo API key, one model, and one gateway process.

Local inference runs natively on macOS. The Apple GPU uses Metal through MLX. Docker and Helm
are for the portable gateway, monitoring, and separately described Linux NVIDIA deployment.
Apple Metal results must not be presented as CUDA results.

## Streaming correctness

TCP/HTTP chunks do not correspond to SSE events or tokenizer tokens. `StreamMonitor` buffers
partial lines, detects first non-empty generated content, reads reported completion usage,
and recognizes the terminal marker. A missing `[DONE]` or upstream error is a failed stream.
Benchmarks exclude failed streams from successful latency percentiles and count failures separately.

The configured timeout covers upstream work and streamed reads. A slow downstream can still
hold a slot during backpressure; a public deployment needs connection/read deadlines at its
ingress as well. Body buffering likewise needs an ingress upload deadline in a public deployment.

## Telemetry and credentials

Prometheus labels contain only bounded outcome/mode/rejection categories. No user identifiers,
prompts, keys, or model-generated text enter metrics. Health and metrics endpoints are unauthenticated
for local monitoring. Keep them within the local/internal network. The engine itself is loopback-only
on the Mac and an internal service in Kubernetes.

## Extensions requiring new validation

- Shared admission/rate state for multiple gateway replicas.
- Model-specific token budgets and authenticated model selection.
- Quantization comparisons with identical prompts, context, and generation settings.
- NVIDIA GPU runtime validation, DCGM monitoring, and cloud-specific node provisioning.
- Production ingress, TLS, access control for metrics, and distributed tracing.

These are potential extensions, not completed capabilities or production guarantees.
