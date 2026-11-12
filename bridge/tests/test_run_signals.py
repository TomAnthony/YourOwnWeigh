"""Ctrl-C handling in run() where the loop has no add_signal_handler (Windows)."""

import asyncio
import signal
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from yow_bridge import __main__ as cli


class SignalFallback(unittest.IsolatedAsyncioTestCase):
    async def start(self, application):
        """Start run() with the Proactor-style loop; return it and the Ctrl-C handler."""
        loop = asyncio.get_running_loop()
        installed = {}

        async def network(*_):
            await asyncio.Event().wait()

        self.enterContext(patch.object(loop, "add_signal_handler", side_effect=NotImplementedError))
        self.enterContext(patch.object(cli.signal, "signal", side_effect=installed.__setitem__))
        self.enterContext(patch.object(cli, "Application", return_value=application))
        self.enterContext(patch.object(cli, "network", network))
        running = asyncio.create_task(
            cli.run(SimpleNamespace(state_dir=None, simulate=True), pairing=None)
        )
        await asyncio.sleep(0)
        self.assertEqual(set(installed), {signal.SIGINT, signal.SIGTERM})
        return running, installed[signal.SIGINT]

    async def test_ctrl_c_stops_an_idle_bridge(self):
        application = SimpleNamespace(task=None, active=None, session=None)
        running, ctrl_c = await self.start(application)
        ctrl_c(signal.SIGINT, None)
        await asyncio.wait_for(running, 2)

    async def test_ctrl_c_does_not_stop_or_cancel_an_ota_in_flight(self):
        release = asyncio.Event()

        async def flash():
            await release.wait()
            return "flashed"

        firmware = asyncio.create_task(flash())
        application = SimpleNamespace(
            task=firmware,
            active={"name": "firmware.install"},
            session=SimpleNamespace(ota_started=True, transport=None),
        )
        running, ctrl_c = await self.start(application)
        with self.assertLogs(cli.LOG, "WARNING") as logs:
            ctrl_c(signal.SIGINT, None)
            await asyncio.sleep(0.1)
        self.assertIn("OTA is in progress", logs.output[0])
        self.assertFalse(running.done())
        self.assertFalse(firmware.done())

        release.set()
        self.assertEqual(await firmware, "flashed")
        ctrl_c(signal.SIGINT, None)  # once the transfer ends, Ctrl-C stops as usual
        await asyncio.wait_for(running, 2)
        self.assertFalse(firmware.cancelled())


if __name__ == "__main__":
    unittest.main()
