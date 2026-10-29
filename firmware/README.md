# Firmware Patches

Sources are grouped by scale model and **stock firmware version**. End users generate firmware through the Python bridge's compiler-free recipes. These maintainer builders compile the original patches, validate stock/output hashes and regenerate container CRCs.

| Model | Stock / Bootloader | YourOwnWeigh Release | Maintainer Build |
| --- | --- | --- | --- |
| Body WBS06 | 1181 / 4 | 127 | [WBS06](wbs06/v1181/README.md) |
| WS-30 / WBS03 | 921 / 15 | 102 | [WS-30](ws30/v921/README.md) |

Other models and stock versions are unsupported. Vendor firmware and complete patched images are not distributed. The small startup-face `.bin` resources are original artwork.

Keep model, source hash, section layout and bootloader checks explicit. After changing a patch, regenerate its bridge recipe with `tools/package_firmware.py` and test both the compiler build and compiler-free output. See [contributing](../CONTRIBUTING.md).

## Device Constraints

[Hostname limits](Hostname-DNS-limits.md) apply even when Bluetooth can save a longer value. WBS06 supports HTTP and HTTPS; WS-30 supports HTTP only. WBS06's patched TLS encrypts traffic but does not authenticate the server certificate or CertificateVerify signature.

Keep firmware backups and a recovery route before OTA. The application runs from internal flash, while radio resources can still be read from an external bank. OTA destination selection and boot selection are separate decisions. With valid gold-marked WBS06 slots, the observed updater chooses the lower-version slot; flags and validity affect other cases. Bluetooth neither exposes nor controls that choice. Use [model-specific UART tools](../tools/README.md) when exact bank contents matter.

CRCs and pinned hashes detect corruption and unintended changes; they are not vendor signatures.
