# WS-30 / WBS03 v921 → v102

The patch adds a persistent owner hostname, redirects Wi-Fi HTTP requests to it and replaces the startup bitmap. It preserves the stock bootloader and radio resources.

## Maintainer Build

Use Python 3.11+ and Apple Clang:

```sh
python3 firmware/ws30/v921/build.py \
  --output local/firmware/ws30/wbs03_yow_102.bin
```

Add `--offline-source PATH` for an identical stock image, or `--check-only` for in-memory validation. The builder downloads the pinned source and emits a private `.bin` and `.yow.json` receipt; it never connects to hardware.

| Artifact | Size | SHA-256 |
| --- | --- | --- |
| Stock v921 | 742,812 | `4eb3f9a5390faae2c11421ac388e5450bddc31449f3153f59daca1b10b0eaf48` |
| YourOwnWeigh v102 | 746,908 | `97d0bbd2cbbdfb81872f05aa6a395d2c3c856553ec3ecf89e679a1fc6dabb34a` |

Stock URL: `http://cdnfw.withings.net/wbs03/wbs03_921_dR7wKb.bin`. Source and output must match their pinned hashes.

## Implementation And Limits

`build.py` is the entry point, `patch.py` handles compilation/container validation, and `owner_patch.c` implements WPP command 0x170 and hostname lookup. Both the Wi-Fi DNS check and HTTP URL builder read the current DBLIB bank. Relocated radio sections must agree with both section descriptors and the runtime loader's header fields.

- Bluetooth Classic SPP; bootloader 15. WBS06 BLE does not apply.
- HTTP only, fixed port 80; hostname **1–59 ASCII bytes**.
- Wi-Fi and server readback do not prove an authenticated server session succeeded.
- The server retains the on-scale roster; WS-30 roster writes and HTTPS are not implemented.

See [Bluetooth OTA](Bluetooth-OTA.md), [owner protocol](Owner-Protocol.md) and [UART tools](../../../tools/README.md). After an update, reconnect to confirm v102 and verify a fresh reading reaches your server.
