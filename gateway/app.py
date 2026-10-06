import asyncio
import json
import logging
import math
import secrets
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from gateway.config import Settings
from gateway.protocol import StreamMonitor

logger = logging.getLogger("gateway")


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern="^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=32000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[Message] = Field(min_length=1, max_length=64)
    max_tokens: int = Field(default=128, ge=1, le=4096)
    temperature: float = Field(default=0.2, ge=0, le=2)
    stream: bool = False
    stream_options: dict[str, bool] | None = None


class BodyLimit:
    """Enforce body size for both Content-Length and chunked requests."""

    def __init__(self, app, limit):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        body = bytearray()
        while True:
            event = await receive()
            if event["type"] == "http.disconnect":
                return
            body.extend(event.get("body", b""))
            if len(body) > self.limit:
                response = JSONResponse({"error": "request_body_too_large"}, status_code=413)
                return await response(scope, receive, send)
            if not event.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None, transport=None):
    settings = settings or Settings.from_env()
    registry = CollectorRegistry()
    requests = Counter("llm_requests_total", "Completed requests", ["outcome"], registry=registry)
    rejected = Counter("llm_rejected_total", "Rejected requests", ["reason"], registry=registry)
    inflight = Gauge("llm_inflight", "Active upstream requests", registry=registry)
    latency = Histogram(
        "llm_request_duration_seconds",
        "Request duration",
        ["mode"],
        buckets=(0.1, 0.5, 1, 2, 5, 10, 30, 60, 120),
        registry=registry,
    )
    ttft = Histogram(
        "llm_ttft_seconds",
        "Time to first content in a stream",
        buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30),
        registry=registry,
    )
    tokens = Counter("llm_completion_tokens_total", "Backend-reported tokens", registry=registry)
    active = 0
    bucket_tokens = float(settings.requests_per_minute)
    bucket_updated = time.monotonic()
    lock = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(
            base_url=settings.backend_url,
            transport=transport,
            timeout=httpx.Timeout(settings.request_timeout, connect=5),
            limits=httpx.Limits(max_connections=settings.max_inflight + 2),
            trust_env=False,
        ) as client:
            app.state.client = client
            yield

    app = FastAPI(title="LLM Inference Platform", version="0.1.0", lifespan=lifespan)
    app.add_middleware(BodyLimit, limit=settings.max_body_bytes)
    app.state.settings = settings

    async def authorize(authorization: str | None = Header(default=None)):
        supplied = (authorization or "").removeprefix("Bearer ")
        if (
            not authorization
            or not authorization.startswith("Bearer ")
            or not secrets.compare_digest(
                supplied.encode(),
                settings.api_key.encode(),
            )
        ):
            rejected.labels("auth").inc()
            raise HTTPException(401, "Invalid bearer token", headers={"WWW-Authenticate": "Bearer"})

    async def admit():
        nonlocal active, bucket_tokens, bucket_updated
        async with lock:
            now = time.monotonic()
            bucket_tokens = min(
                settings.requests_per_minute,
                bucket_tokens + (now - bucket_updated) * settings.requests_per_minute / 60,
            )
            bucket_updated = now
            if active >= settings.max_inflight:
                rejected.labels("capacity").inc()
                raise HTTPException(429, "Inference capacity reached", headers={"Retry-After": "1"})
            if bucket_tokens < 1:
                rejected.labels("rate").inc()
                retry = math.ceil((1 - bucket_tokens) * 60 / settings.requests_per_minute)
                raise HTTPException(429, "Rate limit reached", headers={"Retry-After": str(retry)})
            bucket_tokens -= 1
            active += 1
            inflight.inc()

    async def release():
        nonlocal active
        async with lock:
            active -= 1
            inflight.dec()

    @app.get("/healthz")
    async def health():
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready(request: Request):
        try:
            response = await request.app.state.client.get("/v1/models", timeout=5)
            response.raise_for_status()
            models = response.json().get("data", [])
            if not any(model.get("id") == settings.model for model in models):
                return JSONResponse({"status": "model_unavailable"}, status_code=503)
            return {"status": "ready", "model": settings.model}
        except (httpx.HTTPError, ValueError):
            return JSONResponse({"status": "backend_unavailable"}, status_code=503)

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")

    @app.get("/v1/models", dependencies=[Depends(authorize)])
    async def models():
        return {"object": "list", "data": [{"id": settings.model, "object": "model"}]}

    @app.post("/v1/chat/completions", dependencies=[Depends(authorize)])
    async def chat(body: ChatRequest, request: Request):
        if body.model != settings.model:
            raise HTTPException(400, "Model is not configured")
        if body.max_tokens > settings.max_output_tokens:
            raise HTTPException(400, "Output token limit exceeded")
        if body.stream_options and set(body.stream_options) - {"include_usage"}:
            raise HTTPException(400, "Unsupported stream option")
        await admit()
        start = time.monotonic()
        upstream = None
        owns_slot = True
        mode = "stream" if body.stream else "json"
        outcome = "error"
        try:
            async with asyncio.timeout(settings.request_timeout):
                payload = body.model_dump(exclude_none=True)
                if body.stream:
                    payload["stream_options"] = {"include_usage": True}
                client = request.app.state.client
                upstream = await client.send(
                    client.build_request("POST", "/v1/chat/completions", json=payload),
                    stream=True,
                )
                upstream.raise_for_status()
                if not body.stream:
                    raw = await upstream.aread()
                    result = json.loads(raw)
                    if result.get("error") or not result.get("choices"):
                        raise ValueError("Invalid backend response")
                    count = (result.get("usage") or {}).get("completion_tokens", 0)
                    if isinstance(count, int) and count >= 0:
                        tokens.inc(count)
                    outcome = "success"
                    return JSONResponse(result)
            if "text/event-stream" not in upstream.headers.get("content-type", ""):
                raise ValueError("Backend did not return SSE")

            async def stream():
                stream_outcome = "cancelled"
                monitor = StreamMonitor()
                observed_ttft = False
                try:
                    remaining = max(0.001, settings.request_timeout - (time.monotonic() - start))
                    async with asyncio.timeout(remaining):
                        async for chunk in upstream.aiter_bytes():
                            monitor.feed(chunk)
                            if monitor.has_content and not observed_ttft:
                                ttft.observe(time.monotonic() - start)
                                observed_ttft = True
                            yield chunk
                    if not monitor.done or monitor.failed:
                        raise ValueError("Incomplete or failed backend stream")
                    stream_outcome = "success"
                    tokens.inc(monitor.completion_tokens)
                except (httpx.HTTPError, TimeoutError, ValueError):
                    stream_outcome = "error"
                    yield b'data: {"error":{"message":"Backend stream failed"}}\n\n'
                    yield b"data: [DONE]\n\n"
                finally:
                    await upstream.aclose()
                    await release()
                    requests.labels(stream_outcome).inc()
                    latency.labels("stream").observe(time.monotonic() - start)
                    logger.info("inference mode=stream outcome=%s", stream_outcome)

            owns_slot = False
            return StreamingResponse(
                stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )
        except (TimeoutError, httpx.TimeoutException):
            raise HTTPException(504, "Backend request timed out") from None
        except (httpx.HTTPError, ValueError):
            raise HTTPException(502, "Backend request failed") from None
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            if owns_slot:
                if upstream is not None:
                    await upstream.aclose()
                await release()
                requests.labels(outcome).inc()
                latency.labels(mode).observe(time.monotonic() - start)
                logger.info("inference mode=%s outcome=%s", mode, outcome)

    return app
