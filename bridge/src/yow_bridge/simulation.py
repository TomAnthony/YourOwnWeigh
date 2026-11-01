"""Explicit UI demonstration backend. Never opens Bluetooth or writes hardware."""

import asyncio

from .models.session import ScaleSession, timestamp


_DEMO_NAME = {"WBS06": "Demo Body", "WBS03": "Demo WS-30", "WBS04": "Demo Body Cardio"}


class Backend:
    def __init__(self, model):
        if model not in ("WBS06", "WBS03", "WBS04"):
            raise ValueError("Unsupported model")
        self.model, self.stop = model, asyncio.Event()

    async def scan(self, seconds, found):
        await asyncio.sleep(0.1)
        found(
            dict(
                deviceId="demo-scale",
                name=_DEMO_NAME[self.model],
                rssi=-45,
                modelCandidate=self.model,
                presence="seen",
            )
        )


_SIM_PROFILE = {
    "WBS06": dict(name="Body", mac="020000000006", firmware=127, boot=4),
    "WBS03": dict(name="WS-30", mac="020000000003", firmware=102, boot=15),
    # Starts on stock 2231 so the dry-run shows the real stock->flash->config
    # progression; install() flips it to the YOW owner version.
    "WBS04": dict(name="Body Cardio", mac="020000000004", firmware=2231, boot=12),
}


# Firmware "installed" on each demo scale for the life of the bridge process.
# A reconnect creates a new Session, which must still see the flashed version.
_INSTALLED = {}


class Session(ScaleSession):
    def __init__(self, model):
        super().__init__(model, self)
        self.server = dict(supported=True, unset=True)
        self.ssid = "Demo Wi-Fi"
        self.firmware = _INSTALLED.get(model, _SIM_PROFILE[model]["firmware"])

    async def probe(self):
        p = _SIM_PROFILE[self.model]
        self.identity = dict(
            name=p["name"],
            model=self.model,
            mac=p["mac"],
            secret="0123456789abcdef",
            hardwareVersion=0xFFFFFF,
            firmwareVersion=self.firmware,
            bootloaderVersion=p["boot"],
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
        # Model the reboot into YOW firmware so a re-probe reflects the new
        # version and server config becomes available (WBS06/WBS04).
        self.firmware = {"WBS06": 127, "WBS03": 102, "WBS04": 100}.get(
            self.model, self.firmware
        )
        _INSTALLED[self.model] = self.firmware
        return dict(transferred=True, simulated=True, runningFirmwareConfirmed=False)
