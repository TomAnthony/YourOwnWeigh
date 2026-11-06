# WBS05 / Body+ v1651 analysis

**Assessment: a strong candidate for the same YOW functionality as WBS06 and
WBS04.** The firmware shares their container, Bluetooth command family, URL
builder and TLS implementation. Its composition measurements already match
YOW's grouped-measurement format. The main difference is limited application
flash space: the injected code needs a combined, size-optimized layout.

This directory contains the **v100 candidate builder and offline tests**, plus
the stock analysis. Findings combine disassembly, execution of original ARM
routines with synthetic inputs, compilation, and the earlier read-only
UART/vendor-server checks. The maintainer reports successful Bluetooth OTA to
v100, hostname/protocol reads and writes, and Wi-Fi setup on hardware. End-to-end
HTTP/HTTPS weigh-in sync remains unqualified. Bridge 0.4.9 and web app 0.4.11
enable enrollment and local user selection for that next hardware test.

## Candidate v100

The candidate combines persistent owner hostname/HTTP/HTTPS settings, WPP
command `0x170`, the existing YOW TLS compatibility fixes, vendor-triggered
OTA suppression, and the WBS06 smiley. Bluetooth OTA is retained. The firmware
itself enforces the 48-byte hostname limit. Factory data, measurement algorithms,
radio components and bootloader are preserved.

| Property | Candidate |
| --- | --- |
| Output | `local/firmware/wbs05/wbs05_yow_100.bin` |
| Version | 100 (header, descriptor, runtime getter and application tail agree) |
| Length | 923,276 bytes |
| SHA-256 | `0fb9543739ca4c17eadcb2225ae3b1ee0d48b136bdf57507b1f9c2206ed1b483` |
| Application end | `0x7fd28` |
| Space before reserved manufacturer word | 720 bytes |
| Spare bytes inside the extension, before the version tail | 250 bytes |
| Compilation used for this candidate | Apple Clang 21.0.0, Cortex-M4 Thumb, soft ABI, `-Oz` |

The builder also writes `.candidate.json` metadata and a `.recipe.json`
compiler-free patch recipe beside the image. The bundled
[`WBS05.json`](../../../bridge/src/yow_bridge/firmware/recipes/WBS05.json)
recipe reproduces the pinned candidate through the normal bridge engine.
Choose **Body+ (WBS05)** in Firmware Bridge, generate firmware, then connect
the scale and use **Send Update To Device** with the normal `FLASH` confirmation.
After reconnecting, the identity should report v100. Hardware qualification
is still pending; the firmware panel labels this image as a candidate.

### Build and verify

Use the exact stock image identified below. Clang is needed only by the
maintainer builder, not by bridge recipe generation.

```sh
python3.11 -m venv local/wbs05-analysis-venv
local/wbs05-analysis-venv/bin/pip install -r firmware/wbs05/v1651/requirements.txt
local/wbs05-analysis-venv/bin/python firmware/wbs05/v1651/test_owner_target.py local/firmware/wbs05/wbs05_1651_LJ24pf.bin
local/wbs05-analysis-venv/bin/python firmware/wbs05/v1651/test_tls_http_read.py local/firmware/wbs05/wbs05_1651_LJ24pf.bin
local/wbs05-analysis-venv/bin/python firmware/wbs05/v1651/test_build.py local/firmware/wbs05/wbs05_1651_LJ24pf.bin
local/wbs05-analysis-venv/bin/python firmware/wbs05/v1651/build.py --source local/firmware/wbs05/wbs05_1651_LJ24pf.bin
```

Add `--check-only` to compile and validate without writing artifacts. An
existing different output is never overwritten. The builder rejects an
incorrect stock hash, unexpected patch-site bytes, extension overflow,
inconsistent versions/CRCs, altered radio/boot bytes and unexpected changes
outside the declared patches. Its output hash may change with a different
compiler; the table records the candidate produced with the compiler above.

The offline tests exercise the actual compiled owner handler through the stock
WPP dispatcher, direct and ATT20-sized staged writes/readback, malformed
commands, setup gating, failed persistence and the URL wrapper ABI. Receive
tests cover large plaintext records, allocation/read failures, freeing and both
stock-loop continuations. The actual candidate passes the original bootloader's
validator and copier for both slot locations in emulation, preserving a sentinel
at the reserved flash word. Signature-list generation, fragment negotiation,
the runtime getter and portable recipe round-trip also pass. Hardware-dependent
calls are stubbed: these tests do not replace a first physical OTA and sync.

