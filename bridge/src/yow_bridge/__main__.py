"""Run with `yow-bridge`; paste the invitation shown on your server’s Firmware Bridge page.

--log-file PATH stores operation names/outcomes, never raw Bluetooth bytes,
passwords, or pairing tokens. --simulate is an explicit hardware-free UI demo.
An update continues across browser/network disconnects while this process runs.
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from . import BRIDGE_PROTOCOL, USER_AGENT, __version__
from .application import Application
from .firmware import NoRedirect, atomic_write

LOG = logging.getLogger("yow")


def server_url(raw):
    url = urllib.parse.urlsplit(raw)
    if (
        url.username
        or url.password
        or url.query
        or url.fragment
        or url.path not in ("", "/")
    ):
        raise ValueError("Server must be an origin URL, without credentials or a path")
    if url.scheme != "https" and not (
        url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")
    ):
        raise ValueError("Use HTTPS, or HTTP on this computer's loopback address")
    if not url.hostname:
        raise ValueError("Server hostname is missing")
    return raw.rstrip("/")


def exchange(invitation):
    import uuid

    origin = server_url(invitation["server"])
    if invitation.get("version") != 1 or not isinstance(invitation.get("token"), str):
        raise ValueError("Invalid pairing invitation")
    data = json.dumps(
        dict(token=invitation["token"], attemptId=uuid.uuid4().hex)
    ).encode()
    request = urllib.request.Request(
        origin + "/api/bridge/exchange",
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urllib.request.build_opener(NoRedirect).open(
            request, timeout=20
        ) as response:
            result = json.loads(response.read(8193))
    except urllib.error.HTTPError as error:
        # An edge rejection is different from a bad invitation. Do not print
        # arbitrary response bodies: a proxy may echo credentials or requests.
        with error:
            body = error.read(8192)
        if error.code == 403 and body.strip() == b"error code: 1010":
            message = "Cloudflare blocked this HTTP client (403/1010). Update the bridge and retry."
        else:
            message = {
                401: "Invitation is invalid, expired, or already used. Generate a new invitation.",
                403: "Server or proxy refused pairing (HTTP 403). Check its access rules; this does not mean the invitation expired.",
                409: "A bridge is already paired. Disconnect it in Firmware Bridge before pairing another.",
                429: "Too many pairing attempts. Wait ten minutes, then generate a new invitation.",
            }.get(error.code, f"Pairing request failed (HTTP {error.code}).")
        raise ValueError(message) from None
    if not isinstance(result.get("credential"), str):
        raise ValueError("Server did not return a bridge credential")
    pairing = dict(
        server=origin, credential=result["credential"], helperId=result["helperId"]
    )
    if "expiresAt" in result:
        pairing["expiresAt"] = result["expiresAt"]
    return pairing


async def network(application, pairing, stopped):
    parsed = urllib.parse.urlsplit(pairing["server"])
    socket_url = urllib.parse.urlunsplit(
        (
            "wss" if parsed.scheme == "https" else "ws",
            parsed.netloc,
            "/api/bridge/socket",
            "",
            "",
        )
    )
    backoff = 1
    # Stable across this process's reconnects, distinct from another --resume
    # process. An authenticated reconnect may replace its own half-open socket.
    run_id = uuid.uuid4().hex
    while not stopped.is_set():
        try:
            async with connect(
                socket_url,
                additional_headers={
                    "Authorization": "Bearer " + pairing["credential"],
                    "X-YOW-Bridge-Run": run_id,
                },
                user_agent_header=USER_AGENT,
                max_size=65536,
                open_timeout=20,
                ping_interval=20,
                ping_timeout=20,
            ) as socket:
                LOG.info("Connected to %s", pairing["server"])
                backoff = 1
                # Clear before taking/sending the fresh snapshot. Clearing after
                # an awaited send could discard a just-completed OTA outcome.
                while not application.outgoing.empty():
                    application.outgoing.get_nowait()
                await socket.send(
                    json.dumps(
                        dict(
                            protocol=BRIDGE_PROTOCOL,
                            version=1,
                            kind="hello",
                            snapshot=application.snapshot(),
                        )
                    )
                )
                # Drop stale progress from the disconnected period. The snapshot
                # and operation cache are the source of truth after reconnect.
                async def sender():
                    while True:
                        event = await application.outgoing.get()
                        await socket.send(json.dumps(event))

                last_received = time.monotonic()

                async def receiver():
                    nonlocal last_received
                    async for message in socket:
                        if not isinstance(message, str):
                            continue
                        value = json.loads(message)
                        last_received = time.monotonic()
                        if value.get("kind") != "pong":
                            await application.accept(value)

                async def heartbeat():
                    # WebSocket ping/pong alone can be handled by an edge proxy;
                    # this checks that the actual broker is still responding.
                    while True:
                        await asyncio.sleep(10)
                        if time.monotonic() - last_received > 35:
                            raise TimeoutError("Bridge broker stopped responding")
                        await socket.send(json.dumps(dict(
                            protocol=BRIDGE_PROTOCOL, version=1, kind="ping"
                        )))

                pumps = [asyncio.create_task(fn()) for fn in (sender, receiver, heartbeat)]
                try:
                    done, _ = await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in pumps:
                        task.cancel()
                    await asyncio.gather(*pumps, return_exceptions=True)
        except ConnectionClosed as error:
            # Codes are useful diagnostics; arbitrary server text may contain
            # request details, so log the codes without echoing the close reason.
            LOG.warning(
                "Server connection interrupted (WebSocket received=%s sent=%s); reconnecting, device operations continue locally",
                error.rcvd.code if error.rcvd else "none",
                error.sent.code if error.sent else "none",
            )
        except (OSError, TimeoutError, ValueError) as error:
            LOG.warning(
                "Server connection interrupted (%s); device operations continue locally",
                type(error).__name__,
            )
        except Exception as error:
            # Includes a revoked/expired credential and an HTTP upgrade error.
            status = getattr(getattr(error, "response", None), "status_code", None)
            if status == 403:
                LOG.error(
                    "Server or proxy refused the WebSocket (HTTP 403). Check its access rules; the pairing may still be valid."
                )
                return
            if status == 401:
                LOG.error(
                    "Bridge pairing expired or was revoked (HTTP 401). Generate a new invitation on the server. Invitation expiry itself does not end an established pairing."
                )
                return
            if status == 409:
                LOG.warning(
                    "Server still has another bridge socket (HTTP 409); retrying while its heartbeat expires. The saved pairing remains valid."
                )
            else:
                LOG.warning("Server connection failed (%s); retrying", type(error).__name__)
        try:
            await asyncio.wait_for(stopped.wait(), backoff)
        except TimeoutError:
            pass
        backoff = min(30, backoff * 2)


async def run(args, pairing):
    application = Application(args.state_dir, args.simulate)
    stopped = asyncio.Event()
    loop = asyncio.get_running_loop()

    def stop():
        if (
            application.task
            and not application.task.done()
            and application.active
            and application.active["name"] == "firmware.install"
            and application.session.ota_started
        ):
            LOG.warning(
                "OTA is in progress. Keep this process running until it completes; Ctrl-C cannot safely cancel it."
            )
            return
        stopped.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop)
    tasks = [asyncio.create_task(network(application, pairing, stopped))]
    if sys.platform == "darwin" and not args.simulate:
        from .transports.classic_macos import cocoa_run_loop

        tasks.append(asyncio.create_task(cocoa_run_loop()))
    tasks.append(asyncio.create_task(stopped.wait()))
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        # Loss of credentials must not terminate an in-flight flash either.
        if (
            application.task
            and not application.task.done()
            and application.session
            and application.session.ota_started
        ):
            LOG.warning("Waiting for the active firmware transfer before exiting")
            await application.task
    finally:
        if application.task and not application.task.done():
            application.task.cancel()
            await asyncio.gather(application.task, return_exceptions=True)
        if application.session and application.session.transport:
            await application.session.transport.disconnect()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--version", action="version", version=f"YourOwnWeigh bridge {__version__}")
    parser.add_argument(
        "--log-file", type=Path, help="Write operation logs to this local file"
    )
    parser.add_argument(
        "--state-dir", type=Path, default=Path.home() / ".local/share/yow"
    )
    parser.add_argument(
        "--resume", action="store_true", help="Reconnect using the last saved pairing"
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Explicit demo backend; never accesses hardware",
    )
    args = parser.parse_args()
    os.umask(0o077)
    handlers = [logging.StreamHandler()]
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s", handlers=handlers
    )
    # Avoid library debug output exposing transport parameters.
    logging.getLogger("websockets").setLevel(logging.WARNING)
    LOG.info("YourOwnWeigh bridge %s", __version__)
    if sys.platform != "darwin" and not args.simulate:
        parser.error(
            "This release supports macOS Bluetooth; Linux and Windows are planned."
        )
    try:
        path = args.state_dir / "pairing.json"
        if args.resume:
            pairing = json.loads(path.read_text())
            server_url(pairing["server"])
        else:
            invitation = json.loads(
                input("Paste the connection invitation from the Firmware Bridge page:\n")
            )
            pairing = exchange(invitation)
            atomic_write(path, json.dumps(pairing).encode())
        asyncio.run(run(args, pairing))
    except (ValueError, KeyError, OSError) as error:
        LOG.error("Could not start: %s", str(error)[:200])
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
