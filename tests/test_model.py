import json
from unittest.mock import patch, MagicMock

import pytest

from gotg.model import chat_completion


def _mock_response(content: str):
    """Create a mock httpx response with the given content."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


@patch("gotg.model.httpx.post")
def test_chat_completion_returns_content(mock_post):
    mock_post.return_value = _mock_response("Hello from the model")
    result = chat_completion(
        base_url="http://localhost:11434",
        model="qwen2.5-coder:7b",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result == "Hello from the model"


@patch("gotg.model.httpx.post")
def test_chat_completion_sends_correct_url(mock_post):
    mock_post.return_value = _mock_response("ok")
    chat_completion(
        base_url="http://localhost:11434",
        model="test-model",
        messages=[{"role": "user", "content": "hi"}],
    )
    call_args = mock_post.call_args
    assert call_args[0][0] == "http://localhost:11434/v1/chat/completions"


@patch("gotg.model.httpx.post")
def test_chat_completion_sends_model_and_messages(mock_post):
    mock_post.return_value = _mock_response("ok")
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    chat_completion(
        base_url="http://localhost:11434",
        model="test-model",
        messages=messages,
    )
    body = mock_post.call_args[1]["json"]
    assert body["model"] == "test-model"
    assert body["messages"] == messages


@patch("gotg.model.httpx.post")
def test_chat_completion_no_auth_header_by_default(mock_post):
    mock_post.return_value = _mock_response("ok")
    chat_completion(
        base_url="http://localhost:11434",
        model="m",
        messages=[],
    )
    headers = mock_post.call_args[1].get("headers", {})
    assert "Authorization" not in headers


@patch("gotg.model.httpx.post")
def test_chat_completion_sends_auth_header_when_key_provided(mock_post):
    mock_post.return_value = _mock_response("ok")
    chat_completion(
        base_url="http://api.example.com",
        model="m",
        messages=[],
        api_key="sk-test-123",
    )
    headers = mock_post.call_args[1]["headers"]
    assert headers["Authorization"] == "Bearer sk-test-123"


# --- API error responses ---

@patch("gotg.model.httpx.post")
def test_chat_completion_raises_on_http_error(mock_post):
    """HTTP errors (400, 500, etc.) should exit with the API error message."""
    resp = MagicMock()
    resp.status_code = 500
    resp.json.return_value = {"error": {"message": "Internal server error"}}
    mock_post.return_value = resp
    with pytest.raises(SystemExit, match="API error.*500.*Internal server error"):
        chat_completion("http://localhost:11434", "m", [])


@patch("gotg.model.httpx.post")
def test_chat_completion_raises_on_timeout(mock_post):
    """Timeout should propagate as an exception."""
    import httpx
    mock_post.side_effect = httpx.TimeoutException("timed out")
    with pytest.raises(httpx.TimeoutException):
        chat_completion("http://localhost:11434", "m", [])


@patch("gotg.model.httpx.post")
def test_chat_completion_raises_on_connection_error(mock_post):
    """Connection refused (Ollama not running) should propagate."""
    import httpx
    mock_post.side_effect = httpx.ConnectError("Connection refused")
    with pytest.raises(httpx.ConnectError):
        chat_completion("http://localhost:11434", "m", [])


@patch("gotg.model.httpx.post")
def test_chat_completion_raises_on_empty_choices(mock_post):
    """API returning empty choices array should raise IndexError."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": []}
    resp.raise_for_status = MagicMock()
    mock_post.return_value = resp
    with pytest.raises(IndexError):
        chat_completion("http://localhost:11434", "m", [])


@patch("gotg.model.httpx.post")
def test_chat_completion_raises_on_missing_choices_key(mock_post):
    """API returning unexpected JSON structure should raise KeyError."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"error": "something went wrong"}
    resp.raise_for_status = MagicMock()
    mock_post.return_value = resp
    with pytest.raises(KeyError):
        chat_completion("http://localhost:11434", "m", [])


@patch("gotg.model.httpx.post")
def test_chat_completion_base_url_trailing_slash(mock_post):
    """Trailing slash on base_url shouldn't double up."""
    mock_post.return_value = _mock_response("ok")
    chat_completion("http://localhost:11434/", "m", [])
    url = mock_post.call_args[0][0]
    assert "//" not in url.replace("http://", "")


