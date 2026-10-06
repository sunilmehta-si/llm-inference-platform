"""Generate the benchmark comparison from raw JSON, without invented observations."""

import json
from pathlib import Path


def main():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    root = Path("benchmarks")
    reports = [json.loads((root / f"mac-concurrency-{n}.json").read_text()) for n in (1, 4)]
    for field in ("model", "model_revision", "backend", "hardware"):
        if reports[0][field] != reports[1][field]:
            raise SystemExit(f"Cannot compare runs with different {field}")
    rows = []
    for report in reports:
        summary = report["summary"]
        rows.append(
            f"| {report['configuration']['concurrency']} "
            f"| {summary['successful_requests']}/{report['configuration']['requests']} "
            f"| {summary['aggregate_output_tokens_per_second']:.2f} "
            f"| {summary['ttft_p50_seconds'] * 1000:.1f} "
            f"| {summary['ttft_p95_seconds'] * 1000:.1f} "
            f"| {summary['latency_p95_seconds']:.2f} |"
        )
    throughput = [r["summary"]["aggregate_output_tokens_per_second"] for r in reports]
    ttft = [r["summary"]["ttft_p95_seconds"] * 1000 for r in reports]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.4), layout="constrained")
    fig.patch.set_facecolor("#f5f7fb")
    colors = ["#087f8c", "#7357c6"]
    for ax, values, title, unit in zip(
        axes,
        (throughput, ttft),
        ("Aggregate output throughput", "First-token latency / p95"),
        ("tokens / second", "milliseconds"),
        strict=True,
    ):
        bars = ax.bar(["Concurrency 1", "Concurrency 4"], values, color=colors, width=0.56)
        ax.set_title(title, fontsize=12, loc="left", pad=14)
        ax.set_ylabel(unit)
        ax.set_ylim(0, max(values) * 1.24)
        ax.set_axisbelow(True)
        ax.grid(axis="y", alpha=0.15)
        ax.spines[["top", "right"]].set_visible(False)
        ax.bar_label(bars, labels=[f"{v:.1f}" for v in values], padding=6, fontsize=11)
    fig.suptitle("Apple M5 Pro / Qwen2.5 7B / 4-bit / vLLM-Metal", fontsize=15)
    fig.savefig(root / "comparison.png", dpi=180)
    fig.savefig(root / "comparison.svg")
    plt.close(fig)
    header = f"""# Measured GPU inference on Apple M5 Pro

Recorded on 6 October 2026 with **48 GiB unified memory** and macOS 27.0.1.
Engine: `{reports[0]["backend"]}`. Model: `{reports[0]["model"]}`.
Checkpoint revision: `{reports[0]["model_revision"]}`.

![Measured throughput and first-token latency](comparison.png)

| Concurrency | Success | Tokens/s | TTFT p50 (ms) | TTFT p95 (ms) | Completion p95 (s) |
|---|---|---|---|---|---|
"""
    text = (
        header
        + "\n".join(rows)
        + """

Both runs use 12 measured requests, two warmup requests, the same four short prompts,
temperature zero, and an output limit of 128 tokens. All 24 measured requests completed.
Engine settings: context 4096, maximum four sequences, chunked prefill 2048, prefix caching
enabled, and the observed default GPU memory utilization setting of 0.92.

**Interpretation:** four concurrent requests increase aggregate throughput, while individual
requests take longer and first-token tail latency rises. This is a throughput/latency tradeoff,
not an across-the-board performance improvement. The small sample and repeated prompts do not
establish production capacity, an SLA, or cold-start behavior.

GPU execution was confirmed by engine startup: MLX `Device(gpu, 0)`, PyTorch `mps`, native
paged-attention Metal kernels, and M5 NAX prefill attention kernels. A `+cpu` package suffix or
CPU-named bookkeeping field in vLLM does not identify this plugin's actual compute backend.

Raw observations: [concurrency 1](mac-concurrency-1.json), [concurrency 4](mac-concurrency-4.json).
See [measurement methodology](../docs/benchmarking.md) for metric definitions and limitations.

Recreate the chart after installing the optional reporting dependency:

```bash
.venv/bin/python -m pip install -e '.[report]'
make report
```
"""
    )
    (root / "README.md").write_text(text)
    print("Generated benchmark table, PNG, and SVG from the two raw reports")


if __name__ == "__main__":
    main()
