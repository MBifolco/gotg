from __future__ import annotations

import json
import sys
from typing import Iterator

import httpx

from gotg.model.types import CompletionRound
from gotg.model.helpers import _check_response, post_with_retry, stream_with_retry


# ---------------------------------------------------------------------------
# Private helpers — DRY blocks shared across the 4 public functions
# ---------------------------------------------------------------------------

def _build_headers(api_key: str | None) -> dict:
    return {
        "x-api-key": api_key or "",
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


def _extract_system_and_messages(
    messages: list[dict],
) -> tuple[list[str], list[dict]]:
    """Split system messages from chat messages.

    Skips messages with empty/missing content (preserves existing guard).
    """
    system_parts: list[str] = []
    chat_messages: list[dict] = []
    for msg in messages:
        if msg["role"] == "system":
            system_parts.append(msg["content"])
        elif msg.get("content"):
            chat_messages.append({"role": msg["role"], "content": msg["content"]})
    return system_parts, chat_messages


def _build_system_block(system_parts: list[str]) -> list[dict] | None:
    """Build Anthropic system parameter with cache control on first block."""
    if not system_parts:
        return None
    return [
        {
            "type": "text",
            "text": system_parts[0],
            "cache_control": {"type": "ephemeral"},
        }
    ] + [
        {"type": "text", "text": part}
        for part in system_parts[1:]
    ]


def _apply_message_cache_control(chat_messages: list[dict]) -> None:
    """Mark second-to-last message for prompt caching (mutates in-place)."""
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


def _log_cache_usage(usage: dict) -> None:
    """Log cache stats to stderr when non-zero."""
    cache_created = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    if cache_created or cache_read:
        print(
            f"  [cache] created={cache_created} read={cache_read}",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Public provider functions
# ---------------------------------------------------------------------------

def _anthropic_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
) -> str | dict:
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = _build_headers(api_key)
    system_parts, chat_messages = _extract_system_and_messages(messages)

    body = {
        "model": model,
        "max_tokens": 4096,
        "messages": chat_messages,
    }
    system_block = _build_system_block(system_parts)
    if system_block:
        body["system"] = system_block
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice

    _apply_message_cache_control(chat_messages)

    resp = post_with_retry(url, json=body, headers=headers, timeout=600.0)
    _check_response(resp)
    data = resp.json()

    _log_cache_usage(data.get("usage", {}))

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


def _anthropic_agentic(
    base_url, model, messages, api_key, tools, tool_executor, max_rounds,
):
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = _build_headers(api_key)
    system_parts, chat_messages = _extract_system_and_messages(messages)

    _apply_message_cache_control(chat_messages)

    system_block = _build_system_block(system_parts)

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

        resp = post_with_retry(url, json=body, headers=headers, timeout=600.0)
        _check_response(resp)
        data = resp.json()

        _log_cache_usage(data.get("usage", {}))

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


def _anthropic_raw(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
) -> CompletionRound:
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = _build_headers(api_key)
    system_parts, chat_messages = _extract_system_and_messages(messages)

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": chat_messages,
    }
    system_block = _build_system_block(system_parts)
    if system_block:
        body["system"] = system_block
    if tools:
        body["tools"] = tools

    _apply_message_cache_control(chat_messages)

    resp = post_with_retry(url, json=body, headers=headers, timeout=600.0)
    _check_response(resp)
    data = resp.json()

    _log_cache_usage(data.get("usage", {}))

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


def _anthropic_raw_stream(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
    tool_choice: dict | None = None,
) -> Iterator[str]:
    """Anthropic streaming — yields text deltas, returns CompletionRound."""
    url = f"{base_url.rstrip('/')}/v1/messages"
    headers = _build_headers(api_key)
    system_parts, chat_messages = _extract_system_and_messages(messages)

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": chat_messages,
        "stream": True,
    }
    system_block = _build_system_block(system_parts)
    if system_block:
        body["system"] = system_block
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice

    _apply_message_cache_control(chat_messages)

    text_parts = []
    tool_calls = []
    content_blocks_by_index: dict[int, dict] = {}
    # Track tool_use blocks being accumulated: {index: {"id", "name", "json_parts"}}
    _pending_tools: dict[int, dict] = {}
    _current_block_index = -1
    stop_reason = ""

    with stream_with_retry(url, json=body, headers=headers, timeout=600.0) as resp:
        if resp.status_code >= 400:
            resp.read()
            try:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", resp.text)
            except Exception:
                error_msg = resp.text
            from gotg.errors import ModelError
            raise ModelError(f"API error ({resp.status_code}): {error_msg}")

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
                _log_cache_usage(event.get("usage", {}))

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
