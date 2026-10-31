# WBS13 / Body Smart v1311 Analysis

Analysis and validation date: 31 October 2026. **YOW v100 passed live OTA,
reconnect/probe, Complete Setup, unset-settings readback, HTTP capture and direct
HTTPS sync to the YOW Cloudflare Worker. The scale adopted existing YOW users;
weight, body composition, heart rate and previously queued readings were stored
successfully.** Configured-settings readback and cold-restart persistence remain
separate checks. See
[build and test instructions](BUILD.md).

The image contains a usable Bluetooth firmware updater and a familiar Withings
session protocol. The candidate implements its own container, network and
provisioning patches. The server supports local enrollment, an explicitly selected
local roster and multi-metric uploads, validated with both capture replay and a
live scale. The firmware and server protocol are independent of the computer's
operating system. Platform-specific checks concern the Bluetooth transport; see
the [hardware checklist](../../../docs/hardware-acceptance.md).

The normal Bluetooth identity response deliberately leaves the secret empty,
but a separate diagnostic database dump **returned it on the factory-new
v1311 unit**. The value exactly matches the independently decoded UART copy.
This required a temporary diagnostic-mask write; registered-device access
remains untested.

## Evidence And Scope

This analysis combines:

- Prior live BLE identity/service discovery on a factory-new, unregistered scale.
- Prior UART boot output, `probe`, `update state`, and two complete external
  firmware backups made with [the WBS13 dumper](../../../tools/dump_wbs13_firmware.py).
- Disassembly of the application and bootloader in those backups.
- Execution of selected original ARM routines in Unicorn with simulated inputs.
- Comparison with the current Python bridge and TypeScript server.
- A live BLE database dump, followed by resetting the diagnostic mask to zero
  and checking that the reported factory/setup state was unchanged.
- Two matching UART reads of each complete factory/user configuration bank,
  including a validated factory TLS client certificate and matching private key.
- Live `/once` and `/session` requests using the independently verified device
  credentials and client identity, without association or setup finalization.
  The offered vendor image matches both UART firmware backups byte for byte.
- Two matching read-only UART reads of the internal flash security boundary,
  followed by emulation of the original bootloader installing the combined
  candidate from either explicit OTA slot.
- Owner-confirmed Bluetooth OTA to v100, reconnect/probe reporting 100, and
  Complete Setup changing the device's screen on 31 October 2026.
- Live v100 Bluetooth readback of an unset owner target and absent Wi-Fi network.
  Both replies parsed successfully; no configuration was written during this check.
- A live v100 HTTP session to the capture listener, including an unassigned
  weight upload and explicit session deletion. All nine exchanges were saved
  with verified request-body hashes and received HTTP 200 / status 0.
- Two further HTTP sessions after provisioning a test roster: one unassigned
  weight, then a recognised user's weight, body composition and heart rate.
  All 14 exchanges were captured and received HTTP 200 / status 0; both sessions
  ended with explicit deletion. Request framing, decoded bodies and hashes match.
- Import through the Python bridge, selection and adoption of existing YOW users,
  followed by direct HTTPS sessions to the Cloudflare Worker. After applying the
  measurement-group database migration, live uploads stored weight/body composition
  and separate heart-rate groups, including previously queued readings. The Worker
  audit recorded committed measurements and normal session closure.

The two external images are byte-identical, 1,213,984 bytes each, with SHA-256:

```text
e9a98ceb50f18b5dc2e439296b6133fec9f33ae5362785763da232b9e92b6217
```

Both headers and every component CRC validate. Device-specific credentials,
UART transcripts, and vendor binaries remain outside the distributed tree.
The BLE experiment changed the persistent diagnostic mask to `1`, then `0`;
the original mask was not read, so this is not a verified restoration of every
original diagnostic bit. That diagnostic experiment did not complete setup,
register an account or flash firmware; the later v100 OTA and Complete Setup
test are recorded separately above. Private captures and credential comparisons stay in
`local/`. The earlier Bluetooth bond did not enroll the scale with Withings.

Addresses below are **runtime Thumb addresses**, with the Thumb bit omitted
unless shown as a function pointer. Application file offsets are
`address - 0x08008000 + 0x58`; bootloader offsets are
`address - 0x08000000 + 0xA28A8`.

## Answers At A Glance

