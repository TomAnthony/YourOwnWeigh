# WBS06 Display Bounds — Extension Notes

Scope: stock WBS06 v1181. The released patch keeps the 37×26 startup image unchanged in size. A larger asset is plausible but is not part of the tested release.

The Hello descriptor is at file 0x5faac (runtime 0x63a28), dimensions 37×26, pixel pointer0x777ac (file 0x73830), 148 bytes. The next asset begins immediately after it. Increasing dimensions without relocating the data would consume another asset.

The caller at 0x33b26 centres the image at `x = 64 - floor(width/2)`, `y = 32 - floor(height/2)`. The logical framebuffer is 128×64, 1024 bytes; this alone does not establish the physical visible margins. The renderer at 0x2f9d4 uses column-major eight-row pages, bit0 at the top, and ORs lit pixels into a cleared buffer.

A 112×48 image needs 672 bytes and would be centred at (8,8). Static address tracing puts writes within 65–959, leaving margins. A full 128×64 asset is unsafe without changing/validating the renderer: its unconditional second-byte access appears to touch byte 1024, one byte beyond the framebuffer.

An extension must allocate verified application storage, change width/height/pointer together, preserve adjacent assets, shift radio/bootloader offsets if extending the app, and recalculate all CRCs. The current v126 application has already grown; recompute the remaining flash budget from its actual descriptors instead of reusing old expansion estimates. Decode and compare every pixel offline, then test visible margins on recoverable hardware. Logical dimensions are not a hardware display guarantee.
