import json


class StreamMonitor:
    """Inspect SSE without equating chunks or words to model tokens."""

    def __init__(self):
        self.buffer = b""
        self.has_content = False
        self.done = False
        self.failed = False
        self.completion_tokens = 0

    def feed(self, chunk: bytes):
        self.buffer += chunk
        if len(self.buffer) > 1024 * 1024:
            raise ValueError("Upstream SSE line exceeded limit")
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                self.done = True
                continue
            if not data:
                continue
            message = json.loads(data)
            if message.get("error"):
                self.failed = True
            usage = message.get("usage") or {}
            tokens = usage.get("completion_tokens")
            if isinstance(tokens, int) and tokens >= 0:
                self.completion_tokens = tokens
            for choice in message.get("choices", []):
                delta = choice.get("delta") or {}
                if delta.get("content") or delta.get("reasoning_content"):
                    self.has_content = True
