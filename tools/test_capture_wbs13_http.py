"""Loopback HTTP capture tests using synthetic data; no scale/vendor access."""
import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from capture_wbs13_http import Reader, Responder, Server, Store, load_profile, screen_body

PROFILE = {"ctp": {"goff": 3600, "dst": 0, "ngoff": 3600},
           "ind": {"stp": 0, "fm": 0, "ws": 0}}
PERSON = {"id": 1001, "sn": "TST", "fn": "Test User", "ht": 1.75,
          "agt": 40.25, "sx": 0, "wt": 100.025, "fm": 3,
          "cr": 1793468363, "att": 0, "cs": "2,1,3"}


def request(path, body, headers=b"", chunked=False):
    framing = b"Transfer-Encoding: chunked\r\n" if chunked else f"Content-Length: {len(body)}\r\n".encode()
    return (f"POST {path}?appname=WBS13&appliver=100 HTTP/1.1\r\nHost: capture\r\n".encode()
            + headers + framing + b"\r\n" + body)


def receive(stream):
    first = stream.readline()
    if not first:
        return None
    size = 0
    while True:
        line = stream.readline()
        if line == b"\r\n":
            break
        if line.lower().startswith(b"content-length:"):
            size = int(line.split(b":", 1)[1])
    return int(first.split()[1]), json.loads(stream.read(size))


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.store = Store(Path(self.directory.name) / "capture")
        self.server = Server(("127.0.0.1", 0), self.store, Responder(PROFILE))
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01})
        self.thread.start()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.addCleanup(self.stop)

    def stop(self):
        self.server.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def connect(self):
        sock = socket.create_connection(self.server.server_address, timeout=2)
        return sock, sock.makefile("rb")

    def start_session(self, sock, stream):
        sock.sendall(request("/session", b"action=new&auth=synthetic&hash=synthetic"))
        status, response = receive(stream)
        self.assertEqual(status, 200)
        self.assertNotIn("sp", response["body"])
        self.assertEqual(response["body"]["ind"], PROFILE["ind"])
        self.assertLess(abs(response["body"]["syp"]["utc"] - time.time()), 3)
        return response["body"]["sessionid"]

    def test_persistent_chunked_upload_exact_wire_headers_trailers_and_durable_files(self):
        sock, stream = self.connect()
        with sock, stream:
            token = self.start_session(sock, stream)
            # Metric-only groups, zero user IDs and an unknown field must survive.
            payload = (f'action=batchstore&sessionid={token}&measuregrps='
                       '{"measuregrps":[{"meastime":123,"algo":99,"measures":'
                       '[{"type":11,"value":1234,"unit":0,"position":2}]}]}&extra=keep').encode()
            chunks = b""
            for part in (payload[:11], payload[11:79], payload[79:]):
                chunks += f"{len(part):x};ext=test\r\n".encode() + part + b"\r\n"
            chunks += b"0\r\nX-Trailer: preserved\r\n\r\n"
            raw = request("/measure", chunks, b"X-Same: one\r\nx-same: two\r\n", True)
            sock.sendall(raw)
            self.assertEqual(receive(stream), (200, {"status": 0}))
            self.assertEqual((self.store.path / "000002.request.http").read_bytes(), raw)
            self.assertEqual((self.store.path / "000002.body.bin").read_bytes(), payload)
            response = (self.store.path / "000002.response.http").read_bytes()
            self.assertTrue(response.startswith(b"HTTP/1.1 200 OK\r\n"))
            events = [json.loads(line) for line in (self.store.path / "events.jsonl").read_text().splitlines()]
            item = next(e for e in events if e.get("exchange") == "000002" and e["event"] == "response_prepared")
            self.assertTrue(item["complete"])
            self.assertEqual(item["headers"][1:3], [["X-Same", "one"], ["x-same", "two"]])
            self.assertEqual(item["trailers"], [["X-Trailer", "preserved"]])
            self.assertEqual(item["outcome"], "upload_saved_and_acknowledged")
            for path in self.store.path.iterdir():
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o700)
            sock.sendall(request("/session", f"action=delete&sessionid={token}".encode()))
            self.assertEqual(receive(stream), (200, {"status": 0}))

    def test_no_profile_stops_at_session_but_probe_and_challenge_work(self):
        self.server.responder = Responder(None)
        sock, stream = self.connect()
        with sock, stream:
            sock.sendall(request("/once", b"action=probe"))
            self.assertEqual(receive(stream), (200, {"status": 0}))
            sock.sendall(request("/once", b"action=get"))
            status, response = receive(stream)
            self.assertEqual(status, 200)
            self.assertEqual(len(response["body"]["once"]), 24)
            sock.sendall(request("/session", b"action=new"))
            self.assertEqual(receive(stream)[0], 503)

    def test_incomplete_body_is_saved_exactly_without_success(self):
        sock, stream = self.connect()
        raw = b"POST /measure?appname=WBS13 HTTP/1.1\r\nContent-Length: 20\r\n\r\nshort"
        with sock, stream:
            sock.sendall(raw)
            sock.shutdown(socket.SHUT_WR)
            self.assertEqual(receive(stream)[0], 400)
        self.assertEqual((self.store.path / "000001.request.http").read_bytes(), raw)
        record = next(json.loads(line) for line in (self.store.path / "events.jsonl").read_text().splitlines()
                      if json.loads(line)["event"] == "response_prepared")
        self.assertFalse(record["complete"])

    def test_capture_failure_never_sends_success(self):
        sock, stream = self.connect()
        with sock, stream:
            token = self.start_session(sock, stream)
            with patch.object(self.store, "sync_directory", side_effect=OSError("simulated disk failure")):
                sock.sendall(request("/measure", f"action=batchstore&sessionid={token}".encode()))
                self.assertIsNone(receive(stream))

    def test_keep_queued_and_unknown_endpoint_are_saved_but_rejected(self):
        self.server.responder.keep_queued = True
        sock, stream = self.connect()
        with sock, stream:
            token = self.start_session(sock, stream)
            for path, action in (("/measure", "batchstore"), ("/new-path", "unknown")):
                sock.sendall(request(path, f"action={action}&sessionid={token}".encode()))
                self.assertEqual(receive(stream)[0], 503)

    def test_empty_endpoint_profiles_and_session_isolation(self):
        sock, stream = self.connect()
        with sock, stream:
            token = self.start_session(sock, stream)
            for path, action, body in (
                ("/v2/summary", "getforscale", []),
                ("/v2/screen", "getbydeviceid", {"device": [], "user": []}),
                ("/v2/screen", "getcontentbydeviceid", {"user_screens": []}),
                ("/v2/weather", "getforecast", {}),
                ("/v2/measure", "getlastupdate", {"devices": []}),
                ("/v2/feature", "getbydevice", {"device_features": [], "user_features": []}),
            ):
                sock.sendall(request(path, f"action={action}&sessionid={token}".encode()))
                self.assertEqual(receive(stream), (200, {"status": 0, "body": body}))
            r = Reader(io.BytesIO(request("/measure", f"action=batchstore&sessionid={token}".encode())))
            r.read()
            self.assertEqual(self.server.responder.reply(r, "different-peer")[0], 403)

    def test_ambiguous_or_oversized_requests_do_not_acknowledge(self):
        for headers in (b"Content-Length: 1\r\nTransfer-Encoding: chunked\r\n",
                        b"Content-Length: 1\r\nContent-Length: 1\r\n",
                        b"Content-Length: 9999999999\r\n",
                        b"Transfer-Encoding: gzip\r\n",
                        b"Expect: 100-continue\r\n"):
            sock, stream = self.connect()
            with sock, stream:
                sock.sendall(b"POST /measure?appname=WBS13 HTTP/1.1\r\n" + headers + b"\r\n")
                self.assertEqual(receive(stream)[0], 400)

    def test_profile_cannot_replay_clock_firmware_offer_or_account_credentials(self):
        path = Path(self.directory.name) / "profile.json"
        path.write_text(json.dumps(PROFILE))
        self.assertEqual(load_profile(path), PROFILE)
        for extra in ("syp", "sp", "sessionid"):
            path.write_text(json.dumps({**PROFILE, extra: {}}))
            with self.assertRaises(ValueError):
                load_profile(path)
        path.write_text(json.dumps({"ctp": PROFILE["ctp"], "ind": {"fm": 0}}))
        with self.assertRaises(ValueError):
            load_profile(path)

    def test_roster_and_matching_screens_are_served_and_saved_without_account_setup(self):
        path = Path(self.directory.name) / "profile.json"
        path.write_text(json.dumps({**PROFILE, "sp": {"users": [PERSON]}}))
        profile = load_profile(path)
        self.server.responder = Responder(profile)
        sock, stream = self.connect()
        with sock, stream:
            sock.sendall(request("/session", b"action=new&auth=synthetic&hash=synthetic"))
            status, response = receive(stream)
            self.assertEqual(status, 200)
            body = response["body"]
            self.assertEqual(body["sp"], {"users": [PERSON]})
            self.assertEqual(body["ind"], PROFILE["ind"])
            self.assertEqual(set(body["syp"]), {"utc"})
            self.assertLess(abs(body["syp"]["utc"] - time.time()), 3)
            token = body["sessionid"]
            sock.sendall(request("/v2/screen", f"action=getbydeviceid&sessionid={token}".encode()))
            status, response = receive(stream)
            self.assertEqual(status, 200)
            self.assertEqual(response["body"], {"device": [], "user": [{
                "userid": PERSON["id"], "screens": [
                    {"id": 2, "src": 1, "embid": 2, "rk": 1},
                    {"id": 1, "src": 1, "embid": 1, "rk": 2},
                    {"id": 3, "src": 1, "embid": 3, "rk": 3},
                ]}]})
            saved = (self.store.path / "000002.response.http").read_bytes().split(b"\r\n\r\n", 1)[1]
            self.assertEqual(json.loads(saved), response)

    def test_roster_validation_rejects_overflow_duplicates_and_unknown_fields(self):
        path = Path(self.directory.name) / "profile.json"
        for changes in ({"id": 0}, {"id": True}, {"sn": "TOOLONG"}, {"fn": "X" * 17},
                        {"wt": float("nan")}, {"ht": 186}, {"agt": 0}, {"sx": 2},
                        {"fm": -1}, {"cr": 2**32}, {"att": -1},
                        {"cs": "1,1"}, {"cs": "1,3,"}, {"cs": "1,19"},
                        {"cs": "1," * 20 + "3"}, {"ft": [48]}):
            with self.subTest(changes=changes):
                path.write_text(json.dumps({**PROFILE, "sp": {"users": [{**PERSON, **changes}]}}))
                with self.assertRaises(ValueError):
                    load_profile(path)
        for sp in ({"users": [PERSON, PERSON]}, {"users": [dict(PERSON, id=i+1) for i in range(9)]},
                   {"users": [PERSON], "accountids": [1]}, {"users": "bad"}, {"users": [None]}):
            path.write_text(json.dumps({**PROFILE, "sp": sp}))
            with self.assertRaises(ValueError):
                load_profile(path)

    def test_eight_users_keep_independent_screen_selections_and_empty_roster_works(self):
        profile = copy.deepcopy(PROFILE)
        profile["sp"] = {"users": [dict(PERSON, id=i+1, cs="1" if i % 2 else "3") for i in range(8)]}
        path = Path(self.directory.name) / "profile.json"
        path.write_text(json.dumps(profile))
        users = screen_body(load_profile(path))["user"]
        self.assertEqual([u["userid"] for u in users], list(range(1, 9)))
        self.assertEqual([u["screens"][0]["embid"] for u in users], [3, 1] * 4)
        profile["sp"]["users"] = []
        path.write_text(json.dumps(profile))
        self.assertEqual(screen_body(load_profile(path)), {"device": [], "user": []})

    def test_timeout_retains_partial_header_or_chunk_bytes(self):
        class TimedOut(io.BytesIO):
            def read(self, size=-1):
                result = super().read(size)
                if not result:
                    raise TimeoutError("synthetic timeout")
                return result

            read1 = read

        for raw in (b"POST /once?appname=WBS13 HTTP/1.1\r\nX-Partial: value",
                    b"POST /measure?appname=WBS13 HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n20\r\npartial"):
            r = Reader(TimedOut(raw))
            with self.assertRaises(TimeoutError):
                r.read()
            self.assertEqual(r.raw, raw)
            self.assertFalse(r.complete)


if __name__ == "__main__":
    unittest.main()
