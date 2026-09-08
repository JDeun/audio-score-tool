from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_MAX_JSON_BYTES = 4 * 1024 * 1024


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("URL contains an invalid port") from exc
    if port is None:
        port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return scheme, host, port


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep credentials and POST bodies on the configured origin.

    Same-origin redirects remain compatible with providers that canonicalize their API
    paths. Cross-origin redirects are rejected when a request carries Authorization or
    a non-GET body so API keys/fingerprints/prompts are not forwarded to another host.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            old_origin = _origin(req.full_url)
            new_origin = _origin(newurl)
        except ValueError as exc:
            raise urllib.error.HTTPError(
                req.full_url,
                400,
                f"Invalid redirect URL: {exc}",
                headers,
                fp,
            ) from exc
        has_authorization = req.has_header("Authorization")
        has_sensitive_body = req.data is not None and req.get_method().upper() != "GET"
        if old_origin != new_origin and (has_authorization or has_sensitive_body):
            raise urllib.error.HTTPError(
                req.full_url,
                403,
                "Cross-origin redirect blocked for sensitive API request",
                headers,
                fp,
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(SafeRedirectHandler())


def open_json(
    request: urllib.request.Request,
    *,
    timeout: float,
    max_bytes: int = DEFAULT_MAX_JSON_BYTES,
) -> Any:
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            content_length = response.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > max_bytes:
                        raise RuntimeError(f"External API JSON response exceeds {max_bytes} bytes")
                except ValueError:
                    pass
            raw = response.read(max_bytes + 1)
    except RuntimeError:
        raise
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise RuntimeError(str(exc)) from exc
    if len(raw) > max_bytes:
        raise RuntimeError(f"External API JSON response exceeds {max_bytes} bytes")
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("External API returned invalid JSON") from exc