Files: `constants.py` pins model addresses; `codegen.py` compiles relocation-free
ARM sections; `build.py` assembles and packages the single extension;
`owner_target.c` and `tls_http_read.c` contain the injected code. The remaining
sections document the stock analysis and outstanding integration work.

## Parity assessment

| Capability | Evidence and remaining work |
| --- | --- |
| BLE discovery and identity | WBS05 UUIDs and the exact Body+ / bootloader 6 / hardware `0xffffff` profile are registered. The normal probe supplies the factory secret. Live connection used for the successful OTA. |
| Read/write hostname and HTTP/HTTPS | Owner command and target hook built and emulated, including staged writes and failure paths. Maintainer reports hardware reads and writes working. |
| Wi-Fi, clock and Complete Setup | Wi-Fi setup confirmed after the server probe fix described below. Clock and Complete Setup still need hardware checks. |
| Bluetooth OTA | Original bootloader accepts and copies the actual v100 candidate in emulation. Maintainer reports successful OTA and boot on hardware. |
| HTTP sync | SHA-256 authentication, local roster, screen/summary/weather responses and grouped `/measure` ingestion pass server integration tests. Hardware weigh-in sync remains to be checked. |
| HTTPS sync | WBS06/WBS04 signature-scheme, record-size and HTTP receive-buffer fixes ported; receive/error paths emulated. Needs real TLS/sync qualification. |
| Weight and composition | Weight, impedance, fat, water, bone and muscle values serialized together. Existing server metric support covers the mass values. |
| User roster and recognition | Import and choose local household users in Scales → Edit Settings. Server tests cover roster delivery on each session and recognition-weight updates. Physical adoption and recognition remain to be checked. |
| Startup smiley | Same-size WBS06 smiley included; descriptor and dimensions unchanged. |

## Exact stock image

- Model: **WBS05**, Bluetooth name **Body+**.
- Application: **1651**; runtime version getter and application-tail word agree.
- Application build string: **2021-09-24 10:45:48+02:00**.
- Bundled bootloader: **6**; build string **2018-11-27**.
- Download: <http://cdnfw.withings.net/wbs05/wbs05_1651_LJ24pf.bin>.
- Length: **919,180 bytes**.
- SHA-1: `8784587d3df5bb645c2c21ee4dc569c762e1e87d`.
- SHA-256: `6bb1e5a6e70853886144b2b73c15450aae0077c60fc243b957dc291c8600efcc`.

The downloaded header and sampled application tail match the installed v1651
slot. This was not a full byte-for-byte comparison with both installed slots.
No vendor firmware or device credentials are included in this directory.

### Container and flash layout

This is the older four-component container, with header, descriptor and
whole-file CRCs. Radio component CRCs include alignment padding even though
their size fields exclude it.

| Component | File offset | Length | Version | CRC-32 |
| --- | --- | --- | --- | --- |
| Application | `0x84` | `0x7ad28` (503,080) | 1651 | `0e3cc855` |
| Wi-Fi firmware | `0x7adac` | `0x58d1d` (363,805) | 0 | `8dc2465e` |
| Bluetooth firmware | `0xd3acc` | `0x8bb9` (35,769) | 0 | `37e5fffe` |
| Bootloader | `0xdc688` | `0x4000` (16,384) | 6 | `cc327c8d` |

The application runs at `0x4000`, ending at `0x7ed28`. The bootloader erases
the application region up to `0x80000` and uses a manufacturer word at
`0x7fff8`. There are **4,816 bytes** between the current application end and
that reserved word. The existing two separate 4 KiB extensions cannot simply
be copied across from another model.

A compile-size trial using the WBS04 owner handler and TLS receive helper,
relocated to WBS05 helper addresses and compiled with Apple Clang 21 `-Oz`,
gave this budget:

| Addition | Bytes |
| --- | ---: |
| Relocated command table | 96 |
| Owner configuration code | 3,592 |
| URL wrapper | 22 |
| TLS receive helper and wrapper | 130 |
| Signature-scheme list | 26 |
| New application-tail version | 4 |
| Alignment allowance | 16 |
| **Total** | **3,886** |

That fits one **4,096-byte extension**, ending at `0x7fd28`, with 720 bytes
remaining before the manufacturer word. The corresponding `-Os` trial was
4,242 bytes and did not fit that extension. This is a feasibility measurement,
not a final linked and tested patch: the builder must assert the actual size,
branch reach and all section boundaries. The portable bridge recipe can still
apply precompiled patch bytes without requiring Clang on the user's machine.

