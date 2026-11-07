import struct

import pytest

from apps.bambu_progress.anim import (
    HEADER_LEN, MASK_FULL, MASK_SAME, SECTION_LEN, SIGNATURE, bgra, decode_anim, encode_anim, iter_frames,
    rle_compress, rle_decompress,
)


def test_rle_round_trips_and_uses_both_opcodes():
    data = b"A" * 10 + b"BCD" + b"E" * 3 + b"F" + b"G" * 300
    out = rle_compress(data, 1)
    assert rle_decompress(out, 1) == data
    assert out[0] == 10 and out[1:2] == b"A"                     # run opcode: count then one block
    assert out[2] == 0x83 and out[3:6] == b"BCD"                 # literal opcode: 0x80 | count then the blocks
    assert len(out) < len(data)


def test_rle_respects_block_size_and_the_127_cap():
    data = bytes(range(4)) * 200                                   # 200 identical 4-byte blocks
    out = rle_compress(data, 4)
    assert out[0] == 127 and out[5] == 73                          # 127 + 73 blocks
    assert rle_decompress(out, 4) == data
    with pytest.raises(ValueError):
        rle_compress(b"abc", 4)


def test_encode_anim_header_matches_firmware_1_3_struct():
    """bicycle1 (firmware 1.3.1, lib/anim_file/anim_file_format.h): "<8s BBBB HHBB IIII"."""
    frame_a = bgra([(255, 0, 0, 255)] * 4)                         # 2x2, all red
    frame_b = bgra([(0, 0, 0, 0)] * 3 + [(0, 255, 0, 255)])
    data = encode_anim(2, 2, 12, [(frame_a, 3), (frame_b, 1)])
    assert SIGNATURE == b"bicycle1" and HEADER_LEN == 34 and data[:8] == SIGNATURE
    (flags, w, h, layout, max_mask, max_px, fps, _unused,
     sections_len, frames_len, section_count, frame_count) = struct.unpack_from("<BBBBHHBBIIII", data, 8)
    assert (flags, w, h, layout, fps, max_mask) == (0, 2, 2, 2, 12, 0)
    assert (sections_len, section_count, frame_count) == (SECTION_LEN, 1, 4)   # one record per display frame
    assert len(data) == HEADER_LEN + SECTION_LEN + frames_len               # the loader checks the exact size
    start, end, offs = struct.unpack_from("<III", data, HEADER_LEN)
    assert (start, end, offs) == (0, 3, HEADER_LEN + SECTION_LEN)
    assert data[HEADER_LEN + 12:HEADER_LEN + SECTION_LEN] == b"default\0"
    records = list(iter_frames(data))
    assert [(r.mask, r.mask_bits) for r in records] == [(MASK_FULL, 0), (MASK_SAME, 0), (MASK_SAME, 0), (MASK_FULL, 0)]
    assert records[0].pixel_encoding == 1 and records[1].pixels == b""      # a held frame carries no pixels
    assert max_px >= max(len(r.pixels) for r in records)
    assert decode_anim(data) == [frame_a, frame_a, frame_a, frame_b]


def test_encode_anim_rejects_bad_input():
    with pytest.raises(ValueError):
        encode_anim(2, 2, 12, [(b"\0" * 15, 1)])
    with pytest.raises(ValueError):
        encode_anim(2, 2, 0, [(b"\0" * 16, 1)])
    with pytest.raises(ValueError):
        encode_anim(2, 2, 12, [])
    long = encode_anim(1, 1, 1, [(b"\0\0\0\0", 300)])              # no 255 cap: holds are just repeated frames
    assert struct.unpack_from("<I", long, 30) == (300,)
    assert len(decode_anim(long)) == 300
