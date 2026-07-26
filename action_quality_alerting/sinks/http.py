"""Shared HTTP transport with pluggable auth. `requests` is provided by the
DataHub executor runtime, so it is imported lazily rather than declared as a hard
dependency."""

import hashlib
import hmac
import json as _json
from typing import Any

from action_quality_alerting.config import HTTPAuthConfig, HTTPAuthType


def _sign(secret: str, algorithm: str, body: bytes) -> str:
    digestmod = getattr(hashlib, algorithm, hashlib.sha256)
    return hmac.new(secret.encode("utf-8"), body, digestmod).hexdigest()


def send(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    json_body: Any | None = None,
    data: str | None = None,
    auth: HTTPAuthConfig | None = None,
    basic_auth: tuple[str, str] | None = None,
    timeout: int = 30,
) -> "Any":
    import requests

    final_headers: dict[str, str] = dict(headers or {})
    request_auth: tuple[str, str] | None = basic_auth

    # Serialize the body ourselves so HMAC signs exactly what is sent.
    body_bytes: bytes | None = None
    if json_body is not None:
        data = _json.dumps(json_body)
        final_headers.setdefault("Content-Type", "application/json")
    if data is not None:
        body_bytes = data.encode("utf-8")

    if auth is not None:
        if auth.type == HTTPAuthType.BEARER and auth.token:
            final_headers["Authorization"] = f"Bearer {auth.token}"
        elif auth.type == HTTPAuthType.BASIC and auth.username and auth.password:
            request_auth = (auth.username, auth.password)
        elif auth.type == HTTPAuthType.HMAC and auth.secret and body_bytes is not None:
            final_headers[auth.header] = _sign(auth.secret, auth.algorithm, body_bytes)

    resp = requests.request(
        method=method.upper(),
        url=url,
        headers=final_headers,
        params=params,
        data=body_bytes,
        auth=request_auth,
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp
