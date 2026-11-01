#!/usr/bin/env python3
"""Hash-pinned WBS04 v2231 download + source validation.

The CDN response is accepted only after size and SHA-256 checks. Use build.py
to generate the (experimental) release image.
"""
from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

from constants import CDN_URL, SOURCE_SHA256, SOURCE_SIZE

MAX_DOWNLOAD = 2 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError(f"firmware CDN redirected (HTTP {code}); refusing a different URL")


def download_source() -> bytes:
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(CDN_URL, headers={"User-Agent": "YOW-pinned-firmware-build/1"})
    with opener.open(request, timeout=30) as response:
        if response.status != 200 or response.url != CDN_URL:
            raise ValueError("firmware CDN returned an unexpected response")
        length = response.headers.get("Content-Length")
        if length is not None and int(length) != SOURCE_SIZE:
            raise ValueError("firmware CDN content length differs from the pinned image")
        data = response.read(MAX_DOWNLOAD + 1)
    return verify_source(data)


def verify_source(data: bytes) -> bytes:
    if len(data) != SOURCE_SIZE or hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("downloaded firmware differs from pinned stock v2231")
    return data


def read_pinned(path: Path) -> bytes:
    return verify_source(Path(path).expanduser().read_bytes())
