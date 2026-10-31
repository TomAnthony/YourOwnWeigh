"""Original YOW face for the WBS13's larger display, using stock palette colours.

Rounded eyes, a scale dial, yellow cheeks and a curved smile echo the teal app
icon. This vector source produces both a reviewable SVG and compact scanline
spans for the firmware. Integer curve sampling keeps builds reproducible across
platforms; no image library or compiler is needed to generate the artwork.

Run `python startup_artwork.py --svg /path/to/preview.svg` to export the design.
The firmware builder calls encode() directly; bridge users use its pinned recipe.
"""
from __future__ import annotations

import argparse
from pathlib import Path

WIDTH, HEIGHT = 256, 216
ORIGIN = (32, 12)
BLACK, WHITE, YELLOW = 13, 6, 14
COLOURS = {BLACK: "#000000", WHITE: "#ffffff", YELLOW: "#ffee66"}
Q = 1 << 16


def rounded_rect(x, y, width, height, radius):
    return [
        ("M", x + radius, y), ("L", x + width - radius, y),
        ("Q", x + width, y, x + width, y + radius),
        ("L", x + width, y + height - radius),
        ("Q", x + width, y + height, x + width - radius, y + height),
        ("L", x + radius, y + height),
        ("Q", x, y + height, x, y + height - radius),
        ("L", x, y + radius), ("Q", x, y, x + radius, y), ("Z",),
    ]


def shapes():
    # Approved 10-degree outward tilt, stored as integer control points so
    # generation needs no floating-point rotation. Mirror for the other foot.
    eye = [
        ("M", 57, 53), ("C", 30, 56, 21, 93, 29, 118),
        ("C", 36, 142, 53, 157, 72, 156),
        ("C", 93, 154, 108, 141, 106, 121),
        ("C", 105, 104, 99, 80, 91, 66),
        ("C", 81, 51, 69, 48, 57, 53), ("Z",),
    ]
    mirrored = [tuple([command[0]] + [WIDTH - v if i % 2 == 0 else v
                                    for i, v in enumerate(command[1:])])
                for command in eye]
    result = [(WHITE, eye), (WHITE, mirrored)]
    # A small rounded scale dial carries the app icon's distinctive forehead.
    result.append((WHITE, rounded_rect(76, 8, 104, 34, 11)))
    for x, y, height in ((94, 22, 12), (109, 18, 14), (124, 14, 17),
                         (139, 18, 14), (154, 22, 12)):
        result.append((BLACK, rounded_rect(x, y, 8, height, 4)))
    for x in (41, 215):
        result.append((YELLOW, [
            ("M", x + 10, 174), ("C", x + 10, 180, x + 6, 184, x, 184),
            ("C", x - 6, 184, x - 10, 180, x - 10, 174),
            ("C", x - 10, 168, x - 6, 164, x, 164),
            ("C", x + 6, 164, x + 10, 168, x + 10, 174), ("Z",),
        ]))
    result.append((WHITE, [
        ("M", 66, 170), ("C", 57, 172, 61, 183, 68, 190),
        ("C", 100, 216, 156, 216, 188, 190),
        ("C", 195, 183, 199, 172, 190, 170),
        ("C", 185, 167, 179, 169, 175, 175),
        ("C", 151, 201, 105, 201, 81, 175),
        ("C", 77, 169, 71, 167, 66, 170), ("Z",),
    ]))
    return result


def polygon(commands):
    """Flatten integer Bezier control points into Q16 coordinates."""
    points = []
    for kind, *values in commands:
        if kind == "Z":
            points.append(points[0])
        elif kind in ("M", "L"):
            points.append(tuple(v * Q for v in values))
        else:
            controls = [points[-1]] + [(values[i] * Q, values[i + 1] * Q)
                                       for i in range(0, len(values), 2)]
            for step in range(1, 65):
                work = controls
                # de Casteljau subdivision, with deterministic integer rounding.
                while len(work) > 1:
                    work = [tuple(((64 - step) * a[k] + step * b[k]) // 64
                                  for k in (0, 1)) for a, b in zip(work, work[1:])]
                points.append(work[0])
    return points


def pixels():
    """Rasterise the vector at native resolution, returning stock palette indices."""
    output = bytearray([BLACK] * WIDTH * HEIGHT)
    for colour, commands in shapes():
        points = polygon(commands)
        for y in range(HEIGHT):
            centre = y * Q + Q // 2
            crossings = []
            for (x0, y0), (x1, y1) in zip(points, points[1:]):
                if min(y0, y1) <= centre < max(y0, y1):
                    crossings.append(x0 + (centre - y0) * (x1 - x0) // (y1 - y0))
            crossings.sort()
            if len(crossings) % 2:
                raise ValueError("Open startup artwork outline")
            for left, right in zip(crossings[::2], crossings[1::2]):
                start = max(0, -((Q // 2 - left) // Q))
                end = min(WIDTH, -((Q // 2 - right) // Q))
                output[y * WIDTH + start:y * WIDTH + end] = bytes([colour]) * (end - start)
    return bytes(output)


def encode():
    """Four-byte spans: y, first x, last x (inclusive), palette index."""
    data, spans = pixels(), bytearray()
    for y in range(HEIGHT):
        x = 0
        while x < WIDTH:
            colour, start = data[y * WIDTH + x], x
            while x < WIDTH and data[y * WIDTH + x] == colour:
                x += 1
            if colour != BLACK:
                spans.extend((y, start, x - 1, colour))
    return bytes(spans)


def svg():
    paths = []
    for colour, commands in shapes():
        path = " ".join(" ".join(map(str, command)) for command in commands)
        paths.append(f'<path fill="{COLOURS[colour]}" d="{path}"/>')
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240" '
            'viewBox="0 0 320 240" role="img" aria-labelledby="title">\n'
            '<title id="title">YourOwnWeigh WBS13 startup smiley</title>\n'
            '<rect width="320" height="240" fill="#000000"/>\n'
            f'<g transform="translate({ORIGIN[0]} {ORIGIN[1]})">\n' +
            "\n".join(paths) + '\n</g>\n</svg>\n')


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--svg", type=Path, required=True)
    args = parser.parse_args()
    args.svg.write_text(svg())