# --- Anthropic provider ---

def _mock_anthropic_response(text: str):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [{"type": "text", "text": text}]
    }
    resp.raise_for_status = MagicMock()
    return resp


@patch("gotg.model.httpx.post")
def test_anthropic_returns_content(mock_post):
    mock_post.return_value = _mock_anthropic_response("Hello from Claude")
    result = chat_completion(
        base_url="https://api.anthropic.com",
        model="claude-sonnet-4-5-20250929",
        messages=[
            {"role": "system", "content": "You are an engineer."},
            {"role": "user", "content": "hi"},
        ],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    assert result == "Hello from Claude"


@patch("gotg.model.httpx.post")
def test_anthropic_sends_correct_url(mock_post):
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    url = mock_post.call_args[0][0]
    assert url == "https://api.anthropic.com/v1/messages"


@patch("gotg.model.httpx.post")
def test_anthropic_extracts_system_from_messages(mock_post):
    """System message should be extracted to top-level 'system' field."""
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
            {"role": "user", "content": "bye"},
        ],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    body = mock_post.call_args[1]["json"]
    # System is now a list with cache_control
    assert isinstance(body["system"], list)
    assert body["system"][0]["text"] == "Be helpful."
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    # System message should NOT be in the messages array
    assert all(m["role"] != "system" for m in body["messages"])
    assert len(body["messages"]) == 3


@patch("gotg.model.httpx.post")
def test_anthropic_sends_api_key_header(mock_post):
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-ant-test-key",
        provider="anthropic",
    )
    headers = mock_post.call_args[1]["headers"]
    assert headers["x-api-key"] == "sk-ant-test-key"
    assert headers["anthropic-version"] == "2023-06-01"


@patch("gotg.model.httpx.post")
def test_anthropic_sets_max_tokens(mock_post):
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    body = mock_post.call_args[1]["json"]
    assert body["max_tokens"] == 4096


# --- Tools parameter (OpenAI) ---

SAMPLE_TOOLS = [
    {
        "name": "my_tool",
        "description": "A test tool",
        "input_schema": {
            "type": "object",
            "properties": {"arg": {"type": "string"}},
            "required": ["arg"],
        },
    }
]


@patch("gotg.model.httpx.post")
def test_openai_passes_tools_in_request(mock_post):
    """Tools should be wrapped in OpenAI function format in the request body."""
    mock_post.return_value = _mock_response("ok")
    chat_completion(
        base_url="http://localhost:11434",
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=SAMPLE_TOOLS,
    )
    body = mock_post.call_args[1]["json"]
    assert "tools" in body
    assert body["tools"][0]["type"] == "function"
    assert body["tools"][0]["function"]["name"] == "my_tool"
    assert body["tools"][0]["function"]["parameters"] == SAMPLE_TOOLS[0]["input_schema"]


@patch("gotg.model.httpx.post")
def test_openai_returns_dict_with_tool_calls(mock_post):
    """When tools are provided, response should be a dict with content and tool_calls."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{
            "message": {
                "content": "I'll call the tool.",
                "tool_calls": [{
                    "id": "call_123",
                    "function": {
                        "name": "my_tool",
                        "arguments": json.dumps({"arg": "value"}),
                    }
                }],
            }
        }]
    }
    resp.raise_for_status = MagicMock()
    mock_post.return_value = resp

    result = chat_completion(
        base_url="http://localhost:11434",
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=SAMPLE_TOOLS,
    )
    assert isinstance(result, dict)
    assert result["content"] == "I'll call the tool."
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "my_tool"
    assert result["tool_calls"][0]["input"] == {"arg": "value"}


# --- Tools parameter (Anthropic) ---

@patch("gotg.model.httpx.post")
def test_anthropic_passes_tools_in_request(mock_post):
    """Anthropic tools should be passed directly (our format matches)."""
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-ant-test",
        provider="anthropic",
        tools=SAMPLE_TOOLS,
    )
    body = mock_post.call_args[1]["json"]
    assert "tools" in body
    assert body["tools"] == SAMPLE_TOOLS


@patch("gotg.model.httpx.post")
def test_anthropic_returns_dict_with_tool_calls(mock_post):
    """When tools are provided, Anthropic response should be parsed into dict."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [
            {"type": "text", "text": "I'll signal completion."},
            {"type": "tool_use", "id": "tu_456", "name": "my_tool", "input": {"arg": "value"}},
        ]
    }
    resp.raise_for_status = MagicMock()
    mock_post.return_value = resp

    result = chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        api_key="sk-ant-test",
        provider="anthropic",
        tools=SAMPLE_TOOLS,
    )
    assert isinstance(result, dict)
    assert result["content"] == "I'll signal completion."
    assert len(result["tool_calls"]) == 1
    assert result["tool_calls"][0]["name"] == "my_tool"
    assert result["tool_calls"][0]["input"] == {"arg": "value"}


