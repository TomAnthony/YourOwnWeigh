"""Serialized bridge commands and local operation ownership.

A running operation belongs to this process, not its WebSocket. Reconnecting
publishes a snapshot; it never silently starts another firmware update. Device
commands are tied to a connection generation, preventing stale browser tabs
from acting on a subsequently connected scale.
"""

import asyncio
import base64
import hashlib
import json
import logging
import platform
import re
import time
import uuid
from pathlib import Path

from . import __version__
from .models.registry import MODELS
from .firmware import RELEASES, atomic_write, generate, inspect
from .models.protocol import ProtocolError
from .models.session import ScaleSession, timestamp
from .transports import backend

from . import BRIDGE_PROTOCOL

LOG = logging.getLogger("yow")
COMMANDS = {
    "bridge.describe",
    "device.scan.start",
    "device.scan.stop",
    "device.connect",
    "device.disconnect",
    "device.probe",
    "device.complete_setup",
    "device.reveal_secret",
    "device.enroll",
    "device.read_configuration",
    "device.set_server",
    "device.connect_wifi",
    "device.set_time",
    "firmware.generate",
    "firmware.inspect",
    "firmware.install",
    "artifact.begin",
    "artifact.chunk",
    "artifact.finish",
    "artifact.discard",
    "artifact.read",
    "operation.get",
    "operation.cancel",
}