## Bluetooth, configuration and OTA

### Wi-Fi provisioning and persistence

The shared `device.connect_wifi` command both connects and saves; it does not
need a separate write command. WBS05's Wi-Fi-only setup path (`0x103`, with
credentials in TLV `0x104` and empty TLV `0x113`) joins the network, resolves
the configured server and posts `action=probe` to `/once`. It saves the new
credentials only after that probe returns a successful JSON status.

The stock callback at `0x42d4c` invokes the connectivity check at `0x42c88`,
which calls the web probe at `0x45f3c`; failure skips the save at `0x60e02`.
Consequently, successful join/DHCP status can coexist with readback of the
previous owner's SSID. YOW web app 0.4.10 adds the stateless `{ "status": 0 }`
probe response and distinguishes connection success from matching stored SSID
in the UI. The maintainer confirmed Wi-Fi setup working after that fix; it
needs no additional firmware patch.

SSID readback does not verify password persistence. A password change for the
same network can join successfully, fail the web probe and retain the old
credentials while still returning a matching SSID. Web app 0.4.12 reports the
SSID match and explicitly leaves password saving unverified; it does not infer
"Settings Saved" or recommend Complete Setup from those two observations.

### GATT identity

The bridge already knows the WBS05 GATT pair:

```text
Service:        00000020-5749-5448-0005-000000000000
Characteristic: 00000024-5749-5448-0005-000000000000
```

The bridge promotes this initially identity-only connection to WBS05 only when
the Body+ name, bootloader 6 and hardware `0xffffff` also match. OTA is enabled
for stock v1651 and candidate v100. Other firmware versions remain read-only.

The normal probe builder at `0x417b8` calls the factory-secret accessor at
`0x547be`, which reads DBLIB item 3. Executing these routines with synthetic
factory values confirms that the resulting identity structure contains the
secret, bootloader 6, firmware 1651 and hardware field `0xffffff`. There is no
need for the WBS13 diagnostic-dump approach. This check exercises the builder;
it does not emulate Bluetooth bonding or the physical-setup authentication gate.

The main WPP dispatcher is at `0x420fc`. Relevant commands include identity
`0x101`, Complete Setup `0x113`, OTA start `0x401`, and time `0x501`.
The Wi-Fi dispatcher at `0x42f04` handles `0x104` reads and `0x103` writes.
OTA start at `0x41cb0` joins the existing stream updater; its transport path
emits `0x402` acknowledgments and a final `0x403` response. These are compatible
in shape with the current bridge implementation; actual MTU, timing and
reconnection behavior still need a device test.

The stock bootloader's validator (`0x1778`) and application copier (`0x470`)
were executed for both external slot addresses, `0x18000` and `0x1a8000`:

- Stock image: accepted and copied correctly.
- Modified application with stale CRCs: rejected.
- Same modification with repaired CRCs: accepted and copied correctly.
- Synthetic 4 KiB application expansion with repaired descriptors/CRCs:
  accepted and copied through `0x7fd28`, without changing bootloader bytes.

These executed paths show no additional application-signature requirement.
The emulator substitutes SPI, CRC and flash-controller operations, so this
establishes image/installer behavior rather than successful physical boot.

The updater's destination selector (`0x5fbd2`, wrapper `0x5fc22`) chooses the
lower-version external slot when both are valid and gold-marked; ties choose
bank 1. The inspected device has 1651 in bank 1 and 1511 in bank 2. A first
low-version YOW image would replace 1511; subsequent low-version YOW updates
would continue using that slot while 1651 remains higher. This describes the
updater's destination choice, not the bootloader's startup-selection policy.

### Owner settings port

Use the WBS04 owner handler as the closest starting point. In particular,
WBS05's WPP reply length lives at **offset `0xc0`**, with a `0xc4`-byte reply
buffer; the smaller WBS06 reply layout is incorrect here.

| Purpose | WBS05 v1651 runtime address |
| --- | --- |
| DBLIB get / set | `0x2b9c4` / `0x2b934` |
| Setup-state getter | `0x1a1b4` |
| WPP context / reply / reply initialization | `0x425bc` / `0x419b4` / `0x60e54` |
| Existing extension table | `0x44b0`–`0x4504` (seven 12-byte entries) |
| Extension dispatcher | `0x43db4` |
| Table start / end literal locations | `0x43dec` / `0x43de8` |
| HTTP URL builder / hostname call site | `0x45300` / `0x45358` |
| Transport comparison | `0x45360` |
| Runtime version getter | `0x19db8` |

Port the existing guarded `0x170` owner command, persistent hostname and
transport, and setup-only write semantics. Recheck DBLIB allocation before
adopting the existing custom items `0x1f0` and `0x1f1`; the stock command table
has no `0x170` entry.

The original URL parser (`0x2eeb4`) supports HTTP and HTTPS, defaulting to ports
80 and 443. Offline tests show 48- and 49-character ASCII hosts round-trip;
50 characters are silently truncated to 49. Keep YOW's conservative **48-byte
hostname limit** and validate before saving. The normal owner configuration
remains a hostname plus transport, with no custom-port setting.

Disable the vendor update handoff at `0x46bd6` and automatic update driver at
`0x473f8` when porting the owner patch. Bluetooth OTA should remain available.

## HTTPS port

The stock TLS implementation has the same relevant limitations as the earlier
WBS06/WBS04 implementation. It is not enough to change the hostname:

| Required change | WBS05 v1651 location |
| --- | --- |
| Broaden the Ed25519-only ClientHello signature schemes | Writer `0x4b12e`; byte writer helper `0x6235c` |
| Port the existing server certificate / CertificateVerify policy | `0x4c568`; branches at `0x4c716`, `0x4c732`, `0x4c75c` |
| Accept a server declining max-fragment-length negotiation | Check at `0x4c1d8` |
| Raise the two encrypted-record limits from 800 bytes | `0x4cd4a`, `0x4cdee` |
| Stage decrypted data before the HTTP parser | Hook `0x2ee0c`, stock TLS reader `0x4e26c`, parser `0x7910` |
| Allocation / free for the receive helper | `0x513fc` / `0x5140c` |
| Receive-hook error / success continuation | `0x2ee18` / `0x2ee70` |

The verifier reproduces the receive bug directly: when the caller requests
512 bytes and the simulated TLS engine supplies 518 decrypted bytes, the
original reader returns and copies all 518, overwriting six guard bytes.
The existing scratch-buffer fix is therefore relevant to WBS05 too. Port the
4 KiB encrypted-record allowance and 6 KiB receive staging buffer together,
then repeat the existing parser/error-path tests at the new addresses.

Matching the current WBS06/WBS04 HTTPS policy means encrypted transport
without CA/hostname authentication of the server. Supporting authenticated
server TLS would be a separate enhancement, rather than a prerequisite for
parity with those models.

## Measurement format and calculations

The stock serializer at `0x45b58` is used by the `/measure` request path at
`0x45d4c`. It sends a form with `action=batchstore`, session/device/user fields,
and `measuregrps` containing an array of timestamped groups. **Weight and body
composition from one reading are in the same group and HTTP request.** The
serializer also supports multiple readings in one request.

Executing it with synthetic records produces:

| Measurement | Type | Unit exponent | Example encoded value | Meaning |
| --- | ---: | ---: | ---: | --- |
| Weight | 1 | -3 | 75250 | 75.25 kg |
| Impedance | 16 | 0 | 543 | 543 ohms |
| Fat mass | 8 | -2 | 1850 | 18.50 kg |
| Water mass | 77 | -2 | 4200 | 42.00 kg |
| Bone mass | 88 | -2 | 300 | 3.00 kg |
| Muscle mass | 76 | -2 | 5300 | 53.00 kg |

The test also covers recognized weight-only readings, unrecognized weight-only
readings and a two-reading composition batch. The streaming serializer returns
several chunks to the HTTP sender; these are not separate HTTP requests.

Unlike a device that uploads only raw impedance, **this firmware already
calculates and sends the composition masses**. Its on-device calculation path
at `0x18480` calls `0x5a364` and `0x4b78`, using the recognized user and sensor
data, and stores the values consumed by the serializer. We do not need to
reimplement those formulas to receive the same masses in YOW. Exact formulas
and age/eligibility rules were not reconstructed in this pass.

The server's metric catalog already handles types 1, 8, 76, 77 and 88, and
preserves unrecognized metric types such as impedance in group metadata.
No new measurement-table format is required. This serializer does not emit
heart rate, PWV or vascular age. It also does not emit a separate fat-percentage
type 6 value: deriving that from fat mass and weight could be added separately.

## Vendor authentication and YOW enrollment

The earlier UART check found factory MAC/secret, a client certificate and its
matching Ed25519 key. The factory host is `wbs05-ws.withings.net/cgi-bin`.
The authenticated vendor exchange succeeded with the model CA, client
certificate/key and Ed25519 signature-scheme negotiation. Reporting version
1650 returned the v1651 download offer; reporting 1651 returned no newer offer.

