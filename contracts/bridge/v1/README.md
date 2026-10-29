# Bridge Protocol v1

Authoritative wire envelope: [command.schema.json](command.schema.json). Per-command parameters: [commands.json](commands.json). The broker adds `protocol`, `version`, `kind` and private `replyTo`; browser commands include `clientId` from the UI socket's ready event. The broker validates admin/session ownership; Python validates model-specific parameters and connection state. Firmware and radio details never enter this contract.

## Pairing And Transport

1. Admin POST `/api/bridge/invitations` with same-origin/CSRF creates `{version:1,server,token,expiresAt}`. Ten-minute validity.
2. Helper POST `/api/bridge/exchange` with `{token,attemptId}`. The same secret invitation/attempt can recover a lost response; a different second attempt fails. Response: `{credential,helperId,expiresAt}`. Seven-day pairing; only its hash persists server-side.
3. Helper opens `/api/bridge/socket` using `Authorization: Bearer <credential>` over verified WSS (WS only on loopback).
4. Browser opens `/api/bridge/ui/socket` using its admin cookie and Origin; `ready` supplies `clientId` and helper status. Browser POST `/api/bridge/commands` uses cookie, Origin and `X-CSRF-Token`.

One active helper and one active operation per installation/bridge. Browser disconnect does not own the operation lifetime. Node uses `ws`; Worker uses hibernating Durable Object WebSockets. Pairing state survives restarts, while operation/artifact state belongs to the running Python process. Node files contain hashed pairing state; DO storage contains the same bounded record.

## Envelope And Events

```json
{"protocol":"yow.bridge","version":1,"kind":"command","id":"unique-command-id","operationId":"unique-operation-id","name":"device.probe","parameters":{},"deviceId":"opaque-discovery-id","connectionGeneration":1,"replyTo":"private-ui-connection-id"}
```

The helper sends `hello` and `snapshot` events containing model capabilities, connection state, sanitized identity, artifacts and active operation. The broker translates these into UI `connection` status. Other events retain `id`, `operationId`, `name` and `replyTo`: `accepted`, `candidate`, `progress`, `result`, or `error`. A result has `result`; an error has `{code,message,retryable}` under `error`. Event payloads never require clients to parse log strings.

- Discovery returns candidates `{deviceId,name,rssi,modelCandidate,presence}`; these are hints. Probe validates the actual identity.
- Probe returns `{model,mac,name,firmwareVersion,bootloaderVersion,hardwareVersion,rescueVersion,capabilities,...}` without the secret. Capabilities include `ota`, `serverRead`, `serverWrite`, `serverTransports`, `hostnameMaxBytes` and Wi-Fi support.
- Connection mutations return a monotonically increasing `connectionGeneration`. Device commands and install must repeat it with the opaque `deviceId`. Reconnect requires a new probe.
- `device.enroll` requires `approved:true` and returns the existing portable device-export schema plus observations. Failed optional reads are represented as unavailable, not invented defaults. The server's separate `/api/scales/enroll` then stores and migrates the approved device.
- `device.set_time` receives UTC/goff/dst/ngoff already calculated by the server; Python only validates and packs them. [Clock vectors](../../time/v1/vectors.json).
- Wi-Fi result distinguishes `storedSsidMatches` from `joinStatus`. Server contact is a separate authenticated-session observation through `/api/scales/:id/connection-status`.

## Firmware, Idempotency And Reconnect


`firmware.generate` returns a validated descriptor: artifact ID, model, filename, version, size, SHA-256 and known-release/stock/custom classification. `artifact.begin/chunk/finish` supports manual completed-image upload with exact offsets and a final digest; chunks contain at most 32,768 decoded bytes and images at most 2 MiB. At most four artifacts are retained locally. `artifact.read` downloads bounded pieces; bytes are not persisted on the server.

`firmware.install` requires the artifact ID, exact displayed digest and `confirmation:"FLASH"`. The helper revalidates the image/model/capabilities immediately before START. `progress` has a named stage and byte counters, throttled to four updates/second. Transfer complete is not running-version confirmation. Neither model promises an OTA destination bank through this API.

Python retains up to 200 command outcomes; duplicate IDs with identical envelopes return the retained outcome. Reusing an ID with different parameters fails. `operation.get` and `bridge.describe` recover state after reconnect. Never generate a new OTA command ID automatically after a timeout. Cancellation after OTA START is rejected; browser/server disconnection leaves the local transfer running. Process death loses the live transfer; the journal is diagnostic, not an automatic resume instruction.

The server keeps at most 100 non-private outcomes for polling. Reveal/export/artifact data routes only to the initiating socket and is not cached in the database. Hibernation uses echoed `replyTo` to recover routing; IDs are server-issued and authenticated on command submission. A newly connected browser can request a new approved export if its earlier private result was lost.

Malformed, oversized or stale commands fail before hardware access. Revoke pairing via POST `/api/bridge/revoke`; it closes the server connection without pretending an already-started physical update was cancelled.

## Connection Liveness And OTA Observation

Helpers send `X-YOW-Bridge-Run` on the authenticated socket upgrade: a random identifier for one process lifetime, stable across reconnects. It is not an authentication credential. Only an authenticated reconnect with the same run ID may replace a still-live socket; other processes get HTTP 409 and retry. HTTP 401 is the expired/revoked credential case.

A helper sends `{protocol:"yow.bridge",version:1,kind:"ping"}` every ten seconds; the broker replies with the same envelope and `kind:"pong"`. Helpers reconnect if broker replies stop. Any valid helper event refreshes its 45-second lease. Durable Object socket attachments retain the last contact time and run ID, and closing sockets are not restored as live peers. No firmware or private payload is persisted for this purpose.

OTA events also produce public-to-admin `operation` events with the current `activeOperation`. They update the cached snapshot and reach refreshed tabs, independently of the initiating command's private reply route. Other command results remain private to that route. A reconnect hello/describe restores current state from Python; a browser can settle its existing OTA wait by matching `operationId` without sending another install command.

Candidate `presence` is `seen` (discovered this scan), `paired_only` (cached pairing, no current inquiry sighting), or `connected` (Classic link currently connected to the Mac). It is a discovery observation, not a setup-mode claim. Missing values from older helpers display as unknown.

Since bridge 0.2.3, `device.connect` may interrupt an active `device.scan.start` for a candidate already returned by that scan. Python signals scan stop and awaits backend cleanup before connecting, preserving the candidate cache. The scan still returns its result. Other active operations remain busy; an unknown candidate does not stop discovery. This applies to both BLE and Classic transports.