class Application:
    def __init__(self, state_dir, simulate=False):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.simulate = simulate
        self.sequence = 0
        self.outgoing = asyncio.Queue(maxsize=256)
        self.session = None
        self.transport_backend = None
        self.device_id = None
        self.generation = 0
        self.task = None
        self.active = None
        self.history = {}
        self.artifacts = {}
        self.upload = None
        self.last_progress = 0
        self.last_progress_log = 0
        self.candidates = {}
        self.connected = False
        previous = self.state_dir / "last-ota.json"
        if previous.exists():
            try:
                record = json.loads(previous.read_text())
                if record.get("state") in ("prepared", "running", "failed"):
                    LOG.warning(
                        "The previous firmware operation did not finish with a confirmed transfer. "
                        "Reconnect and probe the scale before another update; no transfer will be resumed."
                    )
            except (OSError, ValueError, AttributeError):
                LOG.warning("Could not read the previous firmware-operation journal")

    def emit(self, kind, command=None, **values):
        self.sequence += 1
        event = dict(
            protocol=BRIDGE_PROTOCOL,
            version=1,
            kind=kind,
            sequence=self.sequence,
            **values,
        )
        if command:
            event.update(
                {
                    k: command[k]
                    for k in (
                        "id",
                        "operationId",
                        "name",
                        "deviceId",
                        "connectionGeneration",
                        "replyTo",
                    )
                    if k in command
                }
            )
        # Old status updates are expendable. Terminal outcomes remain in the
        # operation cache and can be recovered with operation.get after reconnect.
        if self.outgoing.full():
            self.outgoing.get_nowait()
        self.outgoing.put_nowait(event)
        return event

    def snapshot(self):
        return dict(
            helperVersion=__version__,
            os=platform.system(),
            simulated=self.simulate,
            models=list(MODELS),
            backends=["CoreBluetooth", "IOBluetooth"]
            if platform.system() == "Darwin"
            else ["BlueZ GATT", "BlueZ RFCOMM"] if platform.system() == "Linux" else [],
            deviceId=self.device_id,
            connectionGeneration=self.generation,
            state="connected" if self.connected else "disconnected",
            device=self.session.public_identity()
            if self.session and self.session.identity and self.connected
            else None,
            candidates=list(self.candidates.values()),
            activeOperation=self.active,
            artifacts=[value[1] for value in self.artifacts.values()],
        )

    async def accept(self, command):
        try:
            if (
                command.get("protocol") != BRIDGE_PROTOCOL
                or command.get("version") != 1
                or command.get("kind") != "command"
            ):
                raise ValueError("Unsupported bridge protocol")
            if command.get("name") not in COMMANDS or not isinstance(
                command.get("parameters"), dict
            ):
                raise ValueError("Unknown command or invalid parameters")
            for key in ("id", "operationId"):
                if not isinstance(command.get(key), str) or not re.fullmatch(
                    r"[a-zA-Z0-9_-]{1,80}", command[key]
                ):
                    raise ValueError(f"Invalid {key}")
            fingerprint = hashlib.sha256(
                json.dumps(command, sort_keys=True).encode()
            ).hexdigest()
            prior = self.history.get(command["id"])
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise ValueError("Command ID was reused with different parameters")
                self.emit(
                    prior["event"]["kind"],
                    command,
                    **{
                        k: v
                        for k, v in prior["event"].items()
                        if k in ("result", "error", "progress")
                    },
                )
                return
            name = command["name"]
            if name in (
                "bridge.describe",
                "operation.get",
                "operation.cancel",
                "device.scan.stop",
            ):
                result = await self.execute(command)
                self.emit("result", command, result=result)
                return
            if (
                name == "device.connect"
                and self.task
                and not self.task.done()
                and self.active
                and self.active["name"] == "device.scan.start"
            ):
                if self.connected or command.get("deviceId") not in self.candidates:
                    raise ValueError("Select a device found by this scan")
                # Discovery owns the radio until its backend has stopped. Wait
                # for that cleanup before opening GATT/RFCOMM, preserving the
                # discovered-device cache. Never cancel a firmware operation.
                self.transport_backend.stop.set()
                try:
                    await asyncio.wait_for(asyncio.shield(self.task), 5)
                except TimeoutError:
                    raise ValueError(
                        "Scan is still stopping; try Connect again shortly"
                    ) from None
            if self.task and not self.task.done():
                raise ValueError("DEVICE_BUSY: another operation is in progress")
            if (
                name.startswith("device.")
                and name not in ("device.scan.start", "device.connect")
                or name == "firmware.install"
            ):
                if (
                    not self.connected
                    or command.get("deviceId") != self.device_id
                    or command.get("connectionGeneration") != self.generation
                ):
                    raise ValueError(
                        "STALE_CONNECTION: reconnect and probe before continuing"
                    )
            self.active = dict(
                operationId=command["operationId"],
                name=name,
                state="running",
                stage="accepted",
            )
            event = self.emit("accepted", command, progress=self.active)
            self.history[command["id"]] = dict(fingerprint=fingerprint, event=event)
            self.task = asyncio.create_task(self.run(command))
        except Exception as error:
            self.emit("error", command, error=self.error(error))

    def error(self, error):
        # Libraries may attach URLs to transport errors. Never log commands or
        # their parameters. Device-facing errors here are our bounded messages.
        if isinstance(error, TimeoutError):
            return dict(
                code="TIMEOUT",
                message="Scale response timed out; reconnect and probe before retrying",
                retryable=True,
            )
        return dict(
            code="OPERATION_FAILED",
            message=str(error)[:240] or type(error).__name__,
            retryable=False,
        )

    async def run(self, command):
        name = command["name"]
        LOG.info("%s started", name)
        try:
            result = await self.execute(command)
            event = self.emit("result", command, result=result)
            self.active = dict(
                operationId=command["operationId"],
                name=name,
                state="complete",
                result=result
                if name
                not in ("device.enroll", "device.reveal_secret", "artifact.read")
                else {"available": True},
            )
            LOG.info("%s complete", name)
        except asyncio.CancelledError:
            event = self.emit(
                "error",
                command,
                error=dict(
                    code="CANCELLED",
                    message="Operation cancelled before OTA START",
                    retryable=True,
                ),
            )
            self.active = dict(
                operationId=command["operationId"], name=name, state="cancelled"
            )
        except Exception as error:
            detail = self.error(error)
            if name == "firmware.install" and self.session and self.session.ota_started:
                detail = dict(
                    code="OTA_OUTCOME_UNKNOWN",
                    message="OTA outcome is unknown. Reconnect and probe; do not assume the old or new image is running.",
                    retryable=False,
                )
            event = self.emit("error", command, error=detail)
            self.active = dict(
                operationId=command["operationId"],
                name=name,
                state="failed",
                error=detail,
            )
            LOG.error("%s: %s", name, detail["message"])
        finally:
            if name == "firmware.install":
                self.journal(self.active)
                if self.session and self.session.ota_started:
                    self.session.identity = None
        self.history[command["id"]]["event"] = event
        while len(self.history) > 200:
            del self.history[next(iter(self.history))]
        self.emit("snapshot", snapshot=self.snapshot())

    def journal(self, record):
        atomic_write(
            self.state_dir / "last-ota.json", json.dumps(record, indent=2).encode()
        )

    def progress(self, command, stage, done, total):
        self.active = dict(
            operationId=command["operationId"],
            name=command["name"],
            state="running",
            stage=stage,
            bytesDone=done,
            bytesTotal=total,
        )
        current = time.monotonic()
        if (
            current - self.last_progress >= 0.25
            or stage != "transferring"
            or done == total
        ):
            self.emit("progress", command, progress=self.active)
            self.last_progress = current
        if stage in ("starting", "transfer_complete"):
            self.journal({**self.active, "deviceId": self.device_id, "at": timestamp()})
        if (
            stage != "transferring"
            or done == total
            or current - self.last_progress_log >= 5
        ):
            LOG.info(
                "%s: %s (%s/%s, %.1f%%)",
                command["name"],
                stage,
                done,
                total,
                100 * done / total if total else 0,
            )
            self.last_progress_log = current

    def artifact(self, data, model, filename):
        meta = inspect(data, model)
        ident = uuid.uuid4().hex
        meta.update(
            artifactId=ident,
            filename=Path(filename).name,
            compatible=bool(
                self.connected
                and self.session
                and self.session.model == model
                and self.session.identity
                and self.session.capabilities()["ota"]
            ),
        )
        # Keep at most four ~1 MiB images locally; firmware is never persisted at the server.
        while len(self.artifacts) >= 4:
            del self.artifacts[next(iter(self.artifacts))]
        self.artifacts[ident] = (data, meta)
        return meta

    async def execute(self, command):
        name, p = command["name"], command["parameters"]
        if name == "bridge.describe":
            return self.snapshot()
        if name == "operation.get":
            for item in self.history.values():
                if item["event"].get("operationId") == p.get("operationId"):
                    return item["event"]
            raise ValueError("Unknown operation")
        if name in ("operation.cancel", "device.scan.stop"):
            if (
                self.active
                and self.active["name"] == "firmware.install"
                and self.session
                and self.session.ota_started
            ):
                raise ValueError("CANNOT_CANCEL_AT_STAGE: OTA has already started")
            if name == "device.scan.stop":
                if self.transport_backend:
                    self.transport_backend.stop.set()
            elif self.task and not self.task.done():
                if self.active["operationId"] != p.get("operationId"):
                    raise ValueError("Unknown active operation")
                self.task.cancel()
            return dict(stopped=True)
        if name == "device.scan.start":
            if self.connected:
                raise ValueError("Disconnect the current scale before scanning")
            model, duration = p.get("model"), p.get("durationSeconds", 15)
            if type(duration) is not int or not 1 <= duration <= 60:
                raise ValueError("Scan duration must be 1–60 seconds")
            self.candidates.clear()
            if self.simulate:
                from .simulation import Backend

                self.transport_backend = Backend(model)
            else:
                self.transport_backend = backend(model)

            def found(candidate):
                self.candidates[candidate["deviceId"]] = candidate
                self.emit("candidate", command, candidate=candidate)

            await self.transport_backend.scan(duration, found)
            return dict(candidates=list(self.candidates.values()), stopped=True)
        if name == "device.connect":
            if self.connected or command.get("deviceId") not in self.candidates:
                raise ValueError(
                    "Disconnect first, then select a device from this scan"
                )
            self.device_id = command["deviceId"]
            model = self.candidates[self.device_id]["modelCandidate"]
            if self.simulate:
                from .simulation import Session

                self.session = Session(model)
            else:
                # Construct before opening: callbacks can arrive during connect.
                self.session = ScaleSession(model, None)
                session = self.session

                def disconnected():
                    if self.session is session:
                        self.connected = False
                        self.emit("snapshot", snapshot=self.snapshot())
                    session.disconnected()

                session.transport = await self.transport_backend.connect(
                    self.device_id, session.receive, disconnected
                )
            self.connected = True
            self.generation += 1
            return dict(
                deviceId=self.device_id,
                connectionGeneration=self.generation,
                state="identification_required",
            )
        if name == "device.disconnect":
            await self.session.transport.disconnect()
            self.connected = False
            self.session = None
            self.generation += 1
            return dict(state="disconnected")
        if name == "device.probe":
            return await self.session.probe()
        if name == "device.complete_setup":
            return await self.session.complete_setup()
        if name == "device.reveal_secret":
            self.session.require_identity()
            if not self.session.identity["secret"]:
                raise ProtocolError("This scale did not provide a secret in its identity response")
            return dict(secret=self.session.identity["secret"])
        if name == "device.enroll":
            if p.get("approved") is not True:
                raise ValueError("Confirm device import first")
            record = self.session.export(str(p.get("label", ""))[:80])
            configuration = await self.read_configuration()
            record.update(
                wifi_ssid=configuration["wifi"].get("ssid"),
                owner_host=configuration["server"].get("host"),
                owner_transport=configuration["server"].get("transport"),
            )
            return dict(
                device=record, configuration=configuration, timeZone=p.get("timeZone")
            )
        if name == "device.read_configuration":
            return await self.read_configuration()
        if name == "device.set_server":
            return await self.session.set_server(p["host"], p["transport"])
        if name == "device.connect_wifi":
            return await self.session.connect_wifi(p["ssid"], p["password"])
        if name == "device.set_time":
            return await self.session.set_time(**p)
        if name == "firmware.generate":
            model = p.get("model")
            if model not in RELEASES:
                raise ValueError("Unknown firmware model")
            loop = asyncio.get_running_loop()

            def generated_progress(stage):
                loop.call_soon_threadsafe(self.progress, command, stage, 0, 0)

            data, meta = await asyncio.to_thread(
                generate, model, self.state_dir / "firmware", generated_progress
            )
            return self.artifact(
                data, model, f"{model.lower()}_yow_{meta['version']}.bin"
            )
        if name == "artifact.begin":
            size, model, sha = p.get("size"), p.get("model"), p.get("sha256")
            if (
                type(size) is not int
                or not 100 <= size <= 2 * 1024 * 1024
                or model not in RELEASES
                or not isinstance(sha, str)
                or not re.fullmatch(r"[a-f0-9]{64}", sha)
            ):
                raise ValueError("Invalid firmware upload declaration")
            self.upload = dict(
                id=uuid.uuid4().hex,
                data=bytearray(),
                size=size,
                model=model,
                sha=sha,
                filename=str(p.get("filename", "firmware.bin"))[:160],
            )
            return dict(transferId=self.upload["id"], nextOffset=0)
        if name == "artifact.chunk":
            u = self.upload
            if (
                not u
                or p.get("transferId") != u["id"]
                or p.get("offset") != len(u["data"])
            ):
                raise ValueError("Upload offset or transfer ID mismatch")
            data = base64.b64decode(p["dataBase64"], validate=True)
            if not 1 <= len(data) <= 32768 or len(data) + len(u["data"]) > u["size"]:
                raise ValueError("Upload chunk exceeds declared bounds")
            u["data"].extend(data)
            return dict(nextOffset=len(u["data"]))
        if name == "artifact.finish":
            u = self.upload
            if not u or p.get("transferId") != u["id"]:
                raise ValueError("Unknown upload")
            self.upload = None
            data = bytes(u["data"])
            if len(data) != u["size"] or hashlib.sha256(data).hexdigest() != u["sha"]:
                raise ValueError("Firmware upload length/hash mismatch")
            return self.artifact(data, u["model"], u["filename"])
        if name == "artifact.discard":
            self.upload = None
            self.artifacts.pop(p.get("artifactId"), None)
            return dict(discarded=True)
        if name in ("firmware.inspect", "artifact.read", "firmware.install"):
            data, descriptor = self.artifacts[p["artifactId"]]
            if name == "artifact.read":
                offset = p.get("offset", 0)
                if type(offset) is not int or not 0 <= offset <= len(data):
                    raise ValueError("Invalid firmware download offset")
                part = data[offset : offset + 32768]
                return dict(
                    dataBase64=base64.b64encode(part).decode(),
                    nextOffset=offset + len(part),
                    done=offset + len(part) == len(data),
                )
            inspected = inspect(data, descriptor["model"])
            if name == "firmware.inspect":
                return {**descriptor, **inspected}
            # Derive consent from the bytes re-inspected here, never from the
            # browser or cached descriptor. A valid container is not a known release.
            confirmation = (
                "FLASH" if inspected.get("classification") in ("known_release", "known_stock")
                else "FLASH UNKNOWN"
            )
            if (
                p.get("sha256") != inspected["sha256"]
                or self.session.model != descriptor["model"]
            ):
                raise ValueError(
                    "Firmware confirmation does not match this device and image"
                )
            if p.get("confirmation") != confirmation:
                raise ValueError(f"Type {confirmation} to confirm this firmware image")
            self.journal(
                dict(
                    operationId=command["operationId"],
                    state="prepared",
                    sha256=inspected["sha256"],
                    model=descriptor["model"],
                    deviceId=self.device_id,
                    at=timestamp(),
                )
            )
            return await self.session.install(
                data,
                lambda stage, done, total: self.progress(command, stage, done, total),
            )
        raise ValueError("Unsupported command")

    async def read_configuration(self):
        # An unconfigured target can reject GET_CHUNK. Identity/enrollment must
        # still work; record each optional observation independently.
        result = {"observedAt": timestamp()}
        for key, method in (
            ("server", self.session.read_server),
            ("wifi", self.session.read_wifi),
        ):
            try:
                result[key] = await method()
            except (ProtocolError, TimeoutError) as error:
                result[key] = {
                    "supported": True,
                    "available": False,
                    "error": str(error),
                }
        return result