The application uses the usual `/once` → `/session` exchange, with
SHA-256 over `MAC:secret:nonce` and firmware offers in `syp.blc` / `syp.sha1`.
The stock hash routine at `0x441d8` was verified against Python's SHA-256 with
synthetic credentials. The observed session body contains `sessionid`, `sp`,
`ind`, `syp`, `ctp` and `color`, with `sp.users` and `sp.accountids`.

The client certificate is needed for the vendor path we tested, **not for
ordinary YOW enrollment or sync**. The bridge can obtain the MAC/secret via
the normal probe, and YOW can supply its own user roster as it does for WBS13.
Do not make UART extraction of client credentials a prerequisite for adding
a WBS05 to YOW. Existing Withings-user migration needs separate handling:
the current generic `scalews.withings.net` capture adapter has not been
qualified for this model's authenticated endpoint.

Bridge 0.4.9 and web app 0.4.11 enable the automatic **Import Device** offer and
manual link, plus file import. On the Scales page, use **Edit Settings** to
choose one to eight local users and the time zone. The server then supplies
that roster each session, with generated weight/composition display settings,
an empty historic summary and suppressed weather. The initial feature/unit
defaults (`fm=3`, `tmp=11`, `w=1`) match the observed stock vendor session.
User imports and existing household profiles are not changed automatically.
Server integration tests cover this flow and ingestion of the six grouped
metrics emitted by the stock serializer; hardware sync is the next check.

## Startup artwork

The Hello bitmap at runtime `0x7cd75` (file `0x78df9`) is 148 bytes, 37 × 26
pixels, and matches the WBS06 source bitmap exactly. Its descriptor is at
`0x68b18` (file `0x64b9c`). Reuse the same-size WBS06 smiley replacement;
no additional rendering code or expanded artwork storage is necessary.

## Implementation and qualification sequence

1. **Candidate complete:** strict stock/patch-site checks and a single 4 KiB
   extension for the owner handler, table, TLS receive code and signature list.
   The startup bitmap is replaced and vendor-triggered OTA disabled. Radio and
   bootloader bytes are preserved; CRCs and all version words are consistent.
2. **Offline checks complete:** owner-handler and TLS receive emulation,
   including allocation failures, malformed commands, settings persistence and
   large responses. The portable recipe reproduces the candidate exactly and
   passes the bridge inspector with the bundled model recipe.
3. **OTA registration complete:** bridge identity/capabilities, contracts,
   simulator, portable recipe and web model metadata include WBS05. The firmware
   handles the `0xc0` reply layout; v100 advertises HTTP and HTTPS configuration.
   Stock v1651 and candidate v100 are the reviewed OTA starting versions.
4. **Server integration complete:** local enrollment/roster, session, screen,
   summary and weather paths have automated coverage, including grouped
   measurement storage and API reads. Verify the replies on physical hardware.
5. **Hardware OTA and configuration started:** OTA, hostname/transport and
   Wi-Fi setup passed. Check clock, Complete Setup and persistence after reboot.
6. Capture an HTTP setup and recognized barefoot weigh-in, then repeat over
   HTTPS to the Worker. Compare weight and all emitted composition values with
   YOW's stored/API values. Exercise an unrecognized reading, assignment and
   subsequent roster recognition, then a second OTA to confirm repeat updates.

The firmware image is shared across host operating systems. Bluetooth transport
behavior and the firmware/server behavior should be recorded separately when
qualifying the bridge on macOS and Linux.

## Reproduce the offline checks

From the repository root, using your own copy of the exact stock image:

```sh
python3.11 -m venv local/wbs05-analysis-venv
local/wbs05-analysis-venv/bin/pip install -r firmware/wbs05/v1651/requirements.txt
local/wbs05-analysis-venv/bin/python firmware/wbs05/v1651/verify_analysis.py \
  local/firmware/wbs05/wbs05_1651_LJ24pf.bin
```

The verifier prints JSON covering hashes/CRCs, runtime version, session hashing,
bootloader acceptance and copy bounds, slot selection, probe identity, hostname
lengths, the TLS receive overflow, and measurement groups. It only accepts the
pinned stock image. Device identity and measurement inputs are synthetic, and
modified firmware containers exist only in memory. It does not access hardware,
contact a server or save a modified image. Run it without Python's `-O` flag,
because the checks deliberately use assertions.

Addresses above are application/bootloader runtime addresses, not file offsets.
For the original application, file offset = runtime address − `0x4000` + `0x84`.