| Question | Finding | Confidence |
| --- | --- | --- |
| Firmware version? | Application **1311**, bootloader **2**; application build dated **2025-07-08 14:25:11+02:00**. | UART, image metadata and BLE agree. This does not establish the latest available release. |
| Equivalent firmware-offer flow? | Still `/once` → `/session`, SHA-256 of MAC/secret/nonce, then `body.syp.blc` and `body.syp.sha1`. Use `wbs13-ws.withings.net`, the model CA, and the device's TLS client identity. | Live authenticated lookup passed. Reporting 1310 returned 1311; the download exactly matches both UART backups. |
| Bluetooth route to the secret? | Normal probe omits it, but the diagnostic DB dump returns item 3, the raw factory secret. | Live retrieval on the unregistered v1311 unit exactly matches UART. Registered-device authentication remains untested. |
| Bluetooth OTA? | Both streaming `0x0401`–`0x0403` and chunked update handlers exist; streaming callbacks are wired into the BLE-capable transport. | Original parser/ACK-path emulation and live OTA to v100 passed. |
| YOW patch? | v100 adds owner host/transport configuration, secret readback and TLS compatibility, preserving non-application components. | OTA, setup completion, unset-settings readback, HTTP capture, local-user roster adoption and direct HTTPS server sync passed, including persisted body composition, heart rate and queued readings. |

## Firmware And Storage Layout

The image starts with an 88-byte TLV header, not the older models' container.
Its outer type/length is `(1, 80)`. Four 20-byte records follow, each holding
`<type:u16, length:u16, offset:u32, size:u32, crc32:u32, version:u32>`.
The descriptor payload length is 16. The final header word is CRC32 over the
first 84 bytes (`0xD0168DE2` in this image).

| Component | Type | File Offset | Bytes | CRC32 | Descriptor Version |
| --- | ---: | ---: | ---: | --- | --- |
| Application | 1 | `0x58` | 665,680 | `5B40B042` | 1311 |
| Bootloader | 4 | `0xA28A8` | 32,768 | `227FB5E4` | 2 |
| STM32 wireless firmware | 12 | `0xAA8A8` | 78,052 | `BDE7C6D0` | `0x010E0101` |
| Wi-Fi firmware/resource | 13 | `0xBD98C` | 437,396 | `2ABEEC19` | 0 |

The components are contiguous and end at `0x128620`; unused external-slot
padding is not part of the image. External banks begin at `0x18000` and
`0x1F4000`, with capacity `0x1DC000` each. The remaining external capacity is
735,712 bytes; that is **not** evidence of equal free internal application space.

The application runs at `0x08008000`, with initial stack pointer `0x20030000`
and reset vector `0x0801495D`. The bootloader runs at `0x08000000`. Boot output
identifies wireless firmware 1.14.1 build 1 and FUS 1.2.0. The wireless/FUS
interface and register usage identify the STM32WB platform family; an exact
chip/package identification is not required by, or established in, this pass.

Application version getter `0x08016584` reads the word at `0x080AA84C`.
The candidate updates both the descriptor and that internal version word,
adds a version word at the expanded application's tail, then recalculates the
application and header CRCs. All other components remain byte-for-byte identical.

There is no large obvious unused `0xFF` run inside the application: the longest
is only 49 bytes and may be resource data. The candidate instead expands the
application by 8192 bytes. The bootloader derives the application-space limit
from the STM32 wireless/security boundary register. Two matching UART reads of
`0x58004080` returned `0x10E0`; SFSA 224 places that boundary at `0x080E0000`.
The expanded application ends at `0x080AC850`, below it. No option bytes or
wireless firmware were changed to make room.

## Three Different Credentials

These should not be treated as one interchangeable “secret”:

| Credential | Storage / Use | What We Know |
| --- | --- | --- |
| Factory session secret | DBLIB item `3`, 17 bytes including NUL; 16 hexadecimal characters used in HTTP session hashing | Recovered independently through UART and BLE on this unregistered scale; exact match. |
| Account secret(s) | User/account records; Bluetooth account authentication | A different, longer credential. `ACCOUNT_SECRET_SET` is a setter, not a factory-secret getter. |
| TLS client identity | DBLIB `0x12B`: length-prefixed certificate; `0x12C`: 64-byte Ed25519 key material | Recovered over UART before setup. Certificate, stored public key and private seed match; authenticated vendor lookup passed. |

The UART probe returns an encoded representation, not the raw HTTP-session
secret. Its decoder checks a MAC-dependent checksum and decrypts the stored
payload. That binds the **encoded representation** to a MAC; it does not make
the independently stored raw secret computable from the MAC.

Relevant functions are raw getter `0x0806AF60`, encoded getter `0x0806AF76`,
decoder `0x08033968`, encoder `0x08033B08`, and UART probe `0x080344D0`.
This establishes pre-setup provisioning on the inspected unit, not the exact
process Withings uses to generate or register factory credentials.

