from __future__ import annotations

import json
import re
from typing import Iterator

import httpx

from gotg.model.types import CompletionRound
from gotg.model.helpers import _check_response, post_with_retry, stream_with_retry


# ---------------------------------------------------------------------------
# Private helpers — DRY blocks shared across the 4 public functions
# ---------------------------------------------------------------------------

_TEXT_TOOL_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n\s*```", re.DOTALL)


def _rescue_text_tool_calls(
    content: str, tools: list[dict] | None,
) -> tuple[str, list[dict]]:
    """Rescue tool calls from models that emit them as text.

    Some models (e.g. ollama/qwen) return tool calls as JSON in code fences
    instead of using the structured tool calling API.  Detects this pattern
    and converts to proper tool call dicts.

    Returns (cleaned_content, extracted_tool_calls).
    Only call this when the API returned no tool_calls.
    """
    if not tools or not content:
        return content, []

    tool_names = {t["name"] for t in tools}
    extracted: list[dict] = []
    spans_to_remove: list[tuple[int, int]] = []

    for m in _TEXT_TOOL_RE.finditer(content):
        try:
            obj = json.loads(m.group(1).strip())
        except (json.JSONDecodeError, ValueError):
            continue
        name = (obj.get("name") or "").strip()
        if name not in tool_names:
            continue
        args = obj.get("arguments") or obj.get("input") or {}
        extracted.append({
            "name": name,
            "input": args,
            "id": f"text-tc-{len(extracted)}",
        })
        spans_to_remove.append((m.start(), m.end()))

    if not extracted:
        return content, []

    # Remove matched code blocks (reverse order to preserve offsets)
    cleaned = content
    for start, end in reversed(spans_to_remove):
        cleaned = cleaned[:start] + cleaned[end:]
    return cleaned.strip(), extracted

def _build_headers(api_key: str | None) -> dict:
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


def _wrap_tools(tools: list[dict]) -> list[dict]:
    """Convert tool schemas to OpenAI function-call format."""
    return [
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


def _extract_tool_calls(message: dict) -> list[dict]:
    """Normalize tool calls from an OpenAI message.

    json.loads exceptions propagate unchanged — no silent fallback.
    """
    return [
        {
            "name": tc["function"]["name"],
            "input": json.loads(tc["function"]["arguments"]),
            "id": tc["id"],
        }
        for tc in message.get("tool_calls") or []
    ]


# ---------------------------------------------------------------------------
# Public provider functions
# ---------------------------------------------------------------------------

def _openai_completion(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
) -> str | dict:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = _build_headers(api_key)

    body = {"model": model, "messages": messages}
    if tools:
        body["tools"] = _wrap_tools(tools)

    resp = post_with_retry(url, json=body, headers=headers, timeout=600.0)
    _check_response(resp)
    data = resp.json()
    message = data["choices"][0]["message"]

    if tools:
        content = message.get("content") or ""
        tool_calls = _extract_tool_calls(message)
        if not tool_calls:
            content, tool_calls = _rescue_text_tool_calls(content, tools)
        return {"content": content, "tool_calls": tool_calls}

    return message["content"]


def _openai_agentic(
    base_url, model, messages, api_key, tools, tool_executor, max_rounds,
):
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = _build_headers(api_key)
    openai_tools = _wrap_tools(tools or [])

    chat_messages = list(messages)
    operations = []
    last_text = ""

    for _ in range(max_rounds):
        body = {"model": model, "messages": chat_messages}
        if openai_tools:
            body["tools"] = openai_tools

        resp = post_with_retry(url, json=body, headers=headers, timeout=600.0)
        _check_response(resp)
        data = resp.json()
        message = data["choices"][0]["message"]

        content = message.get("content") or ""
        raw_tool_calls = message.get("tool_calls") or []

        if not raw_tool_calls and openai_tools:
            content, rescued = _rescue_text_tool_calls(content, tools)
            if rescued:
                raw_tool_calls = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["input"]),
                        },
                    }
                    for tc in rescued
                ]
                message["content"] = content or None
                message["tool_calls"] = raw_tool_calls

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


def _openai_raw(
    base_url: str,
    model: str,
    messages: list[dict],
    api_key: str | None = None,
    tools: list[dict] | None = None,
    max_tokens: int = 16384,
) -> CompletionRound:
    url = f"{base_url.rstrip('/')}/v1/chat/completions"
    headers = _build_headers(api_key)

    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens}
    if tools:
        body["tools"] = _wrap_tools(tools)

    resp = post_with_retry(url, json=body, headers=headers, timeout=600.0)
    _check_response(resp)
    data = resp.json()
    message = data["choices"][0]["message"]

    content = message.get("content") or ""
    tool_calls = _extract_tool_calls(message)
    if tools and not tool_calls:
        content, tool_calls = _rescue_text_tool_calls(content, tools)

    return CompletionRound(
        content=content,
        tool_calls=tool_calls,
        _provider="openai",
        _raw={"message": message},
    )


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
    headers = _build_headers(api_key)

    body: dict = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": True}
    if tools:
        body["tools"] = _wrap_tools(tools)

    text_parts: list[str] = []
    # Accumulate tool calls: {index: {"id", "name", "args_parts"}}
    _pending_tools: dict[int, dict] = {}

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

    # Rescue tool calls from text if the API returned none
    full_text = "".join(text_parts)
    if tools and not tool_calls:
        full_text, tool_calls = _rescue_text_tool_calls(full_text, tools)

    # Build a synthetic message for continuation
    message: dict = {"role": "assistant", "content": full_text or None}
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
        content=full_text,
        tool_calls=tool_calls,
        _provider="openai",
        _raw={"message": message},
    )
    return rnd
