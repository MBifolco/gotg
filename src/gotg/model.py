from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Iterator

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


@dataclass
class StreamingResult:
    """Wraps a generator that yields text deltas and captures final CompletionRound."""
    _gen: Iterator[str]
    round: CompletionRound | None = None

    def __iter__(self):
        return self

    def __next__(self):
        try:
            return next(self._gen)
        except StopIteration:
            raise


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
    max_tokens: int = 16384,
) -> CompletionRound:
    """Single-round completion returning CompletionRound for engine-driven tool loops.

    Used by implementation executor. chat_completion stays unchanged.
    """
    if provider == "anthropic":
        return _anthropic_raw(base_url, model, messages, api_key, tools, max_tokens=max_tokens)
    return _openai_raw(base_url, model, messages, api_key, tools, max_tokens=max_tokens)


def _anthropic_raw(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
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

    body = {
        "model": model,
        "max_tokens": max_tokens,
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
    max_tokens: int = 16384,
) -> CompletionRound:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
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


# ── Streaming completion (single-round, yields text deltas) ─────


def raw_completion_stream(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    provider: str = "ollama",
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
) -> StreamingResult:
    """Single-round streaming completion returning StreamingResult.

    Yields text deltas as they arrive. The final CompletionRound is
    available on result.round after iteration completes.
    """
    def _provider_stream() -> Iterator[str]:
        if provider == "anthropic":
            return _anthropic_raw_stream(base_url, model, messages, api_key, tools, max_tokens=max_tokens)
        return _openai_raw_stream(base_url, model, messages, api_key, tools, max_tokens=max_tokens)

    result = StreamingResult(_gen=iter(()))

    # Wrap the provider stream so we can capture CompletionRound and provide
    # fallback to non-streaming ONLY before any delta was emitted.
    def _capturing_with_fallback():
        emitted = False
        try:
            stream = _provider_stream()
            while True:
                chunk = next(stream)
                emitted = True
                yield chunk
        except StopIteration as done:
            result.round = done.value
            return
        except (httpx.StreamError, httpx.TransportError):
            if emitted:
                raise
            fallback_round = raw_completion(
                base_url=base_url,
                model=model,
                messages=messages,
                api_key=api_key,
                provider=provider,
                tools=tools,
                max_tokens=max_tokens,
            )
            result.round = fallback_round
            if fallback_round.content:
                yield fallback_round.content
            return

    result._gen = _capturing_with_fallback()
    return result


def _anthropic_raw_stream(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
) -> Iterator[str]:
    """Anthropic streaming — yields text deltas, returns CompletionRound."""
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": api_key or "",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # Extract system from messages (same as _anthropic_raw)
    system = None
    chat_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system = msg["content"]
        elif msg.get("content"):
            chat_messages.append({"role": msg["role"], "content": msg["content"]})

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": chat_messages,
        "stream": True,
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

    text_parts = []
    tool_calls = []
    content_blocks_by_index: dict[int, dict] = {}
    # Track tool_use blocks being accumulated: {index: {"id", "name", "json_parts"}}
    _pending_tools: dict[int, dict] = {}
    _current_block_index = -1
    stop_reason = ""

    with httpx.stream("POST", url, json=body, headers=headers, timeout=600.0) as resp:
        if resp.status_code >= 400:
            resp.read()
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", resp.text)
            except Exception:
                error_msg = resp.text
            raise SystemExit(f"API error ({resp.status_code}): {error_msg}")

        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if not data_str.strip():
                continue
            try:
                event = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")

            if event_type == "content_block_start":
                _current_block_index = event.get("index", _current_block_index + 1)
                block = event.get("content_block", {})
                if block.get("type") == "text":
                    content_blocks_by_index[_current_block_index] = {
                        "type": "text",
                        "text": block.get("text", ""),
                    }
                elif block.get("type") == "tool_use":
                    content_blocks_by_index[_current_block_index] = {
                        "type": "tool_use",
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "input": {},
                    }
                    _pending_tools[_current_block_index] = {
                        "id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "json_parts": [],
                    }

            elif event_type == "content_block_delta":
                idx = event.get("index", _current_block_index)
                delta = event.get("delta", {})
                delta_type = delta.get("type", "")

                if delta_type == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        text_parts.append(text)
                        if idx not in content_blocks_by_index:
                            content_blocks_by_index[idx] = {"type": "text", "text": ""}
                        if content_blocks_by_index[idx].get("type") == "text":
                            content_blocks_by_index[idx]["text"] += text
                        yield text

                elif delta_type == "input_json_delta":
                    partial = delta.get("partial_json", "")
                    if idx in _pending_tools:
                        _pending_tools[idx]["json_parts"].append(partial)

            elif event_type == "content_block_stop":
                idx = event.get("index", _current_block_index)
                if idx in _pending_tools:
                    pt = _pending_tools.pop(idx)
                    json_str = "".join(pt["json_parts"])
                    try:
                        tool_input = json.loads(json_str) if json_str else {}
                    except json.JSONDecodeError:
                        tool_input = {}
                    if idx in content_blocks_by_index and content_blocks_by_index[idx].get("type") == "tool_use":
                        content_blocks_by_index[idx]["input"] = tool_input
                    tool_calls.append({
                        "name": pt["name"],
                        "input": tool_input,
                        "id": pt["id"],
                    })

            elif event_type == "message_delta":
                delta = event.get("delta", {})
                stop_reason = delta.get("stop_reason", stop_reason)
                usage = event.get("usage", {})
                cache_created = usage.get("cache_creation_input_tokens", 0)
                cache_read = usage.get("cache_read_input_tokens", 0)
                if cache_created or cache_read:
                    print(
                        f"  [cache] created={cache_created} read={cache_read}",
                        file=sys.stderr,
                    )

    # Truncation guard: discard tool calls on max_tokens
    if stop_reason == "max_tokens":
        tool_calls = []
        if not text_parts:
            text_parts.append(
                "[Output was truncated due to length. "
                "Try breaking large file writes into smaller pieces.]"
            )

    rnd = CompletionRound(
        content="".join(text_parts),
        tool_calls=tool_calls,
        _provider="anthropic",
        _raw={"content_blocks": [
            content_blocks_by_index[i]
            for i in sorted(content_blocks_by_index.keys())
        ]},
    )
    return rnd


def _openai_raw_stream(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
) -> Iterator[str]:
    """OpenAI/Ollama streaming — yields text deltas, returns CompletionRound."""
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": True}
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

    text_parts: list[str] = []
    # Accumulate tool calls: {index: {"id", "name", "args_parts"}}
    _pending_tools: dict[int, dict] = {}

    with httpx.stream("POST", url, json=body, headers=headers, timeout=600.0) as resp:
        if resp.status_code >= 400:
            resp.read()
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", resp.text)
            except Exception:
                error_msg = resp.text
            raise SystemExit(f"API error ({resp.status_code}): {error_msg}")

        for line in resp.iter_lines():
            if not line.startswith("data: "):
                continue
            data_str = line[6:].strip()
            if data_str == "[DONE]":
                break
            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            choices = chunk.get("choices", [])
            if not choices:
                continue
            delta = choices[0].get("delta", {})

            # Text content
            content = delta.get("content")
            if content:
                text_parts.append(content)
                yield content

            # Tool call deltas
            tc_deltas = delta.get("tool_calls", [])
            for tc_delta in tc_deltas:
                idx = tc_delta.get("index", 0)
                if idx not in _pending_tools:
                    _pending_tools[idx] = {
                        "id": tc_delta.get("id", ""),
                        "name": tc_delta.get("function", {}).get("name", ""),
                        "args_parts": [],
                    }
                else:
                    # Update id/name if provided in later deltas
                    if tc_delta.get("id"):
                        _pending_tools[idx]["id"] = tc_delta["id"]
                    fn_name = tc_delta.get("function", {}).get("name")
                    if fn_name:
                        _pending_tools[idx]["name"] = fn_name

                args_chunk = tc_delta.get("function", {}).get("arguments", "")
                if args_chunk:
                    _pending_tools[idx]["args_parts"].append(args_chunk)

    # Build tool calls from accumulated data
    tool_calls = []
    for idx in sorted(_pending_tools.keys()):
        pt = _pending_tools[idx]
        args_str = "".join(pt["args_parts"])
        try:
            tool_input = json.loads(args_str) if args_str else {}
        except json.JSONDecodeError:
            tool_input = {}
        tool_calls.append({
            "name": pt["name"],
            "input": tool_input,
            "id": pt["id"],
        })

    # Build a synthetic message for continuation
    message: dict = {"role": "assistant", "content": "".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc["input"]),
                },
            }
            for tc in tool_calls
        ]

    rnd = CompletionRound(
        content="".join(text_parts),
        tool_calls=tool_calls,
        _provider="openai",
        _raw={"message": message},
    )
    return rnd
