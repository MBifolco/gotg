from __future__ import annotations

import sys
import time

import httpx

from gotg.errors import ModelError

_RETRY_DELAYS = (5, 15, 30)  # seconds — 3 retries with increasing backoff


def _check_response(resp: httpx.Response) -> None:
    """Raise ModelError with the API error message on failure."""
    if resp.status_code >= 400:
        try:
            error_data = resp.json()
            # Anthropic: {"error": {"message": "..."}}
            # OpenAI: {"error": {"message": "..."}}
            error_msg = error_data.get("error", {}).get("message", resp.text)
        except Exception:
            error_msg = resp.text
        raise ModelError(f"API error ({resp.status_code}): {error_msg}")


def post_with_retry(url: str, **kwargs) -> httpx.Response:
    """httpx.post with automatic retry on 429 rate-limit responses."""
    for attempt, delay in enumerate(_RETRY_DELAYS):
        resp = httpx.post(url, **kwargs)
        if resp.status_code != 429:
            return resp
        retry_after = resp.headers.get("retry-after")
        wait = int(retry_after) if retry_after and retry_after.isdigit() else delay
        print(f"  [rate-limit] 429 from API, retrying in {wait}s (attempt {attempt + 1}/{len(_RETRY_DELAYS)})...", file=sys.stderr)
        time.sleep(wait)
    # Final attempt — no more retries
    return httpx.post(url, **kwargs)


def stream_with_retry(url: str, **kwargs):
    """httpx.stream context manager with automatic retry on 429 rate-limit responses."""
    for attempt, delay in enumerate(_RETRY_DELAYS):
        resp_cm = httpx.stream("POST", url, **kwargs)
        resp = resp_cm.__enter__()
        if resp.status_code != 429:
            # Return a wrapper that delegates __enter__/__exit__
            return _StreamWrapper(resp, resp_cm)
        resp_cm.__exit__(None, None, None)
        retry_after = resp.headers.get("retry-after")
        wait = int(retry_after) if retry_after and retry_after.isdigit() else delay
        print(f"  [rate-limit] 429 from API, retrying in {wait}s (attempt {attempt + 1}/{len(_RETRY_DELAYS)})...", file=sys.stderr)
        time.sleep(wait)
    # Final attempt — no more retries
    return httpx.stream("POST", url, **kwargs)


class _StreamWrapper:
    """Wraps an already-entered stream context manager."""

    def __init__(self, resp, cm):
        self._resp = resp
        self._cm = cm

    def __enter__(self):
        return self._resp

    def __exit__(self, *args):
        return self._cm.__exit__(*args)
