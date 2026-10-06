import os
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass(frozen=True)
class Settings:
    api_key: str
    backend_url: str = "http://127.0.0.1:8001"
    model: str = "mlx-community/Qwen2.5-7B-Instruct-4bit"
    max_inflight: int = 4
    requests_per_minute: int = 60
    request_timeout: float = 120
    max_body_bytes: int = 65536
    max_output_tokens: int = 512

    def __post_init__(self):
        if len(self.api_key) < 24 or self.api_key.startswith("replace-with-"):
            raise ValueError("GATEWAY_API_KEY must contain at least 24 characters")
        url = urlparse(self.backend_url)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username:
            raise ValueError("BACKEND_URL must be an HTTP(S) URL without credentials")
        if url.path not in {"", "/"} or url.query or url.fragment:
            raise ValueError("BACKEND_URL must be an origin without a path, query, or fragment")
        for value in (
            self.max_inflight,
            self.requests_per_minute,
            self.request_timeout,
            self.max_body_bytes,
            self.max_output_tokens,
        ):
            if value <= 0:
                raise ValueError("Limits and timeouts must be positive")

    @classmethod
    def from_env(cls):
        return cls(
            api_key=os.environ.get("GATEWAY_API_KEY", ""),
            backend_url=os.environ.get("BACKEND_URL", cls.backend_url).rstrip("/"),
            model=os.environ.get("MODEL_ID", cls.model),
            max_inflight=int(os.environ.get("MAX_INFLIGHT", "4")),
            requests_per_minute=int(os.environ.get("REQUESTS_PER_MINUTE", "60")),
            request_timeout=float(os.environ.get("REQUEST_TIMEOUT_SECONDS", "120")),
            max_body_bytes=int(os.environ.get("MAX_BODY_BYTES", "65536")),
            max_output_tokens=int(os.environ.get("MAX_OUTPUT_TOKENS", "512")),
        )
