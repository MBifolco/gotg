import json
import sys
from dataclasses import dataclass, field

import httpx


@dataclass
class CompletionRound:
    """Result of a single LLM round that may contain tool calls."""
    content: str
    tool_calls: list[dict]    # [{"name", "input", "id"}]
    _provider: str
    _raw: dict                # Provider-specific raw response data

    def build_continuation(self, tool_results: list[dict]) -> list[dict]:
        """Build messages to append for the next LLM round.

        Args: tool_results = [{"id": str, "result": str}, ...]
        Returns: list of message dicts (provider-formatted)
        """
        if self._provider == "anthropic":
            return [
                {"role": "assistant", "content": self._raw["content_blocks"]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": r["result"]}
                    for r in tool_results
                ]},
            ]
        else:
            msgs = [self._raw["message"]]
            for r in tool_results:
                msgs.append({"role": "tool", "tool_call_id": r["id"], "content": r["result"]})
            return msgs


def _check_response(resp: httpx.Response) -> None:
    """Raise SystemExit with the API error message on failure."""
    if resp.status_code >= 400:
        try:
            error_data = resp.json()
            # Anthropic: {"error": {"message": "..."}}
            # OpenAI: {"error": {"message": "..."}}
            error_msg = error_data.get("error", {}).get("message", resp.text)
        except Exception:
            error_msg = resp.text
        raise SystemExit(f"API error ({resp.status_code}): {error_msg}")


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
    _check_response(resp)
    data = resp.json()
    message = data["choices"][0]["message"]

    if tools:
        content = message.get("content") or ""
        tool_calls = [
            {
                "name": tc["function"]["name"],
                "input": json.loads(tc["function"]["arguments"]),
                "id": tc["id"],
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
        elif msg.get("content"):
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
        if isinstance(msg["content"], str) and msg["content"]:
            msg["content"] = [
                {
                    "type": "text",
                    "text": msg["content"],
                    "cache_control": {"type": "ephemeral"},
                }
            ]

    resp = httpx.post(url, json=body, headers=headers, timeout=600.0)
    _check_response(resp)
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
                tool_calls.append({"name": block["name"], "input": block["input"], "id": block["id"]})
        return {"content": "\n\n".join(text_parts), "tool_calls": tool_calls}

    return data["content"][0]["text"]


def agentic_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
    tools: list[dict] | None = None,
    tool_executor: callable = None,
    max_rounds: int = 10,
) -> dict:
    """Chat completion with automatic tool execution loop.

    Returns: {"content": str, "operations": [{"name", "input", "result"}, ...]}
    """
    if provider == "anthropic":
        return _anthropic_agentic(
            base_url, model, messages, api_key, tools, tool_executor, max_rounds
        )
    return _openai_agentic(
        base_url, model, messages, api_key, tools, tool_executor, max_rounds
    )


def _anthropic_agentic(
    base_url, model, messages, api_key, tools, tool_executor, max_rounds,
):
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": api_key or "",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # Extract system from messages (same as _anthropic_completion)
    system = None
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"]
        elif msg.get("content"):
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

    # Apply cache control to second-to-last message
    if len(chat_messages) >= 2:
        msg = chat_messages[-2]
        if isinstance(msg["content"], str) and msg["content"]:
            msg["content"] = [
                {
                    "type": "text",
                    "text": msg["content"],
                    "cache_control": {"type": "ephemeral"},
                }
            ]

    system_block = None
    if system:
        system_block = [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    operations = []
    last_text = ""

    for _ in range(max_rounds):
        body = {
            "model": model,
            "max_tokens": 4096,
            "messages": chat_messages,
        }
        if system_block:
            body["system"] = system_block
        if tools:
            body["tools"] = tools

        resp = httpx.post(url, json=body, headers=headers, timeout=600.0)
        _check_response(resp)
        data = resp.json()

        # Log cache usage
        usage = data.get("usage", {})
        cache_created = usage.get("cache_creation_input_tokens", 0)
        cache_read = usage.get("cache_read_input_tokens", 0)
        if cache_created or cache_read:
            print(
                f"  [cache] created={cache_created} read={cache_read}",
                file=sys.stderr,
            )

        # Parse response content blocks
        content_blocks = data.get("content", [])
        text_parts = []
        tool_uses = []
        for block in content_blocks:
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_uses.append(block)

        text = "\n\n".join(text_parts)

        if not tool_uses:
            return {"content": text, "operations": operations}

        last_text = text

        # Execute tools and collect results
        tool_results = []
        for tu in tool_uses:
            result = tool_executor(tu["name"], tu["input"])
            operations.append({
                "name": tu["name"],
                "input": tu["input"],
                "result": result,
            })
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": result,
            })

        # Append assistant + tool results to conversation
        chat_messages.append({"role": "assistant", "content": content_blocks})
        chat_messages.append({"role": "user", "content": tool_results})

    # Max rounds reached
    return {"content": last_text, "operations": operations}