## Withings Session And Firmware Offer

### Application Exchange

The firmware uses this sequence:

1. Read its server target from DBLIB item `2`.
2. Establish HTTPS, with the WBS13 server-verification callback and optional
   provisioned client identity installed.
3. POST `/once` with `action=get`; accept a nonce of 1–31 characters.
4. Form `MAC:raw_factory_secret:nonce`, hash with SHA-256, and encode as lowercase hex.
5. POST `/session` with `action=new` and the device metadata below.
6. Parse the session ID, users, settings, time triplet and any firmware offer.
7. If an offer is applied, retain its URL and decoded 20-byte SHA-1 for the
   chunked download path.

Requests append `appliver=1311&appname=WBS13&apppfm=device`.
The session form includes `auth`, `hash`, `mfgid`, `currentfw`, `batterylvl`,
`duration=600`, `wstarget=1`, `enrich=t`, `trademark`, `network=1`,
`httpslink=2`, `hashmethod=sha256`, `trigger=weather,ds`, `withaccids=1`, and
`feature_mask`. Manufacturer ID comes from DBLIB item `0x0B`; it must not
silently default to the older model's value. The firmware has a separate
conditional `final=true` suffix: do not use a setup-finalization request merely
to discover an offer.

The parser still maps **`body.syp.blc` to the firmware URL** and
**`body.syp.sha1` to the checksum**. `clu` and `wclu` are numeric status fields,
not replacement firmware-URL strings. A missing offer can mean no offered
update; it must be distinguished from authentication/session failure.

Evidence:

- Nonce exchange: `0x0804746C`.
- Session construction and POST: `0x08047C20`.
- Session-hash formatting: `0x08044CEC`.
- `blc` parser record: `0x08080128` → callback `0x08047A90`.
- `sha1` parser record: `0x08080134` → callback `0x08047A68`.
- Offer storage: `0x08048048`; chunked download/retry: `0x080480BC`.

### Why The Existing Lookup Is Not Yet Equivalent

YOW's lookup uses `https://scalews.withings.net` with ordinary public trust and
no device client certificate. It also sends the older form, without
`httpslink=2` or the `ds` trigger and with a 300-second duration. Those
differences are leads, not proof that a particular omitted field causes rejection.

The live BLE dump returned **`wbs13-ws.withings.net`** in DBLIB item `2`.
This establishes the configured target on the inspected factory-new unit,
not successful authentication against it. The application contains
`ws.withings.net` as a substring used for its optional beta-host rewrite;
item `0xD1` can insert `beta` after the matching `ws`.

The WBS13 TLS verifier at `0x080285FC` uses a compiled model-specific CA at
`0x080A9BF7` (230-byte DER certificate): self-issued `CN=WBS13`, Ed25519,
valid 2022-11-03 through 2122-11-02. The CertificateVerify callback
`0x080284DC` expects a 64-byte signature and calls the Ed25519 verifier.
This is a specialised trust path, not a browser-style public root store.

HTTPS initialization `0x0805E670` installs that verifier and calls the client
identity initializer through `0x08070F1A` → `0x08028654`. The latter loads
items `0x12B`/`0x12C` and installs a signing callback when available. A missing
client identity is logged. Live tests below confirm this unit already has the
identity and requires it for its vendor session, though `/once` works without it.

### Live Vendor Check: Client Certificate Required

On 31 October 2026, the configured hostname and `scalews.withings.net` both
resolved to the same IPv4 address, but selected different TLS certificates:
the former needed the model CA extracted from firmware; the latter verified
using the system's public trust store. Certificate and hostname verification
remained enabled. Python/OpenSSL negotiated TLS 1.3 without restricting
signature algorithms or supplying a client certificate.

Both hosts accepted `/once` with HTTP 200 / status `0`, then returned HTTP 200
for `/session` with this body:

```json
{"status":100,"body":{},"error":"Client certificate is required for this device"}
```

The requests used the BLE-read MAC/secret and manufacturer ID, firmware 1311,
feature mask 0, and battery level 100. The result was also reproduced with
stock-style literal form values, `Mozilla/4.0`, chunked POST bodies, and a single
persistent TLS connection shared by `/once` and `/session`. No `final=true`,
association, session-delete, or device writes were sent.

This establishes a client-certificate requirement rather than an inference from
status `100`. The missing-identity tests alone did not establish whether other
authentication checks passed. The subsequent UART-backed test below resolved
that uncertainty without replacing any device credentials.