# --- Anthropic prompt caching ---

@patch("gotg.model.httpx.post")
def test_anthropic_system_cache_control(mock_post):
    """System prompt should be a list with cache_control marker."""
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "hi"},
        ],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    body = mock_post.call_args[1]["json"]
    assert isinstance(body["system"], list)
    assert len(body["system"]) == 1
    assert body["system"][0]["type"] == "text"
    assert body["system"][0]["text"] == "Be helpful."
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}


@patch("gotg.model.httpx.post")
def test_anthropic_second_to_last_message_cache_control(mock_post):
    """Second-to-last message should get cache_control marker."""
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    body = mock_post.call_args[1]["json"]
    # Second-to-last (assistant "reply") should have cache_control
    second_to_last = body["messages"][1]
    assert isinstance(second_to_last["content"], list)
    assert second_to_last["content"][0]["cache_control"] == {"type": "ephemeral"}
    # Last message should remain a plain string
    last = body["messages"][2]
    assert isinstance(last["content"], str)


@patch("gotg.model.httpx.post")
def test_anthropic_last_message_no_cache_control(mock_post):
    """Last message should NOT get cache_control."""
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "latest"},
        ],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    body = mock_post.call_args[1]["json"]
    last = body["messages"][-1]
    assert isinstance(last["content"], str)
    assert last["content"] == "latest"


@patch("gotg.model.httpx.post")
def test_anthropic_single_message_no_message_cache(mock_post):
    """With only one message, no message should get cache_control."""
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[
            {"role": "user", "content": "hi"},
        ],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    body = mock_post.call_args[1]["json"]
    assert len(body["messages"]) == 1
    assert isinstance(body["messages"][0]["content"], str)


@patch("gotg.model.httpx.post")
def test_anthropic_no_system_no_system_field(mock_post):
    """Without system message, body should not have 'system' field."""
    mock_post.return_value = _mock_anthropic_response("ok")
    chat_completion(
        base_url="https://api.anthropic.com",
        model="m",
        messages=[
            {"role": "user", "content": "hi"},
        ],
        api_key="sk-ant-test",
        provider="anthropic",
    )
    body = mock_post.call_args[1]["json"]
    assert "system" not in body


@patch("gotg.model.httpx.post")
def test_openai_no_cache_control(mock_post):
    """OpenAI path should never add cache_control markers."""
    mock_post.return_value = _mock_response("ok")
    chat_completion(
        base_url="http://localhost:11434",
        model="m",
        messages=[
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ],
    )
    body = mock_post.call_args[1]["json"]
    # System should be in messages, not extracted
    assert "system" not in body or body.get("system") is None
    # No message should have cache_control
    for msg in body["messages"]:
        assert isinstance(msg["content"], str)


# --- Tool call IDs ---

@patch("gotg.model.httpx.post")
def test_openai_tool_calls_include_id(mock_post):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{
            "message": {
                "content": "text",
                "tool_calls": [{
                    "id": "call_abc",
                    "function": {"name": "my_tool", "arguments": "{}"},
                }],
            }
        }]
    }
    resp.raise_for_status = MagicMock()
    mock_post.return_value = resp
    result = chat_completion("http://localhost", "m", [{"role": "user", "content": "hi"}], tools=SAMPLE_TOOLS)
    assert result["tool_calls"][0]["id"] == "call_abc"


@patch("gotg.model.httpx.post")
def test_anthropic_tool_calls_include_id(mock_post):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [
            {"type": "text", "text": "text"},
            {"type": "tool_use", "id": "tu_xyz", "name": "my_tool", "input": {}},
        ]
    }
    resp.raise_for_status = MagicMock()
    mock_post.return_value = resp
    result = chat_completion(
        "https://api.anthropic.com", "m",
        [{"role": "user", "content": "hi"}],
        api_key="sk", provider="anthropic", tools=SAMPLE_TOOLS,
    )
    assert result["tool_calls"][0]["id"] == "tu_xyz"


# --- agentic_completion ---

from gotg.model import agentic_completion


def _mock_anthropic_text_response(text):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [{"type": "text", "text": text}],
        "usage": {},
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_anthropic_tool_response(text, tool_uses):
    """Build a mock Anthropic response with text + tool_use blocks."""
    content = [{"type": "text", "text": text}]
    for tu in tool_uses:
        content.append({
            "type": "tool_use",
            "id": tu["id"],
            "name": tu["name"],
            "input": tu["input"],
        })
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"content": content, "usage": {}}
    resp.raise_for_status = MagicMock()
    return resp


@patch("gotg.model.httpx.post")
def test_agentic_no_tool_calls_returns_text(mock_post):
    mock_post.return_value = _mock_anthropic_text_response("Just text")
    result = agentic_completion(
        "https://api.anthropic.com", "m",
        [{"role": "user", "content": "hi"}],
        api_key="sk", provider="anthropic",
        tools=SAMPLE_TOOLS, tool_executor=lambda n, i: "ok",
    )
    assert result["content"] == "Just text"
    assert result["operations"] == []


@patch("gotg.model.httpx.post")
def test_agentic_executes_tools_and_returns_final(mock_post):
    """First call returns tool_use, second returns text-only."""
    mock_post.side_effect = [
        _mock_anthropic_tool_response("Let me read that.", [
            {"id": "tu_1", "name": "file_read", "input": {"path": "src/main.py"}},
        ]),
        _mock_anthropic_text_response("Here's the file content."),
    ]
    calls = []

    def executor(name, inp):
        calls.append((name, inp))
        return "print('hello')"

    result = agentic_completion(
        "https://api.anthropic.com", "m",
        [{"role": "user", "content": "read src/main.py"}],
        api_key="sk", provider="anthropic",
        tools=SAMPLE_TOOLS, tool_executor=executor,
    )
    assert result["content"] == "Here's the file content."
    assert len(result["operations"]) == 1
    assert result["operations"][0]["name"] == "file_read"
    assert result["operations"][0]["result"] == "print('hello')"
    assert len(calls) == 1


@patch("gotg.model.httpx.post")
def test_agentic_multiple_rounds(mock_post):
    """Agent calls tools twice before producing final text."""
    mock_post.side_effect = [
        _mock_anthropic_tool_response("Reading...", [
            {"id": "tu_1", "name": "file_list", "input": {"path": "."}},
        ]),
        _mock_anthropic_tool_response("Now reading file...", [
            {"id": "tu_2", "name": "file_read", "input": {"path": "src/a.py"}},
        ]),
        _mock_anthropic_text_response("Done."),
    ]
    result = agentic_completion(
        "https://api.anthropic.com", "m",
        [{"role": "user", "content": "explore"}],
        api_key="sk", provider="anthropic",
        tools=SAMPLE_TOOLS, tool_executor=lambda n, i: "result",
    )
    assert result["content"] == "Done."
    assert len(result["operations"]) == 2


@patch("gotg.model.httpx.post")
def test_agentic_respects_max_rounds(mock_post):
    """If max_rounds is reached, returns last text."""
    # Always return tool calls — should stop after max_rounds
    mock_post.return_value = _mock_anthropic_tool_response("Still going", [
        {"id": "tu_x", "name": "file_read", "input": {"path": "x"}},
    ])
    result = agentic_completion(
        "https://api.anthropic.com", "m",
        [{"role": "user", "content": "loop"}],
        api_key="sk", provider="anthropic",
        tools=SAMPLE_TOOLS, tool_executor=lambda n, i: "data",
        max_rounds=3,
    )
    assert result["content"] == "Still going"
    assert len(result["operations"]) == 3
    assert mock_post.call_count == 3


