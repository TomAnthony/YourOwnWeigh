# Contributing

There are 3 areas that can help:

1. Adding Windows support to the Python bridge.
2. Adding support for more models of scales. You need to be comfortable with modding firmware, or trust AI to do it for you, and be willing to then install that on your own device. We will only accept PRs where you confirm you have tested the firmware on the model you are support.
3. Adding more `<model, firmware>` pairs. A bluetooth connection can read the model, and confirm what firmware Withings is advertising for it.


## Known Firmware Versions

These models are mapped:

| Scale | Stock Firmware | URL |
| --- | --- | --- |
| Body (**WBS06**) | v1181 | http://cdnfw.withings.net/wbs06/wbs06_1181_XFUxfc.bin |
| Wireless Scale (**WS-30 / WBS03**) | v921 | http://cdnfw.withings.net/wbs03/wbs03_921_dR7wKb.bin |

### Identifying New Firmwares

In the web app, if you do a scan and connect to unrecognised scales, you should receive details you can kindly share in a Github issue / PR. What you are sharing includes nothing secret or personal to you - it is details about what firmware is intended to go with what model of scales.

## Adding Model Support

If you have unsupported scales, see above for how to identify the firmware over Bluetooth, which should give you a URL you can use to download the latest firmware for your scales.

Once you have those, you need to patch that firmware to:

- Identify the stock image and layout: model, firmware and bootloader versions, source URL/hash, image sections and checksums.
- Replace the boot 'Hello' image with the smiley face image.
- Redirect syncing: make the server hostname configurable and persistent, identify every relevant connection path, and establish supported protocols and hostname limits.
- Support Bluetooth setup and OTA: identification, configuration, transfer acknowledgements and completing setup. Reuse existing Wi-Fi commands where possible; these do not necessarily require a firmware patch.
- Support the server protocol: verify authentication, user/settings responses, measurement parsing and timestamps against the new model.
- Package the patch: add the maintainer builder, portable bridge recipe, model validation and expected output hashes. Confirm compiler-built and recipe-generated images match.
- Test on hardware: update, reboot, confirm version, retain configuration, and deliver a real reading with the correct user, value and timestamp.

When submitting a PR _please confirm your model as read physically from the device, and that you've tested the firmware end to end on that device_.


# AI Usage

Code produced by AI is welcome, but please have done your due diligence, and be sure you understand the shape of the changes being made.

Firmware PRs produce by AI are fine, but you have to be running this on your own scales, and have validated it works.
