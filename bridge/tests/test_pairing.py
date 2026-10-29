"""Exercise the CLI's HTTP/WebSocket requests without Bluetooth or cloud state."""

import asyncio
import json
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

from websockets.asyncio.server import serve

from yow_bridge import USER_AGENT
from yow_bridge.__main__ import exchange, network


class Pairing(unittest.TestCase):
    def setUp(self):
        owner = self
        self.status = 200
        self.body = json.dumps(
            {"credential": "test-credential", "helperId": "test-helper"}
        ).encode()
        self.received = None

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.received = (
                    self.path,
                    self.headers,
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
                # Reproduce the observed edge behavior: default urllib traffic
                # never reaches the pairing service, regardless of token age.
                if self.headers.get("User-Agent", "").startswith("Python-urllib/"):
                    status, body = 403, b"error code: 1010\n"
                else:
                    status, body = owner.status, owner.body
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.invitation = {"version": 1, "server": self.origin, "token": "a" * 64}

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()

    def test_exchange_uses_product_identity_and_preserves_invitation(self):
        result = exchange(self.invitation)
        self.assertEqual(
            result,
            {
                "server": self.origin,
                "credential": "test-credential",
                "helperId": "test-helper",
            },
        )
        path, headers, body = self.received
        self.assertEqual(path, "/api/bridge/exchange")
        self.assertEqual(headers["User-Agent"], USER_AGENT)
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertEqual(body["token"], self.invitation["token"])
        self.assertRegex(body["attemptId"], r"^[a-f0-9]{32}$")

    def test_cloudflare_block_is_not_reported_as_expired(self):
        self.status, self.body = 403, b"error code: 1010\n"
        with self.assertRaisesRegex(ValueError, r"Cloudflare blocked.*403/1010"):
            exchange(self.invitation)

    def test_pairing_failures_are_distinct_and_do_not_echo_body(self):
        self.body = b"arbitrary upstream body containing private credentials"
        for status, expected in (
            (401, "Invitation is invalid, expired, or already used"),
            (403, "Server or proxy refused pairing"),
            (409, "A bridge is already paired"),
            (429, "Too many pairing attempts"),
            (502, "Pairing request failed (HTTP 502)"),
        ):
            with self.subTest(status=status):
                self.status = status
                with self.assertRaises(ValueError) as raised:
                    exchange(self.invitation)
                self.assertIn(expected, str(raised.exception))
                self.assertNotIn("private credentials", str(raised.exception))


class WebSocketIdentity(unittest.IsolatedAsyncioTestCase):
    async def test_rapid_disconnects_back_off_despite_successful_upgrades(self):
        stopped = asyncio.Event()
        attempts = []

        async def handler(socket):
            attempts.append(time.monotonic())
            await socket.recv()
            if len(attempts) < 3:
                await socket.close(1011, "Temporary server failure")
            else:
                stopped.set()

        application = SimpleNamespace(snapshot=lambda: {}, outgoing=asyncio.Queue())
        async with serve(handler, "127.0.0.1", 0) as server:
            pairing = {"server": f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}",
                       "credential": "test-credential"}
            with self.assertLogs("yow", level="WARNING"):
                await asyncio.wait_for(network(application, pairing, stopped), 8)
        self.assertEqual(len(attempts), 3)
        self.assertGreaterEqual(attempts[2] - attempts[1], 1.8)

    async def test_protocol_rejection_stops_without_retry_or_state_loss(self):
        attempts = 0
        state = {"activeOperation": {"name": "firmware.install", "state": "running"}}

        async def handler(socket):
            nonlocal attempts
            attempts += 1
            await socket.recv()
            await socket.close(1002, "Unsupported protocol")

        application = SimpleNamespace(snapshot=lambda: dict(state), outgoing=asyncio.Queue())
        async with serve(handler, "127.0.0.1", 0) as server:
            pairing = {"server": f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}",
                       "credential": "test-credential"}
            with self.assertLogs("yow", level="ERROR") as logs:
                await asyncio.wait_for(network(application, pairing, asyncio.Event()), 3)
        self.assertEqual(attempts, 1)
        self.assertEqual(state["activeOperation"]["state"], "running")
        self.assertIn("matching releases", "\n".join(logs.output))
        self.assertIn("--resume", "\n".join(logs.output))

    async def test_reconnect_retries_conflict_and_keeps_running_operation(self):
        stopped = asyncio.Event()
        state = {"activeOperation": {"name": "firmware.install", "state": "running", "bytesDone": 0}}
        outgoing = asyncio.Queue()
        hellos, runs = [], []
        attempts = 0
        work = None

        async def local_transfer():
            await asyncio.sleep(0.15)
            state["activeOperation"] = {"name": "firmware.install", "state": "complete", "result": {"transferred": True}}
            await outgoing.put({"kind": "snapshot", "snapshot": dict(state)})

        def handshake(connection, request):
            nonlocal attempts
            attempts += 1
            runs.append(request.headers["X-YOW-Bridge-Run"])
            if attempts == 2:
                return connection.respond(409, "Previous socket still closing")

        async def handler(socket):
            nonlocal work
            hellos.append(json.loads(await socket.recv()))
            if len(hellos) == 1:
                work = asyncio.create_task(local_transfer())
                await socket.close(1011, "Synthetic network failure")
            else:
                stopped.set()

        application = SimpleNamespace(snapshot=lambda: dict(state), outgoing=outgoing)
        async with serve(handler, "127.0.0.1", 0, process_request=handshake) as server:
            port = server.sockets[0].getsockname()[1]
            pairing = {"server": f"http://127.0.0.1:{port}", "credential": "test-credential"}
            with self.assertLogs("yow", level="WARNING") as logs:
                await asyncio.wait_for(network(application, pairing, stopped), 8)
            await work
        self.assertEqual(len(hellos), 2)
        self.assertEqual(hellos[1]["snapshot"]["activeOperation"]["state"], "complete")
        self.assertEqual(len(set(runs)), 1)
        self.assertIn("HTTP 409", "\n".join(logs.output))
        self.assertNotIn("pairing expired", "\n".join(logs.output))

    async def test_product_header_and_authenticated_hello(self):
        observed = {}
        stopped = asyncio.Event()

        async def handler(socket):
            observed["path"] = socket.request.path
            observed["headers"] = socket.request.headers
            observed["hello"] = json.loads(await socket.recv())
            stopped.set()

        application = SimpleNamespace(snapshot=lambda: {}, outgoing=asyncio.Queue())
        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            pairing = {
                "server": f"http://127.0.0.1:{port}",
                "credential": "test-credential",
            }
            await asyncio.wait_for(network(application, pairing, stopped), 3)
        self.assertEqual(observed["path"], "/api/bridge/socket")
        self.assertEqual(observed["headers"]["User-Agent"], USER_AGENT)
        self.assertEqual(observed["headers"]["Authorization"], "Bearer test-credential")
        self.assertEqual(observed["hello"]["kind"], "hello")

    async def test_forbidden_websocket_does_not_blame_pairing_expiry(self):
        def reject(connection, request):
            return connection.respond(403, "Forbidden")

        application = SimpleNamespace(snapshot=lambda: {}, outgoing=asyncio.Queue())
        async with serve(
            lambda socket: None, "127.0.0.1", 0, process_request=reject
        ) as server:
            port = server.sockets[0].getsockname()[1]
            pairing = {
                "server": f"http://127.0.0.1:{port}",
                "credential": "test-credential",
            }
            with self.assertLogs("yow", level="ERROR") as logs:
                await asyncio.wait_for(
                    network(application, pairing, asyncio.Event()), 3
                )
        self.assertIn("Server or proxy refused", logs.output[0])
        self.assertNotIn("pairing expired", logs.output[0])