@patch("gotg.model.httpx.post")
def test_agentic_sends_tool_results_back(mock_post):
    """Verify tool results are sent back to the API in the correct format."""
    mock_post.side_effect = [
        _mock_anthropic_tool_response("Reading...", [
            {"id": "tu_1", "name": "file_read", "input": {"path": "a.py"}},
        ]),
        _mock_anthropic_text_response("Done."),
    ]
    agentic_completion(
        "https://api.anthropic.com", "m",
        [{"role": "user", "content": "read a.py"}],
        api_key="sk", provider="anthropic",
        tools=SAMPLE_TOOLS, tool_executor=lambda n, i: "file content",
    )
    # Second call should include assistant + tool_result messages
    second_call_body = mock_post.call_args_list[1][1]["json"]
    messages = second_call_body["messages"]
    # Last two messages: assistant (with tool_use) + user (with tool_result)
    assistant_msg = messages[-2]
    assert assistant_msg["role"] == "assistant"
    # Content should be the raw content blocks
    assert any(b["type"] == "tool_use" for b in assistant_msg["content"])
    tool_result_msg = messages[-1]
    assert tool_result_msg["role"] == "user"
    assert tool_result_msg["content"][0]["type"] == "tool_result"
    assert tool_result_msg["content"][0]["tool_use_id"] == "tu_1"
    assert tool_result_msg["content"][0]["content"] == "file content"


# --- agentic_completion (OpenAI path) ---

def _mock_openai_text_response(text):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": text}}]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _mock_openai_tool_response(text, tool_calls):
    """Build a mock OpenAI response with tool_calls."""
    message = {"content": text, "tool_calls": [
        {
            "id": tc["id"],
            "type": "function",
            "function": {"name": tc["name"], "arguments": json.dumps(tc["input"])},
        }
        for tc in tool_calls
    ]}
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"choices": [{"message": message}]}
    resp.raise_for_status = MagicMock()
    return resp


@patch("gotg.model.httpx.post")
def test_agentic_openai_no_tool_calls(mock_post):
    mock_post.return_value = _mock_openai_text_response("Just text")
    result = agentic_completion(
        "http://localhost", "m",
        [{"role": "user", "content": "hi"}],
        provider="openai",
        tools=SAMPLE_TOOLS, tool_executor=lambda n, i: "ok",
    )
    assert result["content"] == "Just text"
    assert result["operations"] == []


@patch("gotg.model.httpx.post")
def test_agentic_openai_executes_tools(mock_post):
    mock_post.side_effect = [
        _mock_openai_tool_response("Reading...", [
            {"id": "call_1", "name": "file_read", "input": {"path": "a.py"}},
        ]),
        _mock_openai_text_response("Done."),
    ]
    result = agentic_completion(
        "http://localhost", "m",
        [{"role": "user", "content": "read"}],
        provider="openai",
        tools=SAMPLE_TOOLS, tool_executor=lambda n, i: "content",
    )
    assert result["content"] == "Done."
    assert len(result["operations"]) == 1


# --- CompletionRound ---

from gotg.model import CompletionRound


def test_completion_round_build_continuation_anthropic():
    """Anthropic continuation builds assistant + user tool_result messages."""
    rnd = CompletionRound(
        content="thinking",
        tool_calls=[{"name": "file_read", "input": {"path": "x"}, "id": "tu_1"}],
        _provider="anthropic",
        _raw={"content_blocks": [
            {"type": "text", "text": "thinking"},
            {"type": "tool_use", "id": "tu_1", "name": "file_read", "input": {"path": "x"}},
        ]},
    )
    msgs = rnd.build_continuation([{"id": "tu_1", "result": "file content"}])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == rnd._raw["content_blocks"]
    assert msgs[1]["role"] == "user"
    assert msgs[1]["content"][0]["type"] == "tool_result"
    assert msgs[1]["content"][0]["tool_use_id"] == "tu_1"
    assert msgs[1]["content"][0]["content"] == "file content"


