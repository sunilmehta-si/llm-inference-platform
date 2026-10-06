# Benchmark methodology

Run the same checkpoint with fixed generation settings and a documented concurrency level.
The included four short prompts are infrastructure questions. They are synthetic inputs,
not training data or employer incidents. Warm up before starting the measured batch.

Recorded fields:

| Field | Meaning |
|---|---|
| TTFT | Client start to first non-empty content/reasoning SSE delta |
| Completion latency | Client start to complete terminal stream |
| Aggregate output tokens/s | Sum of successful backend-reported output tokens / measured batch wall time |
| Per-request end-to-end tokens/s | Reported output tokens / total request duration |
| p50 / p95 | Linearly interpolated percentiles of successful requests |
| Failure count | HTTP, stream, parsing, and transport failures |

Reports include engine/version (supplied explicitly), model ID, OS, chip, memory, warmup count,
request count, concurrency, output-token limit, and per-request observations. The benchmark
does not measure GPU utilization, energy, token correctness, or accuracy. It records no API
key, prompt text, output text, local username, hostname, or hardware serial number.

Important interpretation:

- 12 requests form a demonstration, not a statistically strong capacity test.
- Repeated prompts may benefit from prefix caching. The first benchmark is not necessarily cold.
- Memory depends on model weights, context, KV cache, concurrency, runtime, and other Mac apps.
- Reported tokens may include reasoning tokens; TTFT may observe reasoning before visible answers.
- If backend usage is absent, throughput is null. We do not estimate tokenizer counts from words.
- Failures must remain in the report. Successful-only percentiles do not describe the whole workload.
- Compare concurrency runs on the same engine/model/configuration; do not imply cross-hardware equivalence.
- Rates exceeding `REQUESTS_PER_MINUTE` or `MAX_INFLIGHT` test gateway rejection as well as inference.

For larger studies, vary prompt lengths, output lengths, arrival patterns, cache state, and run
multiple repetitions. Save each configuration and all raw observations before drawing conclusions.
