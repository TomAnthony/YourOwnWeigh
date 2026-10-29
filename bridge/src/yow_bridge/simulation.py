"""Explicit UI demonstration backend. Never opens Bluetooth or writes hardware."""

import asyncio

from .models.session import ScaleSession, timestamp


class Backend:
    def __init__(self, model):
        if model not in ("WBS06", "WBS03"):
            raise ValueError("Unsupported model")
        self.model, self.stop = model, asyncio.Event()

    async def scan(self, seconds, found):
        await asyncio.sleep(0.1)
        found(
            dict(
                deviceId="demo-scale",
                name="Demo Body" if self.model == "WBS06" else "Demo WS-30",
                rssi=-45,
                modelCandidate=self.model,
                presence="seen",
            )
        )


class Session(ScaleSession):
    def __init__(self, model):
        super().__init__(model, self)
        self.server = dict(supported=True, unset=True)
        self.ssid = "Demo Wi-Fi"

    async def probe(self):
        self.identity = dict(
            name="Body" if self.model == "WBS06" else "WS-30",
            model=self.model,
            mac="020000000006" if self.model == "WBS06" else "020000000003",
            secret="0123456789abcdef",
            hardwareVersion=0xFFFFFF,
            firmwareVersion=127 if self.model == "WBS06" else 102,
            bootloaderVersion=4 if self.model == "WBS06" else 15,
            rescueVersion=0xFFFFFF,
            identifier="simulation",
            observedAt=timestamp(),
        )
        return self.public_identity()

    async def disconnect(self):
        pass

    async def complete_setup(self):
        return dict(acknowledged=True, expectedDisconnect=True)

    async def read_server(self):
        return self.server

    async def read_wifi(self):
        return dict(ssid=self.ssid, supported=True, observedAt=timestamp())

    async def set_server(self, host, transport):
        from .models.session import hostname

        if transport not in self.capabilities()["serverTransports"]:
            raise ValueError("Unsupported transport")
        self.server = dict(
            host=hostname(host, self.capabilities()["hostnameMaxBytes"]),
            transport=transport,
            supported=True,
            unset=False,
        )
        return {**self.server, "readbackMatches": True, "observedAt": timestamp()}

    async def connect_wifi(self, ssid, password):
        self.ssid = ssid
        return dict(
            ssid=ssid,
            storedSsidMatches=True,
            joinStatus="success",
            observedAt=timestamp(),
        )

    async def set_time(self, **fields):
        return dict(acknowledged=True)

    async def install(self, image, progress):
        self.ota_started = True
        for i in range(11):
            progress("transferring", len(image) * i // 10, len(image))
            await asyncio.sleep(0.1)
        return dict(transferred=True, simulated=True, runningFirmwareConfirmed=False)
