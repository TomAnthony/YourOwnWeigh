"""WPP service selection and notification setup without Bluetooth hardware."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from yow_bridge.transports import ble


class BLETests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_and_identity_only_services_use_their_own_characteristic(self):
        for service_uuid, characteristic_uuid in ble.WPP_SERVICES:
            with self.subTest(service=service_uuid):
                characteristic = SimpleNamespace(uuid=characteristic_uuid)
                service = SimpleNamespace(get_characteristic=lambda uuid:
                    characteristic if uuid == characteristic_uuid else None)
                services = SimpleNamespace(get_service=lambda uuid:
                    service if uuid == service_uuid else None)
                client = SimpleNamespace(
                    services=services, mtu_size=185, is_connected=True,
                    connect=AsyncMock(), disconnect=AsyncMock(), start_notify=AsyncMock(),
                    write_gatt_char=AsyncMock(),
                )
                backend = ble.Backend()
                device = object()
                backend.devices["scale"] = device
                received = []
                with patch.object(ble.sys, "platform", "darwin"), patch.object(
                    ble, "BleakClient", return_value=client
                ) as factory:
                    transport = await backend.connect("scale", received.append, lambda: None)
                self.assertIs(factory.call_args.args[0], device)
                self.assertIs(transport.characteristic, characteristic)
                self.assertEqual(transport.identity_only, service_uuid != ble.SERVICE)
                self.assertEqual(transport.wpp_profile, {
                    ble.SERVICE: "WBS06",
                    ble.IDENTITY_SERVICE: "WBS13",
                    ble.WBS05_SERVICE: "WBS05",
                    ble.WBS04_SERVICE: "WBS04",
                }[service_uuid])
                self.assertEqual(transport.max_write, 182)
                args = client.start_notify.await_args.args
                self.assertIs(args[0], characteristic)
                args[1](characteristic, bytearray(b"reply"))
                self.assertEqual(received, [b"reply"])
                await transport.write(b"probe")
                client.write_gatt_char.assert_awaited_once_with(characteristic, b"probe", response=True)
                await transport.disconnect()
                client.disconnect.assert_awaited_once()

    async def test_characteristic_from_another_service_is_not_accepted(self):
        # A familiar characteristic under an unrelated service is insufficient.
        client = SimpleNamespace(
            services=SimpleNamespace(get_service=lambda _: None,
                                     get_characteristic=lambda _: object()),
            is_connected=True, connect=AsyncMock(), disconnect=AsyncMock(),
            start_notify=AsyncMock(),
        )
        backend = ble.Backend()
        backend.devices["scale"] = object()
        with patch.object(ble.sys, "platform", "darwin"), patch.object(
            ble, "BleakClient", return_value=client
        ):
            with self.assertRaisesRegex(ValueError, "Withings WPP service"):
                await backend.connect("scale", lambda _: None, lambda: None)
        client.disconnect.assert_awaited_once()
        client.start_notify.assert_not_called()


def wbs13_client(**overrides):
    """A fake WinRT client exposing only the WBS13 WPP service."""
    characteristic = SimpleNamespace(uuid=ble.IDENTITY_CHARACTERISTIC)
    service = SimpleNamespace(get_characteristic=lambda uuid:
        characteristic if uuid == ble.IDENTITY_CHARACTERISTIC else None)
    fields = dict(
        services=SimpleNamespace(get_service=lambda uuid:
            service if uuid == ble.IDENTITY_SERVICE else None),
        mtu_size=185, is_connected=True, connect=AsyncMock(), disconnect=AsyncMock(),
        start_notify=AsyncMock(), pair=AsyncMock(return_value=None),
        write_gatt_char=AsyncMock(),
    )
    fields.update(overrides)
    return SimpleNamespace(**fields), characteristic


class LateMTUClient(SimpleNamespace):
    """WinRT reports the default ATT MTU until the exchange completes."""
    reads = 0

    @property
    def mtu_size(self):
        self.reads += 1
        return 23 if self.reads < 3 else 185


class WindowsBLETests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, *clients):
        backend = ble.Backend()
        backend.devices["scale"] = object()
        with patch.object(ble.sys, "platform", "win32"), patch.object(
            ble, "BleakClient", side_effect=list(clients)
        ) as factory:
            transport = await backend.connect("scale", lambda _: None, lambda: None)
        return transport, factory

    async def test_discovers_only_wpp_services(self):
        # Full enumeration fails inside WinRT on another WBS13 service.
        client, characteristic = wbs13_client()
        transport, factory = await self.connect(client)
        self.assertEqual(factory.call_args.kwargs["services"],
                         [service for service, _ in ble.WPP_SERVICES])
        self.assertNotIn("winrt", factory.call_args.kwargs)
        self.assertIs(transport.characteristic, characteristic)
        self.assertEqual(transport.wpp_profile, "WBS13")

    async def test_waits_for_negotiated_mtu(self):
        client, _ = wbs13_client()
        late = LateMTUClient(**{k: v for k, v in vars(client).items() if k != "mtu_size"})
        transport, _ = await self.connect(late)
        self.assertEqual(transport.max_write, 182)
        self.assertGreaterEqual(late.reads, 3)

    async def test_rediscovers_uncached_when_cache_lacks_wpp(self):
        stale = SimpleNamespace(
            services=SimpleNamespace(get_service=lambda _: None),
            is_connected=True, connect=AsyncMock(), disconnect=AsyncMock(),
        )
        fresh, characteristic = wbs13_client()
        transport, factory = await self.connect(stale, fresh)
        stale.disconnect.assert_awaited_once()
        self.assertEqual(factory.call_args.kwargs["winrt"], {"use_cached_services": False})
        self.assertIs(transport.characteristic, characteristic)

    async def test_rediscovery_does_not_report_retired_client_disconnect(self):
        # Disconnecting the cached client fires its callback, as Bleak does;
        # that must not reach the session, now or late, while the replacement
        # client's own disconnects still must.
        stale = SimpleNamespace(
            services=SimpleNamespace(get_service=lambda _: None),
            is_connected=True, connect=AsyncMock(),
        )
        stale.disconnect = AsyncMock(side_effect=lambda: stale.callback(stale))
        fresh, _ = wbs13_client()
        clients = iter([stale, fresh])

        def factory(device, disconnected_callback, **_):
            client = next(clients)
            client.callback = disconnected_callback
            return client

        reported = []
        backend = ble.Backend()
        backend.devices["scale"] = object()
        with patch.object(ble.sys, "platform", "win32"), patch.object(
            ble, "BleakClient", side_effect=factory
        ):
            await backend.connect("scale", lambda _: None, lambda: reported.append(1))
        stale.disconnect.assert_awaited_once()
        self.assertEqual(reported, [])
        stale.callback(stale)  # a late callback from the retired client
        self.assertEqual(reported, [])
        fresh.callback(fresh)
        self.assertEqual(reported, [1])

    async def test_interrupted_retirement_still_disconnects_the_cached_client(self):
        # Cancelled (or failed) mid-disconnect, the cached client may still be
        # connected; the connect cleanup must retry rather than leak it.
        stale = SimpleNamespace(
            services=SimpleNamespace(get_service=lambda _: None),
            is_connected=True, connect=AsyncMock(),
            disconnect=AsyncMock(side_effect=[asyncio.CancelledError(), None]),
        )
        with self.assertRaises(asyncio.CancelledError):
            await self.connect(stale)
        self.assertEqual(stale.disconnect.await_count, 2)

    async def test_unanswered_rediscovery_explains_setup_mode(self):
        stale = SimpleNamespace(
            services=SimpleNamespace(get_service=lambda _: None),
            is_connected=True, connect=AsyncMock(), disconnect=AsyncMock(),
        )
        gone, _ = wbs13_client(connect=AsyncMock(side_effect=OSError(-2147024874, "bad command")))
        with self.assertRaisesRegex(ValueError, "setup mode"):
            await self.connect(stale, gone)

    async def test_pairs_after_insufficient_authentication(self):
        client, characteristic = wbs13_client(
            start_notify=AsyncMock(side_effect=[Exception("Insufficient Authentication"), None]))
        transport, _ = await self.connect(client)
        client.pair.assert_awaited_once()
        self.assertEqual(client.start_notify.await_count, 2)
        self.assertIs(transport.characteristic, characteristic)

    async def test_pair_failure_is_reported(self):
        # Bleak >= 1.0 raises on failure; a None return is success.
        client, _ = wbs13_client(
            start_notify=AsyncMock(side_effect=Exception("Insufficient Authentication")),
            pair=AsyncMock(side_effect=Exception("Could not pair")))
        with self.assertRaisesRegex(ValueError, "could not pair"):
            await self.connect(client)
        client.disconnect.assert_awaited()


class WindowsBackendSelectionTests(unittest.TestCase):
    def test_ble_models_use_bleak_and_classic_models_are_refused(self):
        from yow_bridge import transports
        from yow_bridge.models.registry import MODELS
        with patch.object(transports.sys, "platform", "win32"):
            for model, spec in MODELS.items():
                with self.subTest(model=model):
                    if spec.transport == "ble":
                        self.assertIsInstance(transports.backend(model), ble.Backend)
                    else:
                        with self.assertRaisesRegex(RuntimeError, "Bluetooth LE"):
                            transports.backend(model)