def _openai_agentic(
    base_url, model, messages, api_key, tools, tool_executor, max_rounds,
):
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in (tools or [])
    ]

    chat_messages = list(messages)
    operations = []
    last_text = ""

    for _ in range(max_rounds):
        body = {"model": model, "messages": chat_messages}
        if openai_tools:
            body["tools"] = openai_tools

        resp = httpx.post(url, json=body, headers=headers, timeout=600.0)
        _check_response(resp)
        data = resp.json()
        message = data["choices"][0]["message"]

        content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls") or []

        if not raw_tool_calls:
            return {"content": content, "operations": operations}

        last_text = content

        # Execute tools and collect results
        tool_messages = []
        for tc in raw_tool_calls:
            name = tc["function"]["name"]
            inp = json.loads(tc["function"]["arguments"])
            result = tool_executor(name, inp)
            operations.append({"name": name, "input": inp, "result": result})
            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result,
            })

        # Append assistant message (with tool_calls) + tool result messages
        chat_messages.append(message)
        chat_messages.extend(tool_messages)

    # Max rounds reached — _openai_agentic
    return {"content": last_text, "operations": operations}


# ── Raw completion (single-round, engine-driven tool loop) ──────


def raw_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
    tools: list[dict] | None = None,
) -> CompletionRound:
    """Single-round completion returning CompletionRound for engine-driven tool loops.

    Used by implementation executor. chat_completion stays unchanged.
    """
    if provider == "anthropic":
        return _anthropic_raw(base_url, model, messages, api_key, tools)
    return _openai_raw(base_url, model, messages, api_key, tools)


def _anthropic_raw(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
) -> CompletionRound:
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": api_key or "",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # Extract system from messages
    system = None
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"]
        elif msg.get("content"):
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

    # Higher limit than discussion phases — implementation agents write large files
    body = {
        "model": model,
        "max_tokens": 16384,
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

    # Prompt caching
    if len(chat_messages) >= 2:
        msg = chat_messages[-2]
        if isinstance(msg["content"], str) and msg["content"]:
            msg["content"] = [
                {
                    "type": "text",
                    "text": msg["content"],
                    "cache_control": {"type": "ephemeral"},
                }
            ]

    resp = httpx.post(url, json=body, headers=headers, timeout=600.0)
    _check_response(resp)
    data = resp.json()

    # Log cache usage
    usage = data.get("usage", {})
    cache_created = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    if cache_created or cache_read:
        print(
            f"  [cache] created={cache_created} read={cache_read}",
            file=sys.stderr,
        )

    content_blocks = data.get("content", [])
    stop_reason = data.get("stop_reason", "")
    text_parts = []
    tool_calls = []

    # If stopped due to max_tokens, tool_use blocks may be truncated —
    # discard them to avoid executing malformed tool calls
    include_tools = stop_reason != "max_tokens"

    for block in content_blocks:
        if block["type"] == "text":
            text_parts.append(block["text"])
        elif block["type"] == "tool_use" and include_tools:
            tool_calls.append({"name": block["name"], "input": block["input"], "id": block["id"]})

    if stop_reason == "max_tokens" and not text_parts:
        text_parts.append(
            "[Output was truncated due to length. "
            "Try breaking large file writes into smaller pieces.]"
        )

    return CompletionRound(
        content="\n\n".join(text_parts),
        tool_calls=tool_calls,
        _provider="anthropic",
        _raw={"content_blocks": content_blocks},
    )


def _openai_raw(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
) -> CompletionRound:
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
    _check_response(resp)
    data = resp.json()
    message = data["choices"][0]["message"]

    content = message.get("content") or ""
    tool_calls = [
        {
            "name": tc["function"]["name"],
            "input": json.loads(tc["function"]["arguments"]),
            "id": tc["id"],
        }
        for tc in message.get("tool_calls") or []
    ]

    return CompletionRound(
        content=content,
        tool_calls=tool_calls,
        _provider="openai",
        _raw={"message": message},
    )
