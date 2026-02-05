import httpx


def chat_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
) -> str:
    url = f"{base_url}/v1/chat/completions"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = httpx.post(
        url,
        json={"model": model, "messages": messages},
        headers=headers,
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