As a control, the same Python probe authenticated successfully with known
WS-30/WBS03 and WBS06 credentials against `scalews.withings.net`, without client
certificates. Reporting versions 920/1180 produced firmware offers for 921/1181;
reporting 921/1181 produced accepted sessions with no offer. This validates the
shared nonce/hash exchange and offer parser for those models.

A further controlled test supplied a newly generated Ed25519 key and self-signed
client certificate, with the inspected device's MAC as its subject CN and the
client-auth extended key usage. TLS message tracing established two different
behaviors despite the shared server IP:

- `wbs13-ws.withings.net` sent a TLS CertificateRequest. The client actually sent
  its certificate and CertificateVerify signature; the server then returned
  the fatal TLS alert `unknown_ca`. No HTTP response or firmware offer followed.
  A self-signed replacement identity is therefore insufficient.
- `scalews.withings.net` sent no CertificateRequest. The configured client
  certificate was consequently not transmitted, and `/session` returned the
  same explicit client-certificate-required error as before.

Server certificate and hostname verification remained enabled in both cases.
The generated test identity stays under `local/` and is not the scale's factory
TLS identity. No device configuration or factory credentials were changed.

### UART Client Identity And Successful Firmware Offer

All three 32 KiB configuration banks were read twice through UART, with exact
matches between each pair. Bank 0 at `0x00000` contains 16 factory records;
banks 1 and 2 at `0x08000` and `0x10000` each contain 18 user records. The raw
banks, UART transcript, command log, hashes and item inventories remain private
under `local/`. Both user banks contain diagnostic mask `0` and factory-state
byte `01`. Slot headers still identify application 1311 and bootloader 2.

The factory bank contains:

- `0x12B`: 514-byte record, starting with a little-endian u16 DER length of 268.
  The Ed25519 client certificate is issued by `CN=WBS13`, valid from
  2026-01-28 through 2122-11-02. Its signature verifies with the firmware's
  model CA.
- `0x12C`: 32-byte public key followed by a 32-byte Ed25519 private seed.
  Deriving the public key from the seed matches both the stored public key and
  the certificate. A local sign/verify check also passes.

Private PKCS#8 and certificate PEM files were extracted for the lookup, without
generating or changing any key on the scale. The MAC and factory session secret
also match the earlier independent UART/BLE recovery.

With that identity, verified HTTPS to `wbs13-ws.withings.net` accepts both
`/once` and `/session` with status `0`. Reporting firmware 1311 gives no offer.
Reporting 1310 in the request gives:

```text
URL: https://wbs13-fw.withings.net/wbs13/wbs13_1311_lb2w93.bin
SHA-1: 17fe1d1979c33f2aac4fbf327e9567683075e671
```

The 1,213,984-byte download verifies against that SHA-1 and is byte-identical
to both UART firmware backups (SHA-256 above). Downloading it did not require a
client certificate. The standalone `tools/probe_withings_firmware.py` also
returned the offer with the factory host, model CA and client identity; no
special signature-algorithm restriction or chunked-request workaround is
needed. This confirms the earlier rejection was resolved by supplying the
actual client identity. No registration, setup finalization or firmware update
was performed.

### Bluetooth Device Challenge

Command `0x09B2`, handler `0x080448D0`, implements a newer ownership-proof
mechanism. Input TLV `0x09C2` carries a challenge. Function `0x0804479C`
generates 32 random device bytes and signs:

```text
request_random || device_random
```

It uses the key material in DBLIB `0x12C`; response TLVs `0x09C3` and `0x09C4`
carry the challenge metadata, algorithm code `0x0807`, and a 64-byte signature.
It returns neither the private key nor the factory secret. This gives an app a
way to prove contact with the device, consistent with a newer registration
flow. The app-to-Withings endpoint that consumes this proof is not established
by the firmware. App analysis or a controlled capture would be needed to name
it, without enrolling the factory-new device as a side effect.

## Bluetooth Secret Retrieval

### Normal Identity Does Not Provide It

Live discovery found service `00000020-5749-5448-0010-000000000000` and
protected characteristic `00000024-5749-5448-0010-000000000000`. A bonded
connection returned Body Smart, application 1311 and bootloader 2, with an empty
secret field.

Identity constructor `0x08040FFC` clears its response structure and fills the
name, MAC, manufacturer/hardware fields and versions. It never fills the
secret field. Both the normal probe and account-authentication success use
this constructor. Thus an empty response does not show that the factory secret
is absent, and repeating the same probe after authentication is not a supported
way to obtain it in this build.

Account authentication through command `0x0128` uses an account secret, not
the short factory secret. `0x0134` sets account-secret data; it is not a read
request and should not be tried as one.

