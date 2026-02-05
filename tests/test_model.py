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
