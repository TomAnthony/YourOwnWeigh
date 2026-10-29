#!/usr/bin/env python3
"""Hash-pinned WBS06 v1181 download, source validation and output helpers.

The CDN response is accepted only after size, SHA-256 and container checks.
Use build.py to generate the complete release image."""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path

from validate_stock import PINNED_SHA256, validate_source


CDN_URL = "http://cdnfw.withings.net/wbs06/wbs06_1181_XFUxfc.bin"
SOURCE_SIZE = 897_172
MAX_DOWNLOAD = 1_048_576


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError(f"firmware CDN redirected (HTTP {code}); refusing a different URL")


def download_source() -> bytes:
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(
        CDN_URL, headers={"User-Agent": "YOW-pinned-firmware-build/1"}
    )
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or response.url != CDN_URL:
            raise ValueError("firmware CDN returned an unexpected response")
        header_length = response.headers.get("Content-Length")
        if header_length is not None and int(header_length) != SOURCE_SIZE:
            raise ValueError("firmware CDN content length differs from the pinned image")
        data = response.read(MAX_DOWNLOAD + 1)
    return verify_source(data)


def verify_source(data: bytes) -> bytes:
    if len(data) != SOURCE_SIZE or hashlib.sha256(data).hexdigest() != PINNED_SHA256:
        raise ValueError("downloaded firmware differs from pinned stock v1181")
    validate_source(data)
    return data


def write_new_or_verify(path: Path, candidate: bytes) -> str:
    path = path.expanduser().resolve()
    if path.exists():
        if path.is_file() and path.read_bytes() == candidate:
            return f"Existing image verified: {path}"
        raise ValueError(f"refusing to overwrite a different file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(candidate)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return f"Wrote file: {path}"
