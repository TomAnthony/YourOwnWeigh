import unittest
from unittest.mock import AsyncMock

from yow_bridge.models.protocol import ProtocolError
from yow_bridge.models.session import ScaleSession


class SecondaryWifiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.session = ScaleSession("WBS03", None)
        self.session.identity = dict(firmwareVersion=1103, secret="0123456789abcdef")
        self.primary_record = b"\x07PRIMARY\x0btest-key-01"
        self.session._read_wifi_record = AsyncMock(return_value=self.primary_record)
        self.session.owner = AsyncMock()

    async def test_wpa2_reference_vector_and_no_credentials_in_result(self):
        # IEEE/password is a published PBKDF2 WPA test vector, independent
        # of the implementation's own hashlib calculation.
        expected = b"f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e"
        self.session.owner.side_effect = [b"\x01\x11\x00\x04IEEE", b"\x01\x10\x00\x04IEEE"]
        result = await self.session.set_secondary_wifi("IEEE", "password")
        self.assertEqual(self.session.owner.call_args_list[0].args[0], b"\x01\x11\x04IEEE"+expected)
        self.assertEqual(result["joinStatus"], "not-tested")
        self.assertTrue(result["primaryPreserved"])
        self.assertNotIn("password", str(result))
        self.assertNotIn("test-key-01", str(result))
        self.assertNotIn(expected.decode(), str(result))

    async def test_other_firmware_and_model_cannot_write(self):
        for model, version in [("WBS03", 102), ("WBS03", 1104), ("WBS02", 1103), ("WBS13", 103)]:
            session = ScaleSession(model, None)
            session.identity = dict(firmwareVersion=version, secret="0123456789abcdef")
            session.owner = AsyncMock()
            with self.assertRaises(ProtocolError):
                await session.set_secondary_wifi("IEEE", "password")
            self.assertEqual(await session.read_secondary_wifi(), dict(supported=False))
            session.owner.assert_not_called()

    async def test_reject_invalid_credentials_before_writing(self):
        for ssid, key in [("", "password"), ("x"*33, "password"), ("a\0b", "password"),
                          ("IEEE", "short"), ("IEEE", "x"*64), ("IEEE", "pássword"),
                          ("PRIMARY", "password")]:
            with self.subTest(ssid=ssid), self.assertRaises(ValueError):
                await self.session.set_secondary_wifi(ssid, key)
        self.session.owner.assert_not_called()

    async def test_unset_and_bad_readback(self):
        self.session.owner.return_value = b"\x01\x10\x02\x00"
        self.assertTrue((await self.session.read_secondary_wifi())["unset"])
        for reply in (b"", b"\x01\x10\x00\x00", b"\x01\x10\x03\x00",
                      b"\x01\x10\x00\x04IEEEkey", b"\x01\x10\x00\x01\xff"):
            self.session.owner.return_value = reply
            with self.assertRaises(ProtocolError):
                await self.session.read_secondary_wifi()

    async def test_failed_write_is_not_replayed(self):
        self.session.owner.return_value = b"\x01\x11\x03\x00"
        with self.assertRaises(ProtocolError):
            await self.session.set_secondary_wifi("IEEE", "password")
        self.assertEqual(self.session.owner.call_count, 1)

    async def test_primary_change_is_reported(self):
        self.session.owner.side_effect = [b"\x01\x11\x00\x04IEEE", b"\x01\x10\x00\x04IEEE"]
        self.session._read_wifi_record.side_effect = [self.primary_record, b"\x07PRIMARY\x0btest-key-02"]
        with self.assertRaisesRegex(ProtocolError, "readback"):
            await self.session.set_secondary_wifi("IEEE", "password")

    async def test_clear_requires_readback(self):
        self.session.owner.side_effect = [b"\x01\x11\x00\x00", b"\x01\x10\x02\x00"]
        self.assertTrue((await self.session.clear_secondary_wifi())["unset"])
        self.assertEqual(self.session.owner.call_args_list[0].args[0], b"\x01\x11\x00")
        self.session.owner.side_effect = [b"\x01\x11\x00\x00", b"\x01\x10\x00\x04IEEE"]
        with self.assertRaises(ProtocolError):
            await self.session.clear_secondary_wifi()


if __name__ == "__main__":
    unittest.main()
