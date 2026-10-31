# WBS13 Owner Target Patch

This component targets the exact WBS13 stock v1311 image pinned by the builder.
It supplies owner-server configuration to both normal Wi-Fi synchronization and
the separate DNS lookup used during Wi-Fi setup. It does not write the factory
hostname, device secret, client certificate/key, calibration, or diagnostic mask.

Before an owner target is configured, the stock hostname and HTTPS behavior are
retained. An invalid committed record produces an empty host that the stock URL
parser rejects; it does not fall back to the factory service. The TLS component
uses `owner_target_enabled()` to select its owner-server behavior.

## Bluetooth Protocol

Command and TLV type are both `0x0170`, using the existing owner protocol version
1. The TLV value starts with `[version, operation]`; integers below are single
bytes. HTTP is mode 0 and HTTPS is mode 1.

| Operation | Value Bytes After Version | Purpose |
| --- | --- | --- |
| Get | `0` | Read the committed target |
| Set | `1, mode, length, host…` | Atomically replace the target |
| Begin | `2, transfer_id, mode, total_length` | Start a staged write |
| Data | `3, transfer_id, offset, chunk_length, chunk…` | Append at most six hostname bytes |
| Commit | `4, transfer_id` | Validate and atomically commit the staged target |
| Get Chunk | `5, offset` | Read at most six committed hostname bytes |

Replies contain `[1, operation, status, mode, total_length, host_bytes…]`.
Status 0 is success, 1 invalid input, 2 no usable target, and 3 a storage failure.
The staged write and chunked read paths fit a 20-byte ATT payload including the
WPP frame. They require sequential chunks and preserve the previous committed
target until Commit succeeds. Full Get/Set replies require a larger negotiated
transport payload.

Hostnames are limited to 48 ASCII bytes. Lowercase letters, digits, hyphens and
dots are accepted with nonempty valid labels; URL schemes, paths, ports and the
Withings domain are rejected. The stock parser has a 50-byte host buffer, and
the offline test executes that parser to verify a 48-byte target survives.

The committed target is current-user DBLIB item `0x01F0` (magic `YOW1`); staging
uses item `0x01F1` (magic `STG1`). Both are fixed 72-byte records. The original
13-entry WPP fallback table is copied and one owner command is appended. The
stock dispatcher's connection and authorization checks remain in place.

## Identity And Firmware Offers

The identity hook fills the existing length-prefixed secret field from the
factory secret record when it contains exactly 16 hexadecimal characters. It
does not change the underlying secret or the stock authentication gates. The
original firmware-version getter still provides the reported version.

Owner mode suppresses Wi-Fi firmware offers. The session response hook clears
any offered URL/hash, and a second gate clears a previously cached factory offer
before the session-close download decision. This also covers a response with no
new firmware offer. Factory behavior is preserved while the owner record is
absent. Bluetooth OTA is a separate path.

## Offline Checks

`test_owner_target.py STOCK.bin` executes the injected Thumb code with Unicorn,
including the original fallback-table dispatcher, URL selection/parser, and
session-close offer decision. Synthetic DBLIB and WPP stubs check atomic writes,
chunk boundaries, corrupt storage, host limits, factory fallback, identity ABI,
and stale-offer suppression. Patch-site byte guards and reserved-code bounds
are checked too. These checks do not substitute for live Bluetooth, storage,
Wi-Fi, and OTA qualification.