### Diagnostic Dump: Confirmed On An Unregistered Unit

The ordinary WPP dispatcher contains `0x0117` (debug-mask configuration) and
`0x0118` (debug dump). Dump handler `0x08041370` tests bit 0 of the debug mask
and, if set, streams DBLIB records in 64-byte pieces, using record-selection
mask `0x7FFF`.

The record filter at `0x080713CE`, called by the actual record-copying routine
`0x08029AD8`, first applies the exclusion table at `0x08084D02`:

```text
0x0018  0x0098  0x012B  0x012C  0x012D  0x0142  0x0009  0x0126
```

**Item `3` is not excluded.** Neither are item `1` (MAC), item `2` (host), or
item `0x99` (encoding salt). TLS identity records and the Wi-Fi-settings record
are excluded.

The exclusion check (`0x08029E88`) runs before any selection-mask checks, so
changing diagnostic/selection bits cannot expose `0x12B` or `0x12C` through
this dumper. No separate Bluetooth certificate/key getter has been identified
in the inspected dispatchers. A scan of the captured record payloads also found
no complete DER X.509 certificate under another record ID. The device-challenge
command returns a signature with a fresh device nonce, not a certificate or
private key, and is not a general TLS CertificateVerify signing interface.

The checked-in offline harness executes the original filter and confirms that
item `3` is allowed, while all eight excluded item IDs are rejected. The stream
routine copies the selected record bytes; there is no additional secret-item
masking at that point in the inspected path.

The live test on 31 October 2026 completed this path:

1. Verify WBS13 v1311 / bootloader 2 and read factory-state TLV `0x012C = 01`.
2. Send `0x0117` with TLV `0x011E`, big-endian u32 `1` (DB dump only).
3. Send `0x0118` with TLV `0x0962`, big-endian u32 `0` (READ_ALL).
4. Receive section type `3`: **3,848 bytes**, exactly matching its announced
   length. Item `3` contains the raw 16-character secret plus NUL; it matches
   the UART-decoded value exactly. Item `2` contains the factory hostname.
5. Set the mask to `0`; the command is acknowledged and another dump returns
   only the terminal ACK, with no sections. Probe again: factory-state remains
   `01`, firmware and bootloader versions unchanged.

Dump framing uses TLV `0x011F` for `(section_type, size)` as two big-endian u32s,
and `0x011D` for a one-byte count followed by that many bytes (up to 64).
Several TLVs can share a WPP frame. Empty TLV `0x0100` terminates the dump.
The section contains little-endian u16 item/length records, eight-byte bank
end markers beginning with `0xFFFF`, and appended virtual records. The marker's
second u16 is not necessarily zero and must not be used as a record length.
The captured section parses completely into 53 records and two bank markers.

Enabling the dump writes DBLIB item `0x5B` through `0x0802A4DC`; it is not a
strictly read-only operation. The owner explicitly accepted resetting the mask
to zero because no Bluetooth getter for its original value has been found.
The dump itself contains the newly written `1`, not the original value.
The post-reset empty dump confirms DB export is disabled, but does not read
back every diagnostic bit. No Wi-Fi, server, account, setup-completion, or
firmware-update commands were sent. Raw sensor dump bits and their separate
acknowledgment path were not used.

This qualifies retrieval on this factory-new unit only. The dispatcher still
applies connection/account-auth gates; a registered scale may require a
different authentication flow. A product implementation also needs an explicit
policy for preserving or resetting the original diagnostic mask.

## Bluetooth Firmware Update

### Streaming Path

The existing updater's command family is present:

| Command | Role | Evidence |
| --- | --- | --- |
| `0x0401` | Start, total length and transfer negotiation | WPP handler `0x08041A54` |
| Raw transfer bytes | Write received image data to external SPI | Start `0x080217E8`, receive `0x080218C8` |
| `0x0402` | Transfer acknowledgements | Receive path |
| `0x0403` | Transfer completion indication | Completion callback `0x08021760` |

Transport construction at `0x080215DC` installs the start and receive
callbacks; this is more than a set of unused command-name strings. The same
path explicitly handles Bluetooth LE and selects an acknowledgement interval
of **15 packets**. Packet size is taken from the connection context, with a
256-byte fallback. The `0x0155` MTU exchange exists separately. Do not assume
that the macOS maximum ATT write size is the scale's accepted packet size.

Starting the transfer invokes SPI initialization/erase at `0x08038E34`.
Consequently, an empty or deliberately interrupted “START test” is not a
harmless capability probe. Validate the protocol offline and qualify the first
real transfer with a complete known image.

