"""Render short ASCII strings to a valid PNG using only the stdlib.

Test-only tooling for the B2 live-Anthropic break-control: it needs a real,
decodable image with a unique value baked into the PIXELS (not metadata) to
prove the model actually reads vision content rather than guessing. Pillow
(and every other image library) is constitutionally forbidden in this repo,
so this hand-rolls a minimal 5x7 bitmap font + PNG encoder (struct + zlib,
both stdlib) instead of depending on one.
"""

from __future__ import annotations

import struct
import zlib

_CHAR_W = 5
_CHAR_H = 7

# Only the glyphs this break-control's fixture strings actually need.
_FONT_5X7: dict[str, tuple[str, ...]] = {
    " ": (".....",) * 7,
    "-": (".....", ".....", ".....", "#####", ".....", ".....", "....."),
    "#": (".#.#.", ".#.#.", "#####", ".#.#.", "#####", ".#.#.", ".#.#."),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "...#.", "..#..", ".#...", "#####"),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "8": (".###.", "#...#", "#...#", ".###.", "#...#", "#...#", ".###."),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "###..", "#....", "#....", "#####"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "Q": (".###.", "#...#", "#...#", "#...#", "#.#.#", "#..#.", ".##.#"),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "X": ("#...#", "#...#", ".#.#.", "..#..", ".#.#.", "#...#", "#...#"),
    "Z": ("#####", "....#", "...#.", "..#..", ".#...", "#....", "#####"),
}


def render_text_png(text: str, *, scale: int = 12, margin: int = 3) -> bytes:
    """Return valid PNG bytes rendering ``text`` as black-on-white pixels.

    Every character in ``text`` (case-insensitive) must have a glyph in
    ``_FONT_5X7`` — add it there if a new fixture string needs one.
    """
    glyphs = [_FONT_5X7[ch.upper()] for ch in text]
    spacing = 1
    grid_w = margin * 2 + len(glyphs) * (_CHAR_W + spacing) - spacing
    grid_h = margin * 2 + _CHAR_H
    # 1 = background (white), 0 = foreground (black), one entry per
    # unscaled grid pixel.
    grid: list[list[int]] = [[1] * grid_w for _ in range(grid_h)]
    for index, glyph in enumerate(glyphs):
        x0 = margin + index * (_CHAR_W + spacing)
        for row_index, row in enumerate(glyph):
            for col_index, pixel in enumerate(row):
                if pixel == "#":
                    grid[margin + row_index][x0 + col_index] = 0

    width = grid_w * scale
    height = grid_h * scale
    raw = bytearray()
    for row in grid:
        scanline_template = bytearray()
        for value in row:
            channel = 255 if value else 0
            scanline_template.extend((channel, channel, channel) * scale)
        for _ in range(scale):
            raw.append(0)  # PNG filter type: none
            raw.extend(scanline_template)
    compressed = zlib.compress(bytes(raw), 9)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )
