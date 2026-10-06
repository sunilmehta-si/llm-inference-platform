"""Streaming benchmark: reported tokens, first-content latency, errors, and metadata."""

import argparse
import asyncio
import json
import os
import platform
import statistics
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from gateway.protocol import StreamMonitor

PROMPTS = [
    "Explain Kubernetes readiness and liveness probes in three short sentences.",
    "Give three practical ways to reduce LLM inference latency.",
    "Explain why a GPU inference service can run out of memory.",
    "Describe a safe rollback strategy for an inference model deployment.",
]


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def hardware():
    result = {"os": platform.platform(), "architecture": platform.machine()}
    if platform.system() == "Darwin":
        for name, key in (("machdep.cpu.brand_string", "chip"), ("hw.memsize", "memory_bytes")):
            result[key] = subprocess.check_output(["sysctl", "-n", name], text=True).strip()
    return result


async def one(client, args, index):
    start = time.perf_counter()
    first = None
    monitor = StreamMonitor()
    record = {"index": index, "success": False, "completion_tokens": None}
    try:
        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "model": args.model,
                "messages": [{"role": "user", "content": PROMPTS[index % len(PROMPTS)]}],
                "max_tokens": args.max_tokens,
                "temperature": 0,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        ) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                monitor.feed(chunk)
                if monitor.has_content and first is None:
                    first = time.perf_counter() - start
        if not monitor.done or monitor.failed or first is None:
            raise ValueError("incomplete_or_failed_stream")
        record.update(success=True, completion_tokens=monitor.completion_tokens or None)
    except (httpx.HTTPError, ValueError) as error:
        record["error"] = type(error).__name__
        if isinstance(error, httpx.HTTPStatusError):
            record["http_status"] = error.response.status_code
    duration = time.perf_counter() - start
    record.update(duration_seconds=duration, ttft_seconds=first)
    record["end_to_end_tokens_per_second"] = (
        record["completion_tokens"] / duration if record["completion_tokens"] else None
    )
    return record


async def run(args):
    key = os.environ.get("GATEWAY_API_KEY")
    if not key:
        raise SystemExit("Set GATEWAY_API_KEY; never put credentials in benchmark artifacts")
    records = []
    queue = asyncio.Queue()
    for index in range(args.requests):
        queue.put_nowait(index)
    async with httpx.AsyncClient(
        base_url=args.url,
        headers={"Authorization": f"Bearer {key}"},
        timeout=args.timeout,
        trust_env=False,
    ) as client:
        for index in range(args.warmup):
            warmup = await one(client, args, index)
            if not warmup["success"]:
                raise SystemExit(f"Warmup failed: {warmup}")

        async def worker():
            while not queue.empty():
                index = queue.get_nowait()
                records.append(await one(client, args, index))

        start = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(args.concurrency)))
        elapsed = time.perf_counter() - start
    successful = [record for record in records if record["success"]]
    durations = [record["duration_seconds"] for record in successful]
    first_tokens = [record["ttft_seconds"] for record in successful]
    counts = [record["completion_tokens"] for record in successful]
    all_usage = bool(counts) and all(count is not None for count in counts)
    result = {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "backend": args.backend,
        "model": args.model,
        "hardware": hardware(),
        "configuration": {
            "requests": args.requests,
            "concurrency": args.concurrency,
            "max_tokens": args.max_tokens,
            "warmup_requests": args.warmup,
            "temperature": 0,
            "prompt_set": "devops-short-v1",
        },
        "summary": {
            "successful_requests": len(successful),
            "failed_requests": len(records) - len(successful),
            "wall_seconds": elapsed,
            "latency_p50_seconds": percentile(durations, 0.5),
            "latency_p95_seconds": percentile(durations, 0.95),
            "ttft_p50_seconds": percentile(first_tokens, 0.5),
            "ttft_p95_seconds": percentile(first_tokens, 0.95),
            "aggregate_output_tokens_per_second": sum(counts) / elapsed if all_usage else None,
            "mean_end_to_end_tokens_per_second": statistics.mean(
                [record["end_to_end_tokens_per_second"] for record in successful]
            )
            if all_usage
            else None,
        },
        "limitations": [
            "Small synthetic workload; percentiles are descriptive, not capacity guarantees.",
            "Timing includes gateway/network/queueing; token counts come from backend usage only.",
            "Warmups excluded; repeated prompts may benefit from backend prefix caching.",
            "Hardware inventory is not a GPU utilization measurement.",
        ],
        "requests": sorted(records, key=lambda item: item["index"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))
    if len(successful) != args.requests:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--model", default=os.environ.get("MODEL_ID", ""))
    parser.add_argument("--backend", required=True, help="Actual engine and version")
    parser.add_argument("--requests", type=int, default=12)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=128)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--output", type=Path, default=Path("benchmarks/local.json"))
    args = parser.parse_args()
    if not args.model or min(args.requests, args.concurrency, args.max_tokens, args.timeout) <= 0:
        parser.error("Model and positive request/concurrency/token/timeout values are required")
    if args.warmup < 0:
        parser.error("Warmup must be nonnegative")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
