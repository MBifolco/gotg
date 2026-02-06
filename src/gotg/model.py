import httpx


def chat_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
) -> str:
    if provider == "anthropic":
        return _anthropic_completion(base_url, model, messages, api_key)
    return _openai_completion(base_url, model, messages, api_key)


def _openai_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
) -> str:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    resp = httpx.post(
        url,
        json={"model": model, "messages": messages},
        headers=headers,
        timeout=600.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _anthropic_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
) -> str:
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": api_key or "",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # Anthropic: system is a top-level field, not a message
    system = None
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"]
        else:
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

    body = {
        "model": model,
        "max_tokens": 4096,
        "messages": chat_messages,
    }
    if system:
        body["system"] = system

    resp = httpx.post(url, json=body, headers=headers, timeout=600.0)
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]
