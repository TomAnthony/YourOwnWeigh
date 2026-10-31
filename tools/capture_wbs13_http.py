#!/usr/bin/env python3
"""Local WBS13 v100 HTTP/HTTPS recorder for protocol exploration (Python 3.11+).

Run from the repository root, e.g.:
  sudo python3 tools/capture_wbs13_http.py --host YOUR_LAN_IP \
      --session-profile local/wbs13-capture-profile.json

Point the patched scale at that IP with HTTP. No normal YOW server is needed.
For HTTPS, supply --cert and --key; the default port then becomes 443. The
recorder never contacts Withings, changes the YOW database, or offers firmware.

A profile supplies the small set of session fields the stock parser applies
even when omitted. Without one, /once works but /session returns 503. This is
an experimental responder, not a production server: optional sp.users replaces
the scale's roster and supplies matching embedded measurement screens. Omitting
sp.users clears any existing roster. Empty feature/history responses clear
those cached settings. Use explicit test profiles; see tools/README.md.

Full HTTP plaintext, including chunk framing, duplicate headers and trailers,
is saved privately. Upload success is sent ONLY after the request and planned
response have been fsynced. Successful uploads may leave the scale's queue;
their data remains in the capture, not the YOW database. --keep-queued returns
503 for uploads instead, which may stop the sync at its first upload.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from email.utils import formatdate
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import socketserver
import ssl
import threading
import time
from urllib.parse import parse_qsl, urlsplit

MAX_BODY = 8 * 1024 * 1024
MAX_WIRE = 16 * 1024 * 1024
MAX_HEADERS = 65536
MAX_LINE = 8192
ROOT = Path(__file__).resolve().parents[1]


def utc():
    return datetime.now(timezone.utc).isoformat()


def encode_json(value):
    return (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode()


def private_owner(path):
    # A port-80 sudo invocation must still leave captures readable by its owner.
    if hasattr(os, "geteuid") and os.geteuid() == 0 and os.environ.get("SUDO_UID"):
        os.chown(path, int(os.environ["SUDO_UID"]), int(os.environ["SUDO_GID"]))


class Store:
    """One new directory per run; fsync all exchange files before acknowledging."""
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.mkdir(parents=True, mode=0o700, exist_ok=False)
        private_owner(self.path)
        self.lock = threading.Lock()
        self.sequence = 0
        self.save("events.jsonl", b"")

    def save(self, name, data):
        path = self.path / name
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        private_owner(path)

    def sync_directory(self):
        fd = os.open(self.path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def event(self, **fields):
        with self.lock:
            with (self.path / "events.jsonl").open("ab") as stream:
                stream.write(encode_json({"utc": utc(), **fields}))
                stream.flush()
                os.fsync(stream.fileno())

    def exchange(self, reader, response, **fields):
        with self.lock:
            self.sequence += 1
            prefix = f"{self.sequence:06d}"
        names = {"request": prefix + ".request.http", "body": prefix + ".body.bin",
                 "response": prefix + ".response.http"}
        self.save(names["request"], bytes(reader.raw))
        self.save(names["body"], bytes(reader.body))
        self.save(names["response"], response)
        # Directory entries as well as file contents must exist before status 0.
        self.sync_directory()
        self.event(event="response_prepared", exchange=prefix, files=names,
                   method=reader.method, target=reader.target, headers=reader.headers,
                   trailers=reader.trailers, complete=reader.complete,
                   body_bytes=len(reader.body), body_sha256=hashlib.sha256(reader.body).hexdigest(),
                   body_text=reader.body.decode("utf-8", errors="replace"), **fields)
        return prefix


class HTTPError(ValueError):
    pass


class Reader:
    """Read a single HTTP/1 request without normalizing the saved wire bytes."""
    def __init__(self, stream):
        self.stream = stream
        self.raw, self.body = bytearray(), bytearray()
        self.headers, self.trailers = [], []
        self.method, self.target, self.version = "", "", ""
        self.complete = False
        self.close = False

    def take(self, size=None, eof_ok=False):
        # Buffered readline/read(size) can consume a partial packet then raise a
        # timeout without returning those bytes. Record incremental reads so
        # that partial headers and chunks survive that failure too.
        data = bytearray()
        while size is None or len(data) < size:
            part = self.stream.read(1) if size is None else self.stream.read1(min(65536, size - len(data)))
            if not part:
                if eof_ok and not data:
                    return b""
                raise HTTPError("Incomplete HTTP request")
            data.extend(part)
            self.raw.extend(part)
            if len(self.raw) > MAX_WIRE:
                raise HTTPError("HTTP wire size exceeds capture limit")
            if size is None:
                if len(data) > MAX_LINE:
                    raise HTTPError("Oversized HTTP line")
                if data.endswith(b"\n"):
                    if not data.endswith(b"\r\n"):
                        raise HTTPError("Missing HTTP CRLF")
                    break
        return bytes(data)

    def fields(self, output):
        start = len(self.raw)
        while True:
            line = self.take()
            if len(self.raw) - start > MAX_HEADERS:
                raise HTTPError("HTTP headers/trailers exceed capture limit")
            if line == b"\r\n":
                return
            name, colon, value = line[:-2].partition(b":")
            if not colon or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
                raise HTTPError("Invalid HTTP header")
            output.append([name.decode("ascii"), value.strip(b" \t").decode("latin-1")])

    def read(self):
        # EOF between requests is normal; preserve partial/malformed input below.
        first = self.take(eof_ok=True)
        if not first:
            return False
        if len(first) > MAX_LINE or not first.endswith(b"\r\n"):
            raise HTTPError("Invalid request line")
        parts = first[:-2].split(b" ")
        if len(parts) != 3 or parts[2] not in (b"HTTP/1.0", b"HTTP/1.1"):
            raise HTTPError("Expected HTTP/1 request line")
        self.method, self.target, self.version = [p.decode("ascii") for p in parts]
        if not self.target.startswith("/") or self.target.startswith("//"):
            raise HTTPError("Expected origin-form request target")
        self.fields(self.headers)
        values = {}
        for key, value in self.headers:
            values.setdefault(key.lower(), []).append(value)
        self.close = self.version == "HTTP/1.0" or "close" in ",".join(values.get("connection", [])).lower()
        if "expect" in values:
            # This firmware does not use Expect. Do not deadlock awaiting a body
            # from another client that is waiting for 100 Continue.
            raise HTTPError("Expect is not supported by this diagnostic listener")
        transfer, lengths = values.get("transfer-encoding", []), values.get("content-length", [])
        if transfer and lengths:
            raise HTTPError("Ambiguous Transfer-Encoding and Content-Length")
        if transfer:
            if len(transfer) != 1 or transfer[0].lower() != "chunked":
                raise HTTPError("Unsupported transfer coding")
            while True:
                chunk = self.take()[:-2].split(b";", 1)[0]
                if not re.fullmatch(rb"[0-9a-fA-F]+", chunk):
                    raise HTTPError("Invalid chunk length")
                size = int(chunk, 16)
                if len(self.body) + size > MAX_BODY:
                    raise HTTPError("Body exceeds capture limit")
                if size == 0:
                    self.fields(self.trailers)
                    break
                self.body.extend(self.take(size))
                if self.take(2) != b"\r\n":
                    raise HTTPError("Invalid chunk terminator")
        elif lengths:
            if len(lengths) != 1 or not re.fullmatch(r"[0-9]+", lengths[0]):
                raise HTTPError("Invalid or duplicate Content-Length")
            size = int(lengths[0])
            if size > MAX_BODY:
                raise HTTPError("Body exceeds capture limit")
            self.body.extend(self.take(size))
        self.complete = True
        return True


def load_profile(path):
    if path is None:
        return None
    profile = json.loads(Path(path).read_text())
    if not isinstance(profile, dict) or not {"ctp", "ind"} <= profile.keys() or profile.keys() - {"ctp", "ind", "sp"}:
        raise ValueError("Profile requires ctp/ind and optional sp.users; never firmware offers or credentials")
    ctp, ind = profile["ctp"], profile["ind"]
    if not isinstance(ctp, dict) or set(ctp) != {"goff", "dst", "ngoff"}:
        raise ValueError("Profile ctp requires goff, dst and ngoff")
    if not isinstance(ind, dict) or set(ind) != {"stp", "fm", "ws"}:
        raise ValueError("Profile ind requires exactly stp, fm and ws")
    if any(type(v) is not int for v in [*ctp.values(), *ind.values()]):
        raise ValueError("Profile settings must be integers")
    if not all(-86400 <= ctp[k] <= 86400 for k in ("goff", "ngoff")) or not 0 <= ctp["dst"] <= 0xffffffff:
        raise ValueError("Profile clock fields outside bounds")
    if any(not 0 <= v <= 0xffffffff for v in ind.values()) or ind["ws"] not in (0, 1):
        raise ValueError("Profile device settings outside bounds")
    if "sp" in profile:
        sp = profile["sp"]
        if not isinstance(sp, dict) or set(sp) != {"users"} or not isinstance(sp["users"], list):
            raise ValueError("Profile sp must contain only a users list")
        if len(sp["users"]) > 8:
            raise ValueError("WBS13 supports at most eight users")
        ids = set()
        for user in sp["users"]:
            # This bounded wire profile fits the original 0x17e-byte user record.
            # Do not accept an arbitrary vendor session (account IDs, FT flags,
            # firmware offers, etc.) just to provision a diagnostic user.
            if not isinstance(user, dict) or set(user) != {"id", "sn", "fn", "ht", "agt", "sx", "wt", "fm", "cr", "att", "cs"}:
                raise ValueError("Each user requires id/sn/fn/ht/agt/sx/wt/fm/cr/att/cs")
            for key, low, high in (("id", 1, 0x7fffffff), ("sx", 0, 1),
                                   ("fm", 0, 0x7fff), ("cr", 0, 0xffffffff),
                                   ("att", 0, 0xffffffff)):
                if type(user[key]) is not int or not low <= user[key] <= high:
                    raise ValueError(f"User {key} outside bounds")
            if user["id"] in ids:
                raise ValueError("User IDs must be unique")
            ids.add(user["id"])
            for key, low, high in (("ht", .9, 2.49), ("agt", 18, 99), ("wt", 29, 270)):
                value = user[key]
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"Adult test user {key} outside bounds (height in metres, weight in kg)")
            if not isinstance(user["sn"], str) or not re.fullmatch(r"[A-Z0-9]{3}", user["sn"]):
                raise ValueError("User sn must be three uppercase letters/digits")
            if not isinstance(user["fn"], str) or not re.fullmatch(r"[ -~]{1,16}", user["fn"]):
                raise ValueError("User fn must be 1–16 printable ASCII characters")
            screens = user["cs"]
            if not isinstance(screens, str) or len(screens) > 31 or not re.fullmatch(r"[0-9]+(?:,[0-9]+)*", screens):
                raise ValueError("User cs must be a comma-separated screen list of at most 31 bytes")
            screen_ids = [int(value) for value in screens.split(",")]
            if len(screen_ids) > 16 or len(set(screen_ids)) != len(screen_ids) or any(value not in (1, 2, 3, 14, 15, 16, 22) for value in screen_ids):
                raise ValueError("User cs supports unique embedded screens 1,2,3,14,15,16,22 (at most 16)")
    return profile


def screen_body(profile):
    """Keep /v2/screen consistent with the roster's cs measurement selection.

    WBS13 clears every user's screen list before applying getbydeviceid, so an
    empty response would erase the cs list just provisioned by /session. The
    stock 1311/v100 screen gate maps embedded ID 1 to body composition and 3 to
    heart rate; IDs 14/15/16/22 also request body composition. Screens with src=1
    use built-in rendering and need no downloaded images or feature flags.
    """
    users = (profile or {}).get("sp", {}).get("users", [])
    return {"device": [], "user": [
        {"userid": user["id"], "screens": [
            {"id": int(screen), "src": 1, "embid": int(screen), "rk": rank}
            for rank, screen in enumerate(user["cs"].split(","), 1)
        ]} for user in users
    ]}


class Responder:
    """Small, explicit WBS13 diagnostic profile; unknown endpoints fail visibly."""
    def __init__(self, profile, keep_queued=False):
        self.profile, self.keep_queued = profile, keep_queued
        self.sessions = {}
        self.lock = threading.Lock()

    def reply(self, request, peer):
        url = urlsplit(request.target)
        pairs = parse_qsl(url.query, keep_blank_values=True, max_num_fields=4096)
        if request.body:
            pairs += parse_qsl(request.body.decode("utf-8"), keep_blank_values=True, max_num_fields=4096)
        params = {}
        for key, value in pairs:
            params.setdefault(key, []).append(value)
        # Duplicate measurement fields are valid; control fields are singular.
        for key in ("appname", "action", "sessionid"):
            if len(params.get(key, [])) > 1:
                return 400, {"status": 400, "error": "duplicate control field"}, "rejected"
        def get(key):
            return params.get(key, [""])[0]
        action = get("action")
        if request.method != "POST" or get("appname") != "WBS13":
            return 400, {"status": 400, "error": "WBS13 POST requests only"}, "rejected"
        if url.path == "/once" and action in ("get", "probe"):
            return 200, ({"status": 0, "body": {"once": secrets.token_hex(12)}} if action == "get" else {"status": 0}), "challenge"
        if url.path == "/session" and action == "new":
            if self.profile is None:
                return 503, {"status": 503, "error": "capture needs an explicit session profile"}, "profile_required"
            token = secrets.token_hex(12)
            with self.lock:
                self.sessions = {k: v for k, v in self.sessions.items() if v[1] > time.monotonic()}
                if len(self.sessions) >= 128:
                    return 503, {"status": 503}, "session_limit"
                self.sessions[token] = (peer, time.monotonic() + 900)
            return 200, {"status": 0, "body": {"sessionid": token, "syp": {"utc": int(time.time())}, **self.profile}}, "session_opened"
        token = get("sessionid")
        with self.lock:
            session = self.sessions.get(token)
        if not session or session[0] != peer or session[1] < time.monotonic():
            return 403, {"status": 403, "error": "unknown capture session"}, "rejected"
        if url.path == "/session" and action == "delete":
            with self.lock:
                self.sessions.pop(token, None)
            return 200, {"status": 0}, "session_closed"
        bodies = {
            ("/v2/screen", "getbydeviceid"): screen_body(self.profile),
            ("/v2/screen", "getcontentbydeviceid"): {"user_screens": []},
            ("/v2/summary", "getforscale"): [],
            ("/v2/weather", "getforecast"): {},
            ("/v2/measure", "getlastupdate"): {"devices": []},
            ("/v2/feature", "getbydevice"): {"device_features": [], "user_features": []},
        }
        if (url.path, action) in bodies:
            body = bodies[url.path, action]
            outcome = "roster_screens" if url.path == "/v2/screen" and action == "getbydeviceid" and body["user"] else "empty_diagnostic_response"
            return 200, {"status": 0, "body": body}, outcome
        if (url.path, action) in (("/measure", "batchstore"), ("/v2/event", "fire")):
            if self.keep_queued:
                return 503, {"status": 503, "error": "saved; keep queued requested"}, "upload_saved_not_acknowledged"
            # No normalization: unknown fields and metric-only groups are retained.
            # The caller must durably save the request BEFORE sending this status.
            return 200, {"status": 0}, "upload_saved_and_acknowledged"
        return 503, {"status": 503, "error": "unimplemented capture response"}, "unknown_endpoint_or_action"


def response_bytes(status, payload, close=False):
    body = encode_json(payload)
    reason = {200: "OK", 400: "Bad Request", 403: "Forbidden", 503: "Service Unavailable"}[status]
    return (f"HTTP/1.1 {status} {reason}\r\nDate: {formatdate(usegmt=True)}\r\n"
            f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
            f"Cache-Control: no-store\r\nConnection: {'close' if close else 'keep-alive'}\r\n\r\n").encode() + body


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    # Finish in-flight capture writes before returning from Ctrl-C.
    daemon_threads = False

    def __init__(self, address, store, responder, tls=None):
        self.store, self.responder, self.tls = store, responder, tls
        self.stopping = threading.Event()
        super().__init__(address, Handler)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        connection = secrets.token_hex(6)
        peer = self.client_address[0]
        sock = self.request
        sock.settimeout(30)
        try:
            if self.server.tls:
                sock = self.server.tls.wrap_socket(sock, server_side=True)
            self.server.store.event(event="connected", connection=connection, peer=peer,
                                    tls=sock.version() if isinstance(sock, ssl.SSLSocket) else None,
                                    cipher=sock.cipher() if isinstance(sock, ssl.SSLSocket) else None)
            with sock.makefile("rb") as stream:
                while not self.server.stopping.is_set():
                    reader = Reader(stream)
                    try:
                        if not reader.read():
                            break
                        status, payload, outcome = self.server.responder.reply(reader, peer)
                    except (ValueError, OSError) as error:
                        if not reader.raw:
                            break
                        status, payload, outcome = 400, {"status": 400, "error": str(error)}, "incomplete_or_invalid_request"
                        reader.close = True
                    reader.close = reader.close or self.server.stopping.is_set()
                    response = response_bytes(status, payload, reader.close)
                    # Any write/fsync failure exits without a success response.
                    ident = self.server.store.exchange(reader, response, connection=connection,
                                                       peer=peer, status=status, outcome=outcome)
                    sock.sendall(response)
                    self.server.store.event(event="response_sent", exchange=ident, connection=connection)
                    path = reader.target.split("?", 1)[0]
                    print(f"{utc()} {ident} {reader.method} {path[:160]!r} {len(reader.body)} bytes → {status} ({outcome})", flush=True)
                    if reader.close:
                        break
        except (OSError, ValueError) as error:
            # Do not expose bodies, session IDs or credentials in terminal logs.
            print(f"{utc()} connection {connection}: {type(error).__name__}; no further acknowledgement", flush=True)
            try:
                self.server.store.event(event="connection_error", connection=connection,
                                        error_type=type(error).__name__, detail=str(error))
            except OSError:
                pass  # A failed capture volume cannot safely record another event.
        finally:
            sock.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", required=True, help="This computer's LAN IPv4 address")
    parser.add_argument("--port", type=int, help="Default 80 for HTTP or 443 with --cert/--key")
    parser.add_argument("--session-profile", type=Path, help="Explicit ctp/ind JSON with optional sp.users; see tools/README.md")
    parser.add_argument("--output", type=Path, help="New private capture directory; default local/captures/wbs13-http-TIMESTAMP")
    parser.add_argument("--duration", type=int, default=0, help="Stop after N seconds; default runs until Ctrl-C")
    parser.add_argument("--keep-queued", action="store_true", help="Save uploads but return 503 instead of success")
    parser.add_argument("--cert", type=Path, help="PEM server certificate/chain for HTTPS")
    parser.add_argument("--key", type=Path, help="PEM server private key for HTTPS")
    args = parser.parse_args(argv)
    try:
        ipaddress.IPv4Address(args.host)
        if bool(args.cert) != bool(args.key):
            raise ValueError("Supply both --cert and --key for HTTPS")
        port = args.port if args.port is not None else (443 if args.cert else 80)
        if not 1 <= port <= 65535 or not 0 <= args.duration <= 86400:
            raise ValueError("Port must be 1–65535; duration 0–86400 seconds")
        profile = load_profile(args.session_profile)
        tls = None
        if args.cert:
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.minimum_version = tls.maximum_version = ssl.TLSVersion.TLSv1_3
            tls.load_cert_chain(args.cert, args.key)
        output = args.output or ROOT / "local/captures" / f"wbs13-http-{datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}"
        store = Store(output)
        store.save("run.json", encode_json({"format": "YOW-WBS13-HTTP-capture-v1", "started": utc(),
                   "host": args.host, "port": port, "https": bool(tls), "session_profile": profile,
                   "keep_queued": args.keep_queued, "auth": "diagnostic only; vendor hash not verified"}))
        with Server((args.host, port), store, Responder(profile, args.keep_queued), tls) as server:
            server.timeout = 0.5
            print(f"Listening on {'https' if tls else 'http'}://{args.host}:{port}", flush=True)
            print(f"Private capture: {store.path}", flush=True)
            print("Standalone recorder; no YOW server or Withings connection needed. Stop with Ctrl-C.", flush=True)
            print("Uploads: " + ("saved but rejected to keep them queued." if args.keep_queued else "acknowledged after durable raw capture; not imported into YOW."), flush=True)
            if profile is None:
                print("No session profile: captures stop at /session with HTTP 503.", flush=True)
            else:
                users = profile.get("sp", {}).get("users", [])
                print(f"Roster: {len(users)} test user(s); replaces the scale's existing roster on sync.", flush=True)
                if users:
                    print("Sync once to install the profile, then weigh again barefoot and confirm your test name appears.", flush=True)
            deadline = time.monotonic() + args.duration if args.duration else float("inf")
            try:
                while time.monotonic() < deadline:
                    server.handle_request()
            except KeyboardInterrupt:
                pass
            finally:
                server.stopping.set()
        print(f"Capture finished: {store.path}")
    except (OSError, ValueError, TypeError) as error:
        parser.exit(1, f"Capture could not start: {error}\n")


if __name__ == "__main__":
    main()