### Chunked Path

Commands `0x0967` (`FW_AVAILABLE`) and `0x0968` (`REQUEST_FW_CHUNK`) are
registered too, at `0x08039994` and `0x08039BB8`. They parse TLVs `0x096E` and
`0x0970`, track image/chunk metadata, and compare a SHA-1 checksum. Command
`0x0151` provides the associated reboot path at `0x08039AD8`.

The chunked implementation includes persistent download state and retry logic.
It may be a useful later choice; YOW currently uses the streaming path, which
passed the live v1311-to-v100 OTA. The
SHA-1 check is an image-integrity check, not evidence of a vendor signature.

### Bank Selection And Boot Validation

Both download paths reach the bank chooser at `0x08038CA4`; the apparent
wrapper `0x08073A3C` simply calls it. Selection considers bank validity/state,
versions, and the recorded bank. In its both-valid/state-1 case it chooses the
lower-version bank; equal versions select the other recorded bank. Other
validity/state combinations take different branches. Do not infer a target
bank from the internal application version alone.

The inspected bootloader validates the header and component CRCs, bounds the
external image, checks/copies the application, and compares copied bytes.
Relevant routines are external validation `0x0800367A`, header parsing
`0x08002560`, component CRC `0x08002460`, and application installation
`0x080001F0`.

The offline harness executes **the original external validation function** with
SPI reads and the hardware CRC driver simulated:

| In-memory Input | Result |
| --- | --- |
| Original dump | Accepted, application version 1311 |
| One changed application byte, original CRCs | Rejected |
| Same changed byte, changed descriptor version, repaired application/header CRCs | Accepted |

This supports an application patch without a Withings application-signing key
on this bootloader. That analysis test's synthetic modified image is never
saved. The later `test_build.py` also executes the original application installer
against the complete v100 candidate from both explicit OTA slots, preserving
the bootloader and protected-wireless region in emulated memory. Neither test
proves full hardware startup or changes the separate wireless/FUS update rules.

## YOW Compatibility Work

### Network And Configuration

The server-target getter at `0x080459CC` reads a configurable DBLIB
item `2`. Wi-Fi setup also resolves item `2` directly
at `0x08042D94`, so changing only HTTP URL construction would leave a second
vendor-target dependency during setup.

Both consumers read into **64-byte host buffers**, but the downstream stock
URL parser uses a 50-byte host field. The candidate therefore limits provisioning
to **48 ASCII bytes**. Its tests execute that stock parser and confirm the full
48-byte host survives. Live HTTP to a LAN address and HTTPS to a Cloudflare Worker
hostname also passed. The exact 48-byte boundary has only been tested offline.

The request builder `0x08045B38` supports HTTP and HTTPS formats, but the
normal session call selects HTTPS. The candidate adds an explicit transport
setting covering provisioning-time DNS as well as normal sync.

Changing the hostname alone does not make the stock TLS verifier trust a
Cloudflare endpoint. The candidate adopts the existing WBS06 policy for owner
targets: encrypted TLS without server-certificate authentication. It handles
common signature algorithms, servers declining MFL, and encrypted records up to
4096 bytes. Factory client credentials are withheld from owner servers. With
no owner record, factory TLS behavior is preserved. Authenticated owner HTTPS
would require a separate trust/verification implementation.

The stock code includes Wi-Fi scan, stored-settings reads, connection tests,
time configuration and setup completion. Reuse their protocol structure after
checking WBS13 payloads and results. Keep factory personalization, client keys,
calibration, and account-association commands out of an initial owner-host patch.

### Measurement Protocol And Server Changes

The upload remains **`POST /measure`, `action=batchstore`**. The separate
`POST /v2/measure`, `action=getlastupdate&objects=devices`, queries update state;
it is not the normal upload endpoint. These must not be conflated based on the
presence of the string `v2/measure` in the image.

Upload functions `0x080471E8` / `0x08047290` use serializer `0x08046AE8`.
Its form includes session ID, MAC, user IDs, device/category/attribution and
JSON `measuregrps`. It emits:

- A weight group with timestamp, algorithm ID, and type `1`, unit `-3`.
- Additional conditional measurements in that group, including `position`
  metadata and model-specific numeric type IDs.
- Additional groups at the same timestamp, without necessarily repeating
  weight; one branch emits type `11`, unit `0`.

It streams the form through a bounded output buffer, rather than requiring
one complete JSON body in RAM. Multiple chunks are not necessarily multiple
HTTP requests. A single upload can hold multiple measurement groups; queued
records can also result in several requests. Shared code for impedance, heart-rate,
vascular and other metrics is not by itself proof of the model's enabled
hardware/features.

