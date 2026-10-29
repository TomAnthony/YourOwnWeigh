import asyncio
import tempfile
import unittest
import uuid
from unittest.mock import patch
from yow_bridge.application import Application


def command(name, parameters=None, **extra):
    return dict(
        protocol="yow.bridge",
        version=1,
        kind="command",
        id=uuid.uuid4().hex,
        operationId=uuid.uuid4().hex,
        name=name,
        parameters=parameters or {},
        **extra,
    )


class Commands(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Application(self.tmp.name, simulate=True)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def run_command(self, c):
        await self.app.accept(c)
        if self.app.task:
            await self.app.task
        return self.app.history.get(c["id"], {}).get("event")

    async def connected(self):
        await self.run_command(
            command("device.scan.start", dict(model="WBS06", durationSeconds=1))
        )
        await self.run_command(command("device.connect", deviceId="demo-scale"))
        await self.run_command(
            command(
                "device.probe",
                deviceId="demo-scale",
                connectionGeneration=self.app.generation,
            )
        )

    async def test_connect_stops_scan_and_waits_for_radio_cleanup(self):
        from yow_bridge import simulation

        discovered, cleaned = asyncio.Event(), asyncio.Event()
        original_session = simulation.Session

        async def scanning(backend, seconds, found):
            found(dict(
                deviceId="nearby", name="Test WS-30",
                modelCandidate="WBS03", presence="seen",
            ))
            discovered.set()
            await backend.stop.wait()
            await asyncio.sleep(0)  # Model asynchronous radio cleanup.
            cleaned.set()

        def session(model):
            self.assertTrue(cleaned.is_set(), "Connection started before scan cleanup")
            return original_session(model)

        with (
            patch.object(simulation.Backend, "scan", scanning),
            patch.object(simulation, "Session", session),
        ):
            scan = command("device.scan.start", dict(model="WBS03", durationSeconds=15))
            await self.app.accept(scan)
            await discovered.wait()
            scan_task = self.app.task
            # An unrelated or invalid request cannot stop the running scan.
            for request in (
                command("firmware.generate", dict(model="WBS03")),
                command("device.connect", deviceId="unknown"),
            ):
                await self.app.accept(request)
                self.assertIs(self.app.task, scan_task)
                self.assertFalse(self.app.transport_backend.stop.is_set())
            connect = command("device.connect", deviceId="nearby")
            result = await self.run_command(connect)
            self.assertTrue(scan_task.done())
            self.assertEqual(self.app.history[scan["id"]]["event"]["kind"], "result")
            self.assertEqual(result["kind"], "result")
            self.assertTrue(self.app.connected)
            self.assertEqual(self.app.generation, 1)
            await self.app.accept(connect)  # A retry must not open it twice.
            self.assertEqual(self.app.generation, 1)

    async def test_duplicate_and_stale_connection(self):
        await self.connected()
        c = command(
            "device.complete_setup", deviceId="demo-scale", connectionGeneration=1
        )
        result = await self.run_command(c)
        self.assertEqual(result["kind"], "result")
        await self.app.accept(c)
        self.assertEqual(len([x for x in self.app.history if x == c["id"]]), 1)
        await self.app.accept(
            command(
                "device.set_server",
                dict(host="example.net", transport="https"),
                deviceId="demo-scale",
                connectionGeneration=0,
            )
        )
        events = []
        while not self.app.outgoing.empty():
            events.append(self.app.outgoing.get_nowait())
        self.assertIn("STALE_CONNECTION", events[-1]["error"]["message"])
        self.assertNotIn("0123456789abcdef", str(self.app.snapshot()))

    async def test_upload_rejects_out_of_order(self):
        c = command(
            "artifact.begin",
            dict(model="WBS06", filename="test.bin", size=100, sha256="0" * 64),
        )
        result = await self.run_command(c)
        transfer = result["result"]["transferId"]
        r = await self.run_command(
            command(
                "artifact.chunk", dict(transferId=transfer, offset=1, dataBase64="AA==")
            )
        )
        self.assertEqual(r["kind"], "error")

    async def test_private_reply_is_routed(self):
        await self.connected()
        c = command(
            "device.reveal_secret",
            deviceId="demo-scale",
            connectionGeneration=1,
            replyTo="tab1",
        )
        result = await self.run_command(c)
        self.assertEqual(result["replyTo"], "tab1")
        self.assertEqual(result["result"]["secret"], "0123456789abcdef")
        self.assertNotIn("0123456789abcdef", str(self.app.snapshot()))

    async def test_unrecognised_identity_can_reveal_secret_only_in_private_reply(self):
        await self.connected()
        self.app.session.identity["supported"] = False
        self.app.session.identity["name"] = "Other Body"
        public = self.app.session.public_identity()
        self.assertFalse(public["supported"])
        self.assertFalse(public["capabilities"]["ota"])
        self.assertNotIn("secret", public)
        request = command(
            "device.reveal_secret",
            deviceId="demo-scale",
            connectionGeneration=1,
            replyTo="tab1",
        )
        result = await self.run_command(request)
        self.assertEqual(result["kind"], "result")
        self.assertEqual(result["result"]["secret"], "0123456789abcdef")
        self.assertNotIn("0123456789abcdef", str(self.app.snapshot()))

    async def test_enrollment_keeps_identity_when_optional_read_fails(self):
        from yow_bridge.models.protocol import ProtocolError

        await self.connected()

        async def fail():
            raise ProtocolError("unconfigured")

        self.app.session.read_server = fail
        result = await self.run_command(
            command(
                "device.enroll",
                {"approved": True},
                deviceId="demo-scale",
                connectionGeneration=1,
            )
        )
        self.assertEqual(result["kind"], "result")
        self.assertEqual(result["result"]["device"]["model"], "WBS06")
        self.assertIsInstance(result["result"]["device"]["captured_at"], int)
        self.assertFalse(result["result"]["configuration"]["server"]["available"])
        self.assertIsNone(result["result"]["device"]["owner_host"])

    def test_command_contract_matches_dispatcher(self):
        import json
        from pathlib import Path
        from yow_bridge.application import COMMANDS

        document = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "contracts/bridge/v1/commands.json"
            ).read_text()
        )
        self.assertEqual(set(document), COMMANDS)


class ProgressLogging(unittest.TestCase):
    def test_transfer_log_is_throttled_to_five_seconds(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as directory:
            app = Application(directory, simulate=True)
            c = command("firmware.install")
            with patch("yow_bridge.application.time.monotonic") as clock:
                with self.assertLogs("yow", level="INFO") as logs:
                    for when, stage, done in [(10, "starting", 0), (11, "transferring", 10), (14, "transferring", 40), (15, "transferring", 50), (19, "transferring", 80), (20, "transferring", 90), (21, "transfer_complete", 100)]:
                        clock.return_value = when
                        app.progress(c, stage, done, 100)
            self.assertEqual(len(logs.output), 4)
            self.assertIn("50.0%", logs.output[1])
            self.assertIn("90.0%", logs.output[2])
            self.assertIn("100.0%", logs.output[3])
