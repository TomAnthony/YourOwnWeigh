#!/usr/bin/env python3
"""Capture a WS-30's first owner-HTTP requests without acknowledging uploads.

The scale must temporarily target this computer's LAN IP. Captures contain
private device traffic and are written to an owner-only file under local/.
"""

import argparse
import base64
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import parse_qs, urlsplit


MAX_BODY = 256_000


class CaptureServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, output):
        super().__init__(address, handler)
        self.output = output


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _body(self):
        transfer = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in transfer:
            body = bytearray()
            while True:
                header = self.rfile.readline(100)
                if not header or not header.endswith(b"\r\n"):
                    raise ValueError("invalid chunk header")
                size = int(header[:-2].split(b";", 1)[0], 16)
                if size < 0 or len(body) + size > MAX_BODY:
                    raise ValueError("body too large")
                if size == 0:
                    while self.rfile.readline(8192) not in (b"\r\n", b""):
                        pass
                    return bytes(body)
                body.extend(self.rfile.read(size))
                if self.rfile.read(2) != b"\r\n":
                    raise ValueError("invalid chunk terminator")
        length = self.headers.get("Content-Length")
        if length is None:
            return b""
        size = int(length)
        if size < 0 or size > MAX_BODY:
            raise ValueError("body too large")
        body = self.rfile.read(size)
        if len(body) != size:
            raise ValueError("incomplete body")
        return body

    def _reply(self, status, payload):
        content = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(content)
        self.close_connection = True

    def _capture(self):
        try:
            body = self._body()
        except (ValueError, OverflowError) as exc:
            self._reply(400, {"status": 400, "error": str(exc)})
            return
        parsed = urlsplit(self.path)
        record = {
            "utc": datetime.now(timezone.utc).isoformat(),
            "peer": self.client_address[0],
            "method": self.command,
            "target": self.path,
            "headers": dict(self.headers.items()),
            "body_base64": base64.b64encode(body).decode("ascii"),
            "body_text": body.decode("utf-8", errors="replace"),
        }
        with self.server.output.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"{record['utc']}  {record['peer']}  {self.command} {parsed.path}  {len(body)} bytes", flush=True)
        parameters = parse_qs(parsed.query)
        parameters.update(parse_qs(record["body_text"]))
        if parsed.path.rstrip("/").endswith("/once") and parameters.get("action") == ["get"]:
            self._reply(200, {"status": 0, "body": {"once": secrets.token_hex(12)}})
        else:
            # Never report success for a session or measurement that has not
            # been authenticated and durably stored by a real server adapter.
            self._reply(503, {"status": 503, "error": "diagnostic capture only"})

    do_GET = _capture
    do_POST = _capture
    do_PUT = _capture

    def log_message(self, _format, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="This Mac's LAN IPv4 address")
    parser.add_argument("--port", type=int, default=80)
    parser.add_argument("--duration", type=int, default=180, help="Stop after this many seconds (default 180)")
    parser.add_argument("--output", type=Path, help="Private JSONL path; defaults under local/captures")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.duration <= 3600:
        parser.error("port must be 1–65535 and duration must be 1–3600 seconds")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = args.output or Path("local/captures") / f"ws30-http-{stamp}-{os.getpid()}.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    # Port 80 commonly needs sudo. Keep the private capture readable by the
    # invoking user rather than leaving a root-only file behind.
    if os.geteuid() == 0 and "SUDO_UID" in os.environ and "SUDO_GID" in os.environ:
        os.chown(output, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))
    server = CaptureServer((args.host, args.port), Handler, output)
    server.timeout = 1
    print(f"Listening on http://{args.host}:{args.port}; private capture: {output}", flush=True)
    print("Only /once gets a test nonce; all other requests return 503. Stop with Ctrl-C.", flush=True)
    try:
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            server.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print(f"Capture finished: {output}", flush=True)


if __name__ == "__main__":
    main()
