import os

import httpx

base = os.environ.get("GATEWAY_URL", "http://127.0.0.1:8000")
key = os.environ["GATEWAY_API_KEY"]
with httpx.Client(base_url=base, timeout=120, trust_env=False) as client:
    client.get("/readyz").raise_for_status()
    response = client.post(
        "/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": os.environ["MODEL_ID"],
            "messages": [{"role": "user", "content": "Explain GPU inference in one sentence."}],
            "max_tokens": 64,
            "temperature": 0,
        },
    )
    response.raise_for_status()
    print(response.json()["choices"][0]["message"]["content"])
    print("usage:", response.json().get("usage"))
