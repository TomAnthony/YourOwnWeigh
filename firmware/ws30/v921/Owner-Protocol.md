# WS-30 Owner Protocol

These addresses and wire formats apply to WBS03/WS-30 stock 921, bootloader 15, with the YourOwnWeigh v102 patch.

## Hostname And Provisioning

The owner hostname lives in writable DBLIB item 2. The patch redirects the item-2 lookup at runtime `0x1b230` and HTTP URL copy at `0x22d14` to the current bank. Stock DBLIB calls are `0x25d85` (open), `0x25e19` (read), and `0x25df1` (close). Both hooks are needed: Wi-Fi's DNS check and HTTP requests otherwise use different target buffers.

WPP command/object `0x170`:

- Request: `[1, operation, length, hostname]`, with operation 0 to read or 1 to write.
- Reply: `[1, operation, status, length, hostname]`.
- Status: 0 success, 2 unconfigured, 3 write/readback failure.

Replies use the stock dispatcher's deferred callback mechanism. Hostnames are lowercase ASCII DNS names or IPv4, 1–59 bytes, with no scheme, port or path. The factory destination is rejected until an owner target is configured. Transport is HTTP on port 80.

SSID readback uses WPP `0x104`; Wi-Fi writes use command `0x103` with object `0x104`. Complete Setup is command `0x113`, distinct from a `0x113` object within a Wi-Fi request. Check the Wi-Fi join result separately from stored configuration.

## Wi-Fi Sync

The patched scale calls root `/once` and `/session` endpoints. Its session authentication is the 32-hex MD5 of `<mac>:<secret>:<once>`; WBS06 uses SHA-256 and must remain a separate model branch. The server consumes nonces once, binds sessions to the enrolled device and validates payload bounds.

The session response contains `sessionid`, current `syp.utc` and optional `ctp` timezone fields. Omitting `sp`/`users` preserves the stored roster. The v921 roster routine at `0x23af4` checks for completed parser state at `0x23b74`–`0x23b82` before writing DBLIB item 5. The timezone routine similarly requires a complete `ctp` at `0x23cb8`–`0x23cc0` before changing item 4. The session caller continues past absent-field returns.

The scale requests `/v2/summary`, uploads `/measure` using `batchstore`, then closes its session. The server accepts readings idempotently and returns an empty summary and weather response. `/maint` is unsupported. HTTP to a public server exposes authentication and measurement traffic in cleartext.

User import from Withings populates the local household but does not write a WS-30 roster. Live weather, generated graphs and WS-30 HTTPS are not implemented. See the [shared server](../../../server/ts/README.md) and [Withings fixtures](../../../contracts/withings/README.md).
