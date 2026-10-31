"""WPP service selection and notification setup without Bluetooth hardware."""

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
                self.assertEqual(transport.identity_only, service_uuid == ble.IDENTITY_SERVICE)
                self.assertEqual(transport.wpp_profile, "WBS13" if service_uuid == ble.IDENTITY_SERVICE else "WBS06")
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
