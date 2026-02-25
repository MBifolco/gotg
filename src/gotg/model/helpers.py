from __future__ import annotations

import httpx


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
