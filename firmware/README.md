# Firmware Patches

Sources are grouped by scale model and **stock firmware version**. End users generate firmware through the Python bridge's compiler-free recipes. These maintainer builders compile the original patches, validate stock/output hashes and regenerate container CRCs.

| Model | Stock / Bootloader | YourOwnWeigh Release | Maintainer Build |
| --- | --- | --- | --- |
| Body WBS06 | 1181 / 4 | 127 | [WBS06](wbs06/v1181/README.md) |
| WS-30 / WBS03 | 921 / 15 | 102 | [WS-30](ws30/v921/README.md) |
| WS-50 / WS50 | 1721 / 12 | 1022 (experimental) | [WS-50](ws50/v1721/README.md) |
| Body Smart WBS13 | 1311 / 2 | 103 | [WBS13](wbs13/v1311/BUILD.md) |

Other models and stock versions are unsupported. Vendor firmware and complete patched images are not distributed. The small startup-face `.bin` resources are original artwork.

[WBS13 / Body Smart v100](wbs13/v1311/BUILD.md) passed Bluetooth OTA, setup,
local-user roster adoption, HTTP capture and direct HTTPS sync to the YOW
Cloudflare Worker on 31 October 2026. Weight, body composition, heart rate and
previously queued readings were stored successfully. The firmware image and
server protocol are independent of the bridge computer's operating system;
platform-specific Bluetooth checks are recorded in the
[hardware checklist](../docs/hardware-acceptance.md). Factory-reset previously
Withings-registered WBS13 devices before setup. The
[analysis](wbs13/v1311/README.md) documents the container, protocols and
independently reproduced body-fat calculation.

WBS13 v103 adds a native-resolution smiley startup screen to v100. Its framebuffer and
firmware checks pass offline; the maintainer confirmed the new smiley works on the
physical scale on 31 October 2026.

Keep model, source hash, section layout and bootloader checks explicit. After changing a patch, regenerate its bridge recipe with `tools/package_firmware.py` and test both the compiler build and compiler-free output. See [contributing](../CONTRIBUTING.md).

## Device Constraints

[Hostname limits](Hostname-DNS-limits.md) apply even when Bluetooth can save a longer value. WBS06 and WBS13 support HTTP and HTTPS; WS-30 supports HTTP only. WBS06 and WBS13's patched TLS encrypts traffic but does not authenticate the server certificate or CertificateVerify signature.

Keep firmware backups and a recovery route before OTA. The application runs from internal flash, while radio resources can still be read from an external bank. OTA destination selection and boot selection are separate decisions. With valid gold-marked WBS06 slots, the observed updater chooses the lower-version slot; flags and validity affect other cases. Bluetooth neither exposes nor controls that choice. Use [model-specific UART tools](../tools/README.md) when exact bank contents matter.

CRCs and pinned hashes detect corruption and unintended changes; they are not vendor signatures.
