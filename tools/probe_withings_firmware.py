#!/usr/bin/env python3
"""Check a Withings firmware offer using a scale's MAC and raw session secret.

WS-30/WBS03 and WBS06 use the existing vendor lookup form with their respective
model names and stock versions (921 and 1181). WBS13 uses the form traced in v1311.
WBS13 requires its factory hostname, model CA and device client certificate/key;
this profile has been verified against a factory-new v1311 unit.
This is a standalone developer tool, not a Bluetooth connection or a firmware
downloader.

Only /once?action=get and /session?action=new are requested. The latter opens
a temporary vendor session; no registration, setup finalization, session-delete,
measurement upload or device writes are performed. Output contains only request
status and any firmware offer, never the returned roster or session token.

Python 3.9+, standard library only. Run --help for model and TLS options.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import http.client
import json
import math
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_HOST = "scalews.withings.net"
STOCK_VERSIONS = {"WBS03": 921, "WBS06": 1181, "WBS13": 1311}
MAX_RESPONSE = 2_000_000


class ProbeError(Exception):
    """A failed lookup, distinct from an accepted session without an offer."""


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not resend device authentication to a redirected destination.
        return None


def normalize_mac(value: str) -> str:
    raw = value.replace(":", "").replace("-", "").lower()
    if not re.fullmatch(r"[0-9a-f]{12}", raw):
        raise ValueError("MAC must contain exactly 12 hexadecimal digits")
    return ":".join(raw[i:i + 2] for i in range(0, 12, 2))


def integer(value: str) -> int:
    """Accept decimal (including leading zeroes) or explicitly prefixed hex."""
    try:
        return int(value, 16 if value.lower().startswith("0x") else 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use decimal or 0x-prefixed hexadecimal") from exc


def session_fields(args: argparse.Namespace, secret: str, nonce: str) -> dict:
    # Preserve the secret's spelling: the firmware hashes its stored text,
    # rather than interpreting the 16 characters as an eight-byte integer.
    fields = {
        "action": "new",
        "auth": args.mac,
        "hash": hashlib.sha256(f"{args.mac}:{secret}:{nonce}".encode("utf-8")).hexdigest(),
        "mfgid": args.mfgid,
        "currentfw": args.current_fw,
        "batterylvl": args.battery_level,
        "duration": 600 if args.model == "WBS13" else 300,
        "wstarget": 1,
        "enrich": "t",
        "trademark": args.trademark,
        "network": 1,
    }
    if args.model == "WBS13":
        fields["httpslink"] = 2
    fields.update({
        "hashmethod": "sha256",
        "trigger": "weather,ds" if args.model == "WBS13" else "weather",
        "withaccids": 1,
        "feature_mask": args.feature_mask,
    })
    # In particular, never append the stock setup-finalization flag final=true.
    return fields


class WithingsClient:
    def __init__(self, args: argparse.Namespace, report=print):
        context = ssl.create_default_context(cafile=args.ca_file)
        if args.client_cert:
            context.load_cert_chain(args.client_cert, args.client_key)
        self.opener = urllib.request.build_opener(
            NoRedirects(), urllib.request.HTTPSHandler(context=context),
        )
        self.host = args.host
        self.query = urllib.parse.urlencode({
            "appliver": args.current_fw, "appname": args.model, "apppfm": "device",
        })
        self.timeout = args.timeout
        self.report = report

    def post(self, path: str, fields: dict) -> dict:
        request = urllib.request.Request(
            f"https://{self.host}/{path}?{self.query}",
            data=urllib.parse.urlencode(fields).encode("ascii"),
            headers={"Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-store"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise ProbeError(f"/{path}: HTTP {response.status}; offer unknown")
                raw = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            exc.close()
            suffix = " (redirect refused)" if 300 <= exc.code < 400 else ""
            raise ProbeError(f"/{path}: HTTP {exc.code}{suffix}; offer unknown") from exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            if isinstance(reason, ssl.SSLCertVerificationError):
                detail = f"TLS certificate verification failed: {getattr(reason, 'verify_message', 'untrusted certificate')}"
            elif isinstance(reason, ssl.SSLError):
                detail = f"TLS failed: {getattr(reason, 'reason', None) or 'handshake/record error'}"
            elif isinstance(reason, TimeoutError):
                detail = "request timed out"
            else:
                detail = f"connection failed ({type(reason).__name__})"
            raise ProbeError(f"/{path}: {detail}; offer unknown") from exc

        if len(raw) > MAX_RESPONSE:
            raise ProbeError(f"/{path}: HTTP 200 response exceeds {MAX_RESPONSE} bytes")
        try:
            document = json.loads(raw)
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise ProbeError(f"/{path}: HTTP 200 response is not valid JSON") from exc
        if not isinstance(document, dict):
            raise ProbeError(f"/{path}: HTTP 200 JSON response is not an object")
        status = document.get("status")
        # Arbitrary vendor error text can echo private request data. Recognize
        # this fixed diagnostic without printing any other server-provided text;
        # status 100 alone does not distinguish this from other auth failures.
        status_text = str(status) if type(status) is int else "missing/invalid"
        self.report(f"/{path}: HTTP 200, Withings status {status_text}")
        if type(status) is not int or status != 0:
            detail = ""
            if document.get("error") == "Client certificate is required for this device":
                detail = "; server requires this device's TLS client certificate (--client-cert and --client-key)"
            raise ProbeError(f"/{path}: session exchange rejected (status {status_text}){detail}; offer unknown")
        body = document.get("body")
        if not isinstance(body, dict):
            raise ProbeError(f"/{path}: successful response has no valid body object")
        return body


def lookup(args: argparse.Namespace, secret: str, client: WithingsClient) -> dict:
    nonce = client.post("once", {"action": "get"}).get("once")
    if not isinstance(nonce, str) or not 1 <= len(nonce) <= 31:
        raise ProbeError("/once: invalid challenge; no session request sent")
    body = client.post("session", session_fields(args, secret, nonce))
    syp = body.get("syp")
    if syp is None:
        return {"offered": False}
    if not isinstance(syp, dict):
        raise ProbeError("/session: invalid syp object; offer unknown")
    url, sha1 = syp.get("blc"), syp.get("sha1")
    if url is None and sha1 is None:
        return {"offered": False}
    if (not isinstance(url, str) or not 1 <= len(url) <= 1024
            or any(ord(c) < 32 or ord(c) == 127 for c in url)
            or not isinstance(sha1, str) or not re.fullmatch(r"[a-fA-F0-9]{40}", sha1)):
        raise ProbeError("/session: incomplete or malformed firmware offer")
    try:
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or not parsed.hostname.endswith(".withings.net")
                or parsed.username or parsed.password
                or parsed.port not in (None, 80, 443)):
            raise ValueError("unexpected firmware URL")
    except ValueError as exc:
        raise ProbeError("/session: unexpected firmware URL; not displaying the offer") from exc
    return {"offered": True, "url": url, "sha1": sha1.lower()}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=STOCK_VERSIONS, default="WBS06", help="request profile; WBS03 is WS-30 (default: WBS06)")
    parser.add_argument("--mac", required=True, help="device MAC, with or without separators")
    secrets = parser.add_mutually_exclusive_group()
    secrets.add_argument("--secret", help="raw 16-hex session secret; otherwise prompted without echo")
    secrets.add_argument("--secret-env", help="read the secret from this environment variable instead")
    parser.add_argument("--current-fw", type=integer, help="reported version (defaults: WBS03 921, WBS06 1181, WBS13 1311)")
    parser.add_argument("--mfgid", type=integer, help="manufacturer ID, decimal or 0x-prefixed hex; required for WBS13, otherwise 0")
    parser.add_argument("--feature-mask", type=integer, default=0, help="reported feature mask (default: 0)")
    parser.add_argument("--battery-level", type=int, default=100, help="battery percentage (default: 100)")
    parser.add_argument("--trademark", type=int, choices=(1, 2), default=1, help="Withings=1, Nokia=2 (default: 1)")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"HTTPS hostname, no URL/port (default: {DEFAULT_HOST})")
    parser.add_argument("--ca-file", help="optional PEM CA bundle replacing system trust for a factory-host test")
    parser.add_argument("--client-cert", help="optional PEM client certificate; requires --client-key")
    parser.add_argument("--client-key", help="optional PEM client private key; requires --client-cert")
    parser.add_argument("--timeout", type=float, default=15, help="socket timeout in seconds (default: 15)")
    args = parser.parse_args(argv)
    try:
        args.mac = normalize_mac(args.mac)
    except ValueError as exc:
        parser.error(str(exc))
    if args.model == "WBS13" and args.mfgid is None:
        parser.error("WBS13 requires --mfgid from its probe/DBLIB item 0x0B; do not assume zero")
    args.mfgid = args.mfgid if args.mfgid is not None else 0
    args.current_fw = args.current_fw if args.current_fw is not None else STOCK_VERSIONS[args.model]
    if not 0 <= args.current_fw <= 65535 or not 0 <= args.mfgid <= 0x7fffffff:
        parser.error("firmware must be 0..65535 and manufacturer ID 0..2147483647")
    if not 0 <= args.feature_mask <= 0xffffffff or not 0 <= args.battery_level <= 100:
        parser.error("feature mask must be 0..4294967295 and battery level 0..100")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and greater than zero")
    if bool(args.client_cert) != bool(args.client_key):
        parser.error("--client-cert and --client-key must be supplied together")
    labels = args.host.split(".")
    if len(args.host) > 253 or not all(re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) for label in labels):
        parser.error("host must be a DNS hostname without scheme, path, credentials or port")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        if args.secret_env:
            secret = os.environ.get(args.secret_env, "")
        elif args.secret is not None:
            secret = args.secret
        else:
            secret = getpass.getpass("Raw device session secret (16 hex characters): ")
        if not re.fullmatch(r"[a-fA-F0-9]{16}", secret):
            raise ProbeError("use the raw 16-hex session secret, not the 48-hex encoded UART probe value")
        print(f"{args.model}, firmware {args.current_fw}, manufacturer ID {args.mfgid}, feature mask {args.feature_mask}")
        print(f"Checking https://{args.host}")
        if args.model == "WBS13":
            print("WBS13 requires its factory host, model CA, and device TLS client certificate/key.")
        result = lookup(args, secret, WithingsClient(args))
        if result["offered"]:
            print(f"Firmware URL: {result['url']}")
            print(f"Firmware SHA-1: {result['sha1']}")
        else:
            print("Session accepted; no firmware offer returned for these request values.")
        return 0
    except (ProbeError, OSError, EOFError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
