"""Bounded JSON fetches and the small coercions every vendor module shares.

Nothing here knows a vendor. It exists so that each vendor module is only its
vocabulary — which fields, what they mean — and the mechanics of "GET a small
JSON document without letting a misconfigured URL buffer something enormous
onto a Pi" are written once.
"""

from __future__ import annotations

import json
import math
from typing import Any, Final
from urllib.parse import urljoin

import httpx

#: Per-request timeout for every feeder HTTP probe. Every source is on the LAN
#: (usually the same host); one that cannot answer a few kilobytes in three
#: seconds is one to try again next poll.
REQUEST_TIMEOUT_S: Final = 3.0

#: Ceiling on one document. The largest source (readsb ``stats.json``) is a few
#: kilobytes.
MAX_DOCUMENT_BYTES: Final = 1024 * 1024


class FetchError(Exception):
    """A document could not be fetched or decoded. The message is loggable."""


def join_url(base: str, path: str) -> str:
    """``path`` resolved against ``base``, treating ``base`` as a directory."""
    return urljoin(base if base.endswith("/") else f"{base}/", path)


async def fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    """GET ``url`` and return its decoded JSON body.

    Raises:
        FetchError: unreachable, an error status, oversized, or not JSON. The
            message names the URL and the reason but never a response body.
    """
    try:
        async with client.stream("GET", url, timeout=REQUEST_TIMEOUT_S) as response:
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code} from {url}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    raise FetchError(f"document at {url} exceeds {MAX_DOCUMENT_BYTES} bytes")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise FetchError(f"could not reach {url}: {type(exc).__name__}") from exc
    try:
        return json.loads(b"".join(chunks))
    except ValueError as exc:
        raise FetchError(f"document at {url} is not JSON") from exc


def number(value: object) -> float | None:
    """A finite number, or ``None``. Numeric strings are accepted; ``bool`` is not."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    if not isinstance(value, int | float):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def count(value: object) -> int | None:
    """A non-negative integer, or ``None``."""
    result = number(value)
    if result is None or result < 0:
        return None
    return int(result)


def block(document: object, name: str) -> dict[str, Any]:
    """A named sub-object, or an empty one."""
    if not isinstance(document, dict):
        return {}
    value = document.get(name)
    return value if isinstance(value, dict) else {}


def text(value: object, *, limit: int = 200) -> str | None:
    """A non-empty display string, truncated, or ``None``."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped[:limit] or None


__all__ = [
    "MAX_DOCUMENT_BYTES",
    "REQUEST_TIMEOUT_S",
    "FetchError",
    "block",
    "count",
    "fetch_json",
    "join_url",
    "number",
    "text",
]