def test_completion_round_build_continuation_openai():
    """OpenAI continuation builds assistant message + tool messages."""
    raw_message = {
        "content": "thinking",
        "tool_calls": [
            {"id": "call_1", "function": {"name": "file_read", "arguments": '{"path": "x"}'}}
        ],
    }
    rnd = CompletionRound(
        content="thinking",
        tool_calls=[{"name": "file_read", "input": {"path": "x"}, "id": "call_1"}],
        _provider="openai",
        _raw={"message": raw_message},
    )
    msgs = rnd.build_continuation([{"id": "call_1", "result": "file content"}])
    assert len(msgs) == 2
    assert msgs[0] is raw_message  # same object reference
    assert msgs[1]["role"] == "tool"
    assert msgs[1]["tool_call_id"] == "call_1"
    assert msgs[1]["content"] == "file content"


@patch("gotg.model.httpx.post")
def test_raw_completion_openai_returns_completion_round(mock_post):
    """raw_completion with OpenAI provider returns CompletionRound."""
    from gotg.model import raw_completion
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{
            "message": {
                "content": "hello",
                "tool_calls": [{
                    "id": "call_1",
                    "function": {"name": "file_read", "arguments": '{"path": "x"}'},
                }],
            }
        }]
    }
    resp.raise_for_status = MagicMock()
    mock_post.return_value = resp

    rnd = raw_completion(
        "http://localhost", "m",
        [{"role": "user", "content": "hi"}],
        provider="openai",
        tools=SAMPLE_TOOLS,
    )
    assert isinstance(rnd, CompletionRound)
    assert rnd.content == "hello"
    assert len(rnd.tool_calls) == 1
    assert rnd.tool_calls[0]["name"] == "file_read"
    # Round-trip: build_continuation should work
    msgs = rnd.build_continuation([{"id": "call_1", "result": "ok"}])
    assert len(msgs) == 2


# --- max_tokens parameter plumbing ---


@patch("gotg.model.httpx.post")
def test_raw_completion_anthropic_max_tokens_default(mock_post):
    """raw_completion defaults to max_tokens=16384 for Anthropic."""
    from gotg.model import raw_completion
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {},
    }
    mock_post.return_value = resp
    raw_completion(
        "https://api.anthropic.com", "m",
        [{"role": "user", "content": "hi"}],
        api_key="sk", provider="anthropic",
    )
    body = mock_post.call_args[1]["json"]
    assert body["max_tokens"] == 16384


@patch("gotg.model.httpx.post")
def test_raw_completion_anthropic_max_tokens_custom(mock_post):
    """raw_completion passes custom max_tokens for Anthropic."""
    from gotg.model import raw_completion
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": {},
    }
    mock_post.return_value = resp
    raw_completion(
        "https://api.anthropic.com", "m",
        [{"role": "user", "content": "hi"}],
        api_key="sk", provider="anthropic",
        max_tokens=4096,
    )
    body = mock_post.call_args[1]["json"]
    assert body["max_tokens"] == 4096


@patch("gotg.model.httpx.post")
def test_raw_completion_openai_max_tokens(mock_post):
    """raw_completion passes max_tokens for OpenAI."""
    from gotg.model import raw_completion
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "choices": [{"message": {"content": "ok"}}]
    }
    mock_post.return_value = resp
    raw_completion(
        "http://localhost", "m",
        [{"role": "user", "content": "hi"}],
        provider="openai", max_tokens=8192,
    )
    body = mock_post.call_args[1]["json"]
    assert body["max_tokens"] == 8192


@patch("gotg.model.httpx.post")
def test_raw_completion_stream_max_tokens_default(mock_post):
    """raw_completion_stream defaults to max_tokens=16384."""
    from gotg.model import raw_completion_stream
    # Mock stream response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.iter_lines.return_value = iter([
        "data: " + json.dumps({"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        "data: " + json.dumps({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ok"}}),
        "data: " + json.dumps({"type": "content_block_stop", "index": 0}),
        "data: " + json.dumps({"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {}}),
    ])
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)

    with patch("gotg.model.httpx.stream", return_value=mock_resp) as mock_stream:
        result = raw_completion_stream(
            "https://api.anthropic.com", "m",
            [{"role": "user", "content": "hi"}],
            api_key="sk", provider="anthropic",
        )
        list(result)

    body = mock_stream.call_args[1]["json"]
    assert body["max_tokens"] == 16384
