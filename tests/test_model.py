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
    """HTTP errors (400, 500, etc.) should propagate as exceptions."""
    import httpx
    resp = MagicMock()
    resp.status_code = 500
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=resp
    )
    mock_post.return_value = resp
    with pytest.raises(httpx.HTTPStatusError):
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
    assert body["system"] == "Be helpful."
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
            {"type": "tool_use", "name": "my_tool", "input": {"arg": "value"}},
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
