# Startup Face

The selected 37×26 monochrome face is stored as an exact 12× PNG enlargement in `face-user-source-x12.png`. `convert_png_to_wbs06.py` validates each source block and packs it into 148 bytes: 37 columns, four bytes per column, least-significant bit first vertically, unused bottom bits clear. Set pixels are white/lit.

Run `python3 design/startup-face/convert_png_to_wbs06.py --help` for the input/output arguments. It accepts this exact grayscale enlargement, not arbitrary antialiased artwork. The resulting `face-user-wbs06-37x26.bin` is original image data. Identical copies are bundled with the WBS06 and WS-30 recipes so packaged builders need no files outside their resource directory.

The WBS06 Hello descriptor and WS-30 renderer both reference a 37×26 image despite the perceived display differences. The recipes pin the original bitmap hash/pointer before replacement and recalculate container CRCs. They change no display dimensions. See [display bounds](WBS06-display-bounds.md) for extension research.

## WBS13

[wbs13-smiley.svg](wbs13-smiley.svg) is a new vector face for the 320×240 Body
Smart display, based on the teal app icon's outward-tilted eyes, smile, yellow cheeks and scale
dial. Its source and deterministic rasteriser are in
[startup_artwork.py](../../firmware/wbs13/v1311/startup_artwork.py). Regenerate
the SVG with:

```sh
python3 firmware/wbs13/v1311/startup_artwork.py --svg design/startup-face/wbs13-smiley.svg
```

WBS13 v103 draws this at native resolution using compact horizontal spans and
the stock white/yellow palette on black. It needs neither a bitmap library nor
a larger framebuffer. The firmware tests execute the actual drawing routine
and compare every screen pixel with the vector raster. WBS06 and WS-30 keep
their original 37×26 artwork.
