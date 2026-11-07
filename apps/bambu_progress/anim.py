"""BUSY Bar `.anim` files, so the bar animates logos itself instead of us redrawing PNGs twice a second.

Container "bicycle1", the format firmware 1.3.1 reads (lib/anim_file/anim_file_format.h and
scripts/seq2anim.py in busybar-firmware). Firmware 1.3.1 rejects the older "bicycle0" files outright,
so an animation element drawn from one shows nothing. Layout: a 34-byte header, one "default"
section, then one record per display frame. Each record carries a mask saying which pixels it
replaces: we write a full frame (mask "fully white") whenever the picture changes and an empty one
(mask "fully black", no pixels) for every frame it is held. Pixels are BGRA8888 by default, so the
gaps in a mark stay transparent and whatever is behind shows through. Playback keeps running when
the same element is drawn again, so the render loop can upsert every tick as before.

All integers are little-endian.
"""
from __future__ import annotations

import struct
from collections.abc import Iterator, Sequence
from typing import NamedTuple

SIGNATURE = b"bicycle1"
LAYOUT_BGR888 = 0
LAYOUT_BGRA8888 = 2
BLOCK = 4                      # bytes per pixel in BGRA8888 (the default layout)
BLOCK_OF = {LAYOUT_BGR888: 3, LAYOUT_BGRA8888: 4}
_HEADER = struct.Struct("<8sBBBBHHBBIIII")
HEADER_LEN = _HEADER.size      # 34
_SECTION_NAME = b"default"
SECTION_LEN = 4 + 4 + 4 + len(_SECTION_NAME) + 1
_FRAME = struct.Struct("<BHH")  # pixel encoding | mask encoding << 4, mask length in bits, pixel length in bytes
MASK_SAME = 0                  # "fully black": no pixel changes, the previous frame stays
MASK_FULL = 1                  # "fully white": every pixel is replaced
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


class Record(NamedTuple):
    mask: int
    mask_bits: int
    pixel_encoding: int
    pixels: bytes


def encode_anim(width: int, height: int, fps: int, frames: Sequence[tuple[bytes, int]], layout: int = LAYOUT_BGRA8888) -> bytes:
    """`frames` are (pixels in `layout`, number of display frames to hold) pairs."""
    if not 1 <= fps <= 255:
        raise ValueError("fps must be 1..255")
    block = BLOCK_OF[layout]
    expected = width * height * block
    body = bytearray()
    count = max_pixels = 0
    for index, (pixels, repeats) in enumerate(frames):
        if len(pixels) != expected:
            raise ValueError(f"frame {index}: {len(pixels)} bytes, expected {expected}")
        if repeats < 1:
            continue
        packed = rle_compress(pixels, block)
        encoding, data = (ENCODING_RLE, packed) if len(packed) < len(pixels) else (ENCODING_RAW, pixels)
        max_pixels = max(max_pixels, len(data))
        body += _FRAME.pack(encoding | MASK_FULL << 4, 0, len(data)) + data
        body += _FRAME.pack(ENCODING_RAW | MASK_SAME << 4, 0, 0) * (repeats - 1)
        count += repeats
    if not count:
        raise ValueError("an animation needs at least one frame")
    head = _HEADER.pack(SIGNATURE, 0, width, height, layout, 0, max_pixels, fps, 0, SECTION_LEN, len(body), 1, count)
    section = struct.pack("<III", 0, count - 1, HEADER_LEN + SECTION_LEN) + _SECTION_NAME + b"\0"
    return bytes(head + section + body)


def iter_frames(data: bytes) -> Iterator[Record]:
    """The records of a file written by `encode_anim` (full or held frames only)."""
    if data[:8] != SIGNATURE:
        raise ValueError("not a bicycle1 animation")
    *_, sections_len, _frames_len, _sections, count = _HEADER.unpack_from(data)
    pos = HEADER_LEN + sections_len
    for _ in range(count):
        joint, mask_bits, length = _FRAME.unpack_from(data, pos)
        pos += _FRAME.size + (mask_bits + 7) // 8
        yield Record(joint >> 4, mask_bits, joint & 0xF, data[pos:pos + length])
        pos += length


def decode_anim(data: bytes) -> list[bytes]:
    """Every display frame's pixels, in the file's layout."""
    layout = data[11]
    frames: list[bytes] = []
    for r in iter_frames(data):
        if r.mask == MASK_SAME:
            frames.append(frames[-1])
        elif r.mask == MASK_FULL:
            frames.append(rle_decompress(r.pixels, BLOCK_OF[layout]) if r.pixel_encoding == ENCODING_RLE else r.pixels)
        else:
            raise ValueError(f"mask encoding {r.mask} is not one encode_anim writes")
    return frames


def bgra(pixels: Sequence[tuple[int, int, int, int]]) -> bytes:
    """(r, g, b, a) tuples -> BGRA bytes."""
    out = bytearray()
    for r, g, b, a in pixels:
        out += bytes((b, g, r, a))
    return bytes(out)
