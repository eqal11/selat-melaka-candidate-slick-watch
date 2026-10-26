"""Bounded external HTTP calls. Never log signed asset URLs or response bodies."""

import time

import httpx


def get_json(url, params=None):
    error = None
    for attempt in range(3):
        try:
            with httpx.Client(timeout=httpx.Timeout(20, connect=8), follow_redirects=True) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            error = type(exc).__name__
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code < 500
                and exc.response.status_code != 429
            ):
                break
            time.sleep(0.5 * 2**attempt)
    raise RuntimeError(f"External service unavailable ({error}); retry later")
