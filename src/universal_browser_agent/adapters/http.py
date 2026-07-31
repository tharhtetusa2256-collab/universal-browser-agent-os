"""Minimal JSON HTTP transport shared by optional adapters."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AdapterHTTPError(RuntimeError):
    """Raised when an external adapter request fails safely."""


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str],
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read()
    except HTTPError as exc:
        limited = exc.read(2_000).decode("utf-8", errors="replace")
        raise AdapterHTTPError(
            f"External service returned HTTP {exc.code}: {limited}"
        ) from exc
    except URLError as exc:
        raise AdapterHTTPError(f"External service request failed: {exc.reason}") from exc

    if not response_body:
        return {}
    try:
        value = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise AdapterHTTPError("External service returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise AdapterHTTPError("External service JSON response must be an object")
    return value
