import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from gateway.app import create_app
from gateway.config import Settings
from gateway.protocol import StreamMonitor

KEY = "test-only-key-with-more-than-24-characters"
MODEL = "test-model"
HEADERS = {"Authorization": f"Bearer {KEY}"}
PAYLOAD = {"model": MODEL, "messages": [{"role": "user", "content": "hello"}]}


def settings(**changes):
    return Settings(api_key=KEY, model=MODEL, **changes)


def backend(request):
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": MODEL}]})
    body = json.loads(request.content)
    if body.get("stream"):
        content = (
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            'data: {"choices":[],"usage":{"completion_tokens":2}}\n\n'
            "data: [DONE]\n\n"
        )
        return httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"role": "assistant", "content": "Hello"}}],
            "usage": {"completion_tokens": 2},
        },
    )


@pytest.fixture
def client():
    with TestClient(create_app(settings(), httpx.MockTransport(backend))) as client:
        yield client


def test_auth_and_allowlisted_model(client):
    assert client.post("/v1/chat/completions", json=PAYLOAD).status_code == 401
    assert (
        client.post(
            "/v1/chat/completions",
            json=PAYLOAD,
            headers={
                "Authorization": "Bearer invalid-token",
            },
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/v1/chat/completions", json={**PAYLOAD, "model": "other"}, headers=HEADERS
        ).status_code
        == 400
    )
    assert client.get("/v1/models", headers=HEADERS).json()["data"][0]["id"] == MODEL


def test_completion_and_metrics(client):
    response = client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "Hello"
    metrics = client.get("/metrics").text
    assert 'llm_requests_total{outcome="success"} 1.0' in metrics
    assert "llm_completion_tokens_total 2.0" in metrics
    assert "llm_inflight 0.0" in metrics


def test_stream_and_ttft(client):
    response = client.post(
        "/v1/chat/completions", json={**PAYLOAD, "stream": True}, headers=HEADERS
    )
    assert response.status_code == 200
    assert "data: [DONE]" in response.text
    metrics = client.get("/metrics").text
    assert "llm_ttft_seconds_count 1.0" in metrics
    assert "llm_completion_tokens_total 2.0" in metrics
    assert "llm_inflight 0.0" in metrics


def test_limits_and_unknown_fields(client):
    assert (
        client.post(
            "/v1/chat/completions", json={**PAYLOAD, "max_tokens": 513}, headers=HEADERS
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/v1/chat/completions", json={**PAYLOAD, "tools": []}, headers=HEADERS
        ).status_code
        == 422
    )
    assert (
        client.post("/v1/chat/completions", content=b"x" * 65537, headers=HEADERS).status_code
        == 413
    )


def test_rate_limit():
    with TestClient(create_app(settings(requests_per_minute=1), httpx.MockTransport(backend))) as c:
        assert c.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS).status_code == 200
        response = c.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0


@pytest.mark.parametrize("status", [429, 500, 503])
def test_backend_failure_is_sanitized_and_releases_slot(status):
    def failing(request):
        return httpx.Response(status, text="private backend information")

    with TestClient(create_app(settings(), httpx.MockTransport(failing))) as c:
        response = c.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
        assert response.status_code == 502
        assert "private" not in response.text
        assert "llm_inflight 0.0" in c.get("/metrics").text


@pytest.mark.parametrize("response_body", ["not-json", '{"choices":[]}'])
def test_invalid_backend_json(response_body):
    with TestClient(
        create_app(
            settings(),
            httpx.MockTransport(
                lambda r: httpx.Response(200, text=response_body),
            ),
        )
    ) as c:
        assert c.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS).status_code == 502


def test_readiness_checks_exact_model(client):
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    with TestClient(
        create_app(
            settings(),
            httpx.MockTransport(
                lambda r: httpx.Response(200, json={"data": [{"id": "wrong-model"}]}),
            ),
        )
    ) as c:
        assert c.get("/readyz").status_code == 503


async def test_timeout_releases_slot():
    async def slow(request):
        await asyncio.sleep(0.1)
        return backend(request)

    app = create_app(settings(request_timeout=0.01), httpx.MockTransport(slow))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as c,
    ):
        assert (
            await c.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
        ).status_code == 504
        assert "llm_inflight 0.0" in (await c.get("/metrics")).text


async def test_capacity_and_cancellation_release():
    entered = asyncio.Event()

    async def blocked(request):
        entered.set()
        await asyncio.Event().wait()

    app = create_app(settings(max_inflight=1), httpx.MockTransport(blocked))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as c,
    ):
        first = asyncio.create_task(c.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS))
        await asyncio.wait_for(entered.wait(), 1)
        assert (
            await c.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
        ).status_code == 429
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert "llm_inflight 0.0" in (await c.get("/metrics")).text


async def test_chunked_body_limit():
    async def chunks():
        yield b"x" * 40000
        yield b"x" * 40000

    app = create_app(settings(), httpx.MockTransport(backend))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as c,
    ):
        assert (await c.post("/v1/chat/completions", content=chunks())).status_code == 413


class BrokenStream(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
        raise httpx.ReadError("connection lost")


def test_stream_error_is_visible_and_releases_slot():
    with TestClient(
        create_app(
            settings(),
            httpx.MockTransport(
                lambda r: httpx.Response(
                    200, stream=BrokenStream(), headers={"content-type": "text/event-stream"}
                ),
            ),
        )
    ) as c:
        response = c.post("/v1/chat/completions", json={**PAYLOAD, "stream": True}, headers=HEADERS)
        assert "Backend stream failed" in response.text
        assert 'llm_requests_total{outcome="error"} 1.0' in c.get("/metrics").text
        assert "llm_inflight 0.0" in c.get("/metrics").text


def test_fragmented_sse_and_no_word_count_estimates():
    monitor = StreamMonitor()
    message = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\n'
    for byte in message:
        monitor.feed(bytes([byte]))
    assert monitor.has_content
    assert monitor.completion_tokens == 0
    monitor.feed(b'data: {"usage":{"completion_tokens":3}}\n\ndata: [DONE]\n\n')
    assert monitor.done and monitor.completion_tokens == 3


def test_settings_require_secret():
    with pytest.raises(ValueError):
        Settings(api_key="")
