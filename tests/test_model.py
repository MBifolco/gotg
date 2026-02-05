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
