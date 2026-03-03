"""Single source of truth for provider constants and model override logic."""

from __future__ import annotations


PROVIDERS = {
    "ollama": {
        "base_url": "http://localhost:11434",
        "default_model": "qwen2.5-coder:7b",
        "api_key": "",
        "models": [
            "qwen2.5-coder:7b",
            "qwen2.5-coder:14b",
            "qwen2.5-coder:32b",
            "llama3.2:8b",
            "deepseek-coder-v2:16b",
            "codellama:13b",
        ],
    },
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "default_model": "claude-sonnet-4-5-20250929",
        "api_key": "$ANTHROPIC_API_KEY",
        "models": [
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-6",
            "claude-haiku-4-5-20251001",
        ],
    },
    "openai": {
        "base_url": "https://api.openai.com",
        "default_model": "gpt-4o",
        "api_key": "$OPENAI_API_KEY",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "o1",
            "o3-mini",
        ],
    },
}


def provider_select_options() -> list[tuple[str, str]]:
    """(label, value) tuples for Textual Select."""
    return [(name, name) for name in PROVIDERS]


def model_names(provider: str) -> list[str]:
    """Known model names for a provider."""
    return list(PROVIDERS.get(provider, {}).get("models", []))


def provider_preset(provider: str) -> dict:
    """Return {base_url, api_key} for a provider."""
    p = PROVIDERS.get(provider, {})
    return {"base_url": p.get("base_url", ""), "api_key": p.get("api_key", "")}


def provider_runtime_config(provider: str, model: str | None = None) -> dict:
    """Build a clean runtime config dict (no UI metadata like 'models')."""
    p = PROVIDERS.get(provider, {})
    config = {
        "provider": provider,
        "base_url": p.get("base_url", ""),
        "model": model or p.get("default_model", ""),
    }
    api_key = p.get("api_key", "")
    if api_key:
        config["api_key"] = api_key
    return config


def build_model_override(
    provider: str,
    model: str,
    base_url: str,
    api_key: str,
    team_provider: str,
    team_base_url: str,
    team_api_key: str,
) -> dict | str:
    """Build a minimal override dict, or return an error string.

    Cross-provider: base_url required, api_key always persisted.
    Same-provider: only include base_url/api_key if they differ from team default.
    Returns error string if validation fails, override dict otherwise.
    """
    if not model:
        return "Model name is required for override."
    override: dict = {"provider": provider, "model": model}
    if provider != team_provider:
        if not base_url:
            return "Base URL is required when overriding to a different provider."
        override["base_url"] = base_url
        override["api_key"] = api_key
    else:
        if base_url != team_base_url:
            override["base_url"] = base_url
        if api_key != team_api_key:
            override["api_key"] = api_key
    return override
