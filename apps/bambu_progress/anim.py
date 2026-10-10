"""BUSY Bar `.anim` files, so the bar animates logos itself instead of us redrawing PNGs twice a second.

Container "bicycle0" as the firmware's player (1.2.4) accepts it and the busybar-anim crate writes it:
a 36-byte header, one "default" section, then keyframe records. Pixels are BGRA8888, so the gaps in
a mark stay transparent and whatever is behind shows through (verified on the device). Playback keeps
running when the same element is drawn again, so the render loop can upsert every tick as before.

All integers are little-endian.
"""
from __future__ import annotations

import struct
from collections.abc import Sequence

SIGNATURE = b"bicycle0"
LAYOUT_BGR888 = 0
LAYOUT_BGRA8888 = 2
BLOCK = 4                      # bytes per pixel in BGRA8888 (the default layout)
BLOCK_OF = {LAYOUT_BGR888: 3, LAYOUT_BGRA8888: 4}
HEADER_LEN = 36
_SECTION_NAME = b"default"
SECTION_LEN = 4 + 4 + 4 + 1 + len(_SECTION_NAME) + 1
ENCODING_RAW = 0
ENCODING_RLE = 1
_MAX_BLOCKS = 127              # per opcode
_RUN = 3                       # shortest run worth an opcode of its own


def rle_compress(data: bytes, blk: int = BLOCK) -> bytes:
    """`toolbox/rle_encode` stream: opcode n (1..127) repeats the following block n times,
    opcode 0x80|n copies the following n blocks verbatim."""
    if len(data) % blk:
        raise ValueError(f"data length {len(data)} is not a multiple of the block size {blk}")
    blocks = [data[i:i + blk] for i in range(0, len(data), blk)]
    out = bytearray()
    i, n = 0, len(blocks)
    while i < n:
        run = 1
        while i + run < n and run < _MAX_BLOCKS and blocks[i + run] == blocks[i]:
            run += 1
        if run >= _RUN:
            out.append(run)
            out += blocks[i]
            i += run
            continue
        j = i + 1                                  # literal stretch: stop where a run of _RUN starts
        while j < n and j - i < _MAX_BLOCKS and blocks[j:j + _RUN] != [blocks[j]] * _RUN:
            j += 1
        out.append(0x80 | (j - i))
        out += b"".join(blocks[i:j])
        i = j
    return bytes(out)


def rle_decompress(data: bytes, blk: int = BLOCK) -> bytes:
    out = bytearray()
    i = 0
    while i < len(data):
        op = data[i]
        count = op & 0x7F
        i += 1
        if op & 0x80:
            out += data[i:i + count * blk]
            i += count * blk
        else:
            out += data[i:i + blk] * count
            i += blk
    return bytes(out)


def encode_anim(width: int, height: int, fps: int, frames: Sequence[tuple[bytes, int]], layout: int = LAYOUT_BGRA8888) -> bytes:
    """`frames` are (pixels in `layout`, number of display frames to hold) pairs; every record is a keyframe."""
    if not 1 <= fps <= 255:
        raise ValueError("fps must be 1..255")
    block = BLOCK_OF[layout]
    expected = width * height * block
    body = bytearray()
    records = total = max_len = 0
    first_duration: int | None = None
    for index, (pixels, repeats) in enumerate(frames):
        if len(pixels) != expected:
            raise ValueError(f"frame {index}: {len(pixels)} bytes, expected {expected}")
        packed = rle_compress(pixels, block)
        encoding, data = (ENCODING_RLE, packed) if len(packed) < len(pixels) else (ENCODING_RAW, pixels)
        max_len = max(max_len, len(data))
        while repeats > 0:
            hold = min(repeats, 255)
            repeats -= hold
            total += hold
            records += 1
            if first_duration is None:
                first_duration = hold
            body += bytes((encoding, hold)) + struct.pack("<H", len(data)) + data
    if first_duration is None:
        raise ValueError("an animation needs at least one frame")
    head = SIGNATURE + bytes((0, width, height, layout, fps)) + struct.pack("<H", max_len) + b"\0"
    head += struct.pack("<IIIII", SECTION_LEN, len(body), 1, records, total)
    assert len(head) == HEADER_LEN
    section = struct.pack("<III", 0, total - 1, HEADER_LEN + SECTION_LEN) + bytes((first_duration,)) + _SECTION_NAME + b"\0"
    return bytes(head + section + body)


def bgra(pixels: Sequence[tuple[int, int, int, int]]) -> bytes:
    """(r, g, b, a) tuples -> BGRA bytes."""
    out = bytearray()
    for r, g, b, a in pixels:
        out += bytes((b, g, r, a))
    return bytes(out)