The first live v100 capture on 31 October 2026 contained one `/measure` request
with one group: `algo:0`, weight type `1`, unit `-3`, and no `userid`. No
additional metrics were present. The sequence was `/once`, `/session` new,
`/v2/event` (type 116), `/v2/summary`, `/measure`, `/v2/measure` last-update,
`/v2/screen`, `/v2/feature`, then `/session` delete. All exchanges received
HTTP 200 / status 0. This establishes complete HTTP synchronization using the
minimal empty-roster capture profile.

A subsequent test on the same day provisioned a user with `cs:"2,1,3"`. The
first weigh-in was unassigned; the next was recognised and uploaded a single
`/measure` request containing **two groups at the same timestamp**:

- Weight and body composition: types `1`, `5`, `8`, `76`, `77`, `88`, `170`,
  `226` and `227`, alongside raw types `177`, `178`, `189`, `201`, `202`, `203`
  and `207`. This group includes `algo`; most non-weight items include
  `position:6`.
- Heart rate: type `11`, unit `0`, in its own group without weight or `algo`.

The documented types correspond to weight, fat-free mass, fat mass, muscle mass,
water mass, bone mass, visceral fat index, basal metabolic rate, metabolic age
and heart rate ([Withings measurement types](https://developerbeta.withings.com/api-reference/)).
The scale therefore uploads calculated body-composition values directly; the
server need not derive them from the raw impedance-related fields. Keep unknown
types and metadata intact rather than assigning unverified meanings. The final
fat calculation has since been reproduced independently: see
[Body-Fat Calculation](BODY_COMPOSITION.md) for exact inputs, the reference
implementation, firmware-equivalence checks and the limits of server replay.

Both sessions completed `/once`, `/session` new, `/v2/summary`, `/measure`,
`/v2/measure` last-update, `/v2/feature`, and `/session` delete. Neither requested
`/v2/screen` in this run. This confirms acquisition and HTTP upload using the
session's test roster; it does not independently hardware-test the screen reply.

Current YOW integration status:

1. WBS13 identity/model recognition and source-hash/container validation are
   implemented for stock 1311 / bootloader 2 and YOW 100.
2. WBS13 session authentication uses SHA-256 of `auth:secret:nonce`, verified
   against both captured session requests using the independently recovered
   secret. Its response profile is selected from the enrolled model.
3. Import v100 through the bridge or a device export, then explicitly select
   one to eight local users in Scales → Edit Settings. The server sends this
   roster and the tested minimal settings/display profile; it does not attempt
   the older models' MAC/secret-only Withings import.
4. The server handles the captured `/v2/measure` last-update and `/v2/feature`
   queries. All 14 requests from the two-session capture passed an isolated
   application replay with fresh nonces and session tokens.
5. Measurement persistence accepts metric-only groups and preserves `algo`,
   `position` and unknown fields. The general [readings API](../../../contracts/readings/v1/README.md)
   exposes these groups, while the existing weight API and Apple Health queue
   filter out groups without weight. Metric selectors show only observed types.
6. Hardware validation covers OTA, setup completion, unset-settings readback,
   unassigned HTTP weight upload and recognised body-composition/heart-rate
   upload to the capture listener. Direct HTTPS sync to the YOW Cloudflare Worker
   also passed, including local-user roster adoption and persistence of new and
   previously queued measurements. WBS13 is a supported model; the bridge
   restricts operations to the reviewed identity and firmware versions.

For further protocol exploration, capture complete request/response bodies using
the diagnostic listener, and preserve unknown metric fields.
Do not acknowledge a measurement payload that has not been durably stored.
Also distinguish a successful HTTP exchange from successfully completing the
scale's sync state machine.

The standalone [WBS13 capture listener](../../../tools/README.md#wbs13-conversation-capture)
records complete HTTP plaintext and responds with an explicit experimental
profile. Stock parser execution confirms that omitting timezone, diagnostic
mask (`ind.stp`) or feature mask (`ind.fm`) is not settings-neutral: the session
apply routine applies zero values. Other omitted scalar settings are left
alone, but **omitting `sp.users` does not preserve an existing roster**: session
finalization creates an empty replacement. Empty screen/feature replies can
also clear their tables. Use the capture listener for controlled diagnostic
experiments with an explicit empty or test roster.

### User Roster Initialization

Flashing v100 does not provision people. The normal roster arrives in
`body.sp.users` of the `/session` response and is persisted in DBLIB item `5`.
The table has eight slots of `0x17E` bytes each (`0xBF0` bytes total). Parsed
fields include `id`, `sn`, `fn`, `ht` (metres), `agt` (years), `sx`, `wt` (kg),
`fm`, `cr`, `att` and `cs`. A populated server response can create the table or
update it using the existing firmware path; no additional firmware patch or
Withings account registration is needed for that operation.

The successful-session wrapper performs an essential step after JSON parsing:
`0x08047D82..84` calls finalizer `0x080754A6`, which calls the user callback
`0x08047948`. This flushes the last parsed user and allocates the table even
when no users were supplied. Then `WsLib_Connect` calls apply routine
`0x08047568` at `0x08047DFA`. Missing DB5 is created through `0x080293A0`
at `0x08047930`; an existing changed table is replaced through `0x080293FC`
at `0x080478EE`. Omitted users and `users:[]` both produce an empty table.

Before its first successful sync, the factory-new test unit had **no DBLIB item 5
(user table)**. The connection
manager reads that item at `0x0802663E`; failure bypasses the measurement helper
`0x0802606C`. A successful session initializes the table before this check, so
an empty table is sufficient to reach the helper. The serializer supports an
unassigned reading without a `userid`; a fake person is not required.

Offline execution in both stock 1311 and the v100 candidate verified empty
initialization, one/eight-user initialization with the expected stored fields,
roster replacement, and the upload-gate branch with absent, empty and populated
tables. Storage and an empty measurement queue were simulated. A subsequent
live capture confirmed an unassigned weight upload with this response profile.
An explicit test roster subsequently enabled recognition, body composition and
heart rate on the same unit, without Withings registration. WBS13 local enrollment
now provisions users selected explicitly in Scales → Edit Settings. The standalone
listener still stores its uploads only in capture files, not in the YOW database.

### Measurement Screens For A Test Roster

The screen list controls measurement acquisition, not just display. Original
routine `0x08013E44` returns zero for an empty list (logging "No screen list,
skip measures"). Embedded screen `1` sets bit 0, used to enter the BIA path at
`0x080124F6`; screen `3` sets bit 1, used for heart rate at `0x08012676`.
The list `2,1,3` returns mask `3`. Body-composition screens `14`, `15`, `16`
and `22` also set bit 0.

Provisioning `sp.users[].cs` alone is insufficient if a subsequent screen
response is empty. The `/v2/screen` wrapper clears each user's 128-byte list
before parsing (`0x08048546..6E`). The diagnostic listener therefore derives
`body.user[].screens` from each user's `cs`, using `src:1`, the embedded ID and
one-based `rk`. Running the original session parser/finalizer, screen parser/
finalizers and measurement gate in stock 1311 and YOW v100 confirmed the list
survives and requests both measurement paths. Empty screen replies cleared it
in the same check. A subsequent live test with this session roster produced a
recognised weigh-in containing body composition and heart rate. That run did
not request `/v2/screen`, so the separate screen-response path remains verified
offline only.

## Next Experiments

1. **Configuration persistence:** check configured hostname/SSID readback after a
   cold restart, followed by another sync. HTTP and direct HTTPS synchronization
   are already validated. UART write recovery remains unqualified on this model.
2. **Bluetooth transports:** exercise WBS13 pairing, provisioning and OTA through
   the Linux Bleak/BlueZ backend. The shared BLE path is implemented, but WBS13
   hardware tests so far used macOS. This does not require different firmware or
   server support.
3. **Registered-device access:** qualify the existing Bluetooth authentication
   gates on a registered scale. The live diagnostic work and factory-state
   observations apply to the unregistered test unit.
4. **Optional Withings roster import:** investigate the required client identity,
   available only through UART so far. Existing YOW users already work; the patched
   Bluetooth identity returns the factory secret but not the TLS client identity.

The BLE test establishes UART-free factory-secret retrieval on this
unregistered unit. The vendor lookup additionally needs its TLS client identity,
which has only been recovered through UART. Registered-device access remains
unqualified.

## Reproducing The Offline Checks

Install Unicorn in a development environment and run:

```sh
python firmware/wbs13/v1311/verify_analysis.py /path/to/wbs13_fw1_v1311.bin
```

The script refuses any other source hash. It executes the DBLIB selection
filter and bootloader validator, reports results as JSON, and performs no
hardware/network access or firmware output. The existing UART-container tests
remain separate:

```sh
python3 -m unittest discover -s tools -p test_dump_wbs13_firmware.py
```

The evidence establishes these specific paths in **v1311 / bootloader 2**.
Later WBS13 images, previously registered devices, and other models require
their own qualification.
