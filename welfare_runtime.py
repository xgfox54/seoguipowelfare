from __future__ import annotations

import http.client
import os
import sys
import urllib.error
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request


def configured_local_port(env_name: str, default: int) -> int:
    """Read an optional loopback port override while preserving a safe default."""
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        return default
    return port if 1 <= port <= 65535 else default


def bundle_root() -> Path:
    """Return the directory that contains bundled read-only application resources."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    return Path(frozen_root) if frozen_root else Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return bundle_root().joinpath(*parts)


_APP_VERSION_CACHE: str | None = None


def app_version() -> str:
    global _APP_VERSION_CACHE
    if _APP_VERSION_CACHE is not None:
        return _APP_VERSION_CACHE
    try:
        text = resource_path("VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        text = "0.0.0"
    _APP_VERSION_CACHE = text
    return text


def knowledge_base_root() -> Path:
    return bundle_root()


def open_http_url(request: Request | str, timeout: float) -> http.client.HTTPResponse:
    """Open an http(s) URL via http.client, rejecting any other scheme such as ``file://``.

    Accepts the same inputs as ``urllib.request.urlopen`` (a plain URL string or a
    ``urllib.request.Request``) and raises the same ``urllib.error`` exception types,
    so it is a drop-in replacement for existing call sites. Every caller in this
    project only ever targets a hardcoded localhost endpoint (Ollama or this app's
    own local server), never a value derived from user or network input; the scheme
    check is a defense-in-depth guard, not a mitigation for untrusted input.
    """
    if isinstance(request, str):
        url, method, data, header_items = request, "GET", None, []
    else:
        url = request.full_url
        method = request.get_method()
        data = request.data
        header_items = list(request.header_items())

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Refusing to open non-HTTP(S) URL scheme: {parts.scheme!r}")
    if parts.hostname not in {"127.0.0.1", "::1", "localhost"} or parts.username or parts.password:
        raise ValueError("Runtime permits only literal loopback destinations")

    connection_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    hostname = "127.0.0.1" if parts.hostname == "localhost" else parts.hostname
    connection = connection_cls(hostname, parts.port, timeout=timeout)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"

    try:
        connection.request(method, path, body=data, headers=dict(header_items))
        response = connection.getresponse()
    except OSError as error:
        raise urllib.error.URLError(error) from error

    if response.status >= 400:
        raise urllib.error.HTTPError(url, response.status, response.reason, response.msg, response)
    return response
