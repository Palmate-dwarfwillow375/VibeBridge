"""Proxy Main-originated HTTP requests through the Node's in-process ASGI app."""

from __future__ import annotations

import base64
from typing import Any

import httpx
from fastapi import FastAPI

_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

_PROXY_APP: FastAPI | None = None


def set_proxy_app(app: FastAPI) -> None:
    """Register the in-process ASGI app used for WS-backed proxy requests."""
    global _PROXY_APP
    _PROXY_APP = app


def _normalize_headers(headers: dict[str, Any] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in (headers or {}).items():
        header_name = str(key).strip()
        if not header_name or header_name.lower() in _HOP_BY_HOP_HEADERS:
            continue
        normalized[header_name] = str(value)
    normalized.setdefault("host", "node.local")
    return normalized


def _decode_body(body: str | None, encoding: str) -> bytes:
    if not body:
        return b""
    if encoding == "base64":
        return base64.b64decode(body)
    return body.encode("utf-8")


async def proxy_http_request(
    *,
    method: str,
    path: str,
    query_string: str = "",
    headers: dict[str, Any] | None = None,
    body: str | None = None,
    body_encoding: str = "base64",
) -> dict[str, Any]:
    """Execute an HTTP request against the local FastAPI app without a TCP hop."""
    if _PROXY_APP is None:
        raise RuntimeError("Node proxy app is not initialized")

    url = path or "/"
    if query_string:
        url = f"{url}?{query_string}"

    request_headers = _normalize_headers(headers)
    request_body = _decode_body(body, body_encoding)

    transport = httpx.ASGITransport(app=_PROXY_APP)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://node.local",
        timeout=60.0,
        follow_redirects=False,
    ) as client:
        response = await client.request(
            method=(method or "GET").upper(),
            url=url,
            headers=request_headers,
            content=request_body,
        )

    response_headers = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in _HOP_BY_HOP_HEADERS
    }
    return {
        "statusCode": response.status_code,
        "headers": response_headers,
        "body": base64.b64encode(response.content).decode("ascii"),
        "bodyEncoding": "base64",
    }
