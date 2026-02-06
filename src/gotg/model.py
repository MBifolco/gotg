import json
import sys

import httpx


def chat_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
    tools: list[dict] | None = None,
) -> str | dict:
    if provider == "anthropic":
        return _anthropic_completion(base_url, model, messages, api_key, tools)
    return _openai_completion(base_url, model, messages, api_key, tools)


def _openai_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
) -> str | dict:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body = {"model": model, "messages": messages}
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    resp = httpx.post(url, json=body, headers=headers, timeout=600.0)
    resp.raise_for_status()
    data = resp.json()
    message = data["choices"][0]["message"]

    if tools:
        content = message.get("content") or ""
        tool_calls = [
            {
                "name": tc["function"]["name"],
                "input": json.loads(tc["function"]["arguments"]),
            }
            for tc in message.get("tool_calls") or []
        ]
        return {"content": content, "tool_calls": tool_calls}

    return message["content"]


def _anthropic_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
) -> str | dict:
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
        body["system"] = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]
    if tools:
        body["tools"] = tools

    # Prompt caching: mark second-to-last message for cache breakpoint
    if len(chat_messages) >= 2:
        msg = chat_messages[-2]
        if isinstance(msg["content"], str):
            msg["content"] = [
                {
                    "type": "text",
                    "text": msg["content"],
                    "cache_control": {"type": "ephemeral"},
                }
            ]

    resp = httpx.post(url, json=body, headers=headers, timeout=600.0)
    resp.raise_for_status()
    data = resp.json()

    # Log cache usage if present (for observability)
    usage = data.get("usage", {})
    cache_created = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    if cache_created or cache_read:
        print(
            f"  [cache] created={cache_created} read={cache_read}",
            file=sys.stderr,
        )

    if tools:
        text_parts = []
        tool_calls = []
        for block in data.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append({"name": block["name"], "input": block["input"]})
        return {"content": "\n\n".join(text_parts), "tool_calls": tool_calls}

    return data["content"][0]["text"]
