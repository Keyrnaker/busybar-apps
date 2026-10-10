import struct

import pytest

from apps.bambu_progress.anim import (
    BLOCK, HEADER_LEN, SECTION_LEN, SIGNATURE, bgra, encode_anim, rle_compress, rle_decompress,
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


def test_encode_anim_header_section_and_records():
    frame_a = bgra([(255, 0, 0, 255)] * 4)                         # 2x2, all red
    frame_b = bgra([(0, 0, 0, 0)] * 3 + [(0, 255, 0, 255)])
    data = encode_anim(2, 2, 12, [(frame_a, 3), (frame_b, 1)])
    assert data[:8] == SIGNATURE
    flags, w, h, layout, fps = data[8:13]
    assert (flags, w, h, layout, fps) == (0, 2, 2, 2, 12)
    max_len, = struct.unpack_from("<H", data, 13)
    sections_len, frames_len, section_count, record_count, display_frames = struct.unpack_from("<IIIII", data, 16)
    assert (sections_len, section_count, record_count, display_frames) == (SECTION_LEN, 1, 2, 4)
    assert len(data) == HEADER_LEN + SECTION_LEN + frames_len
    start, end, offs = struct.unpack_from("<III", data, HEADER_LEN)
    assert (start, end, offs) == (0, 3, HEADER_LEN + SECTION_LEN)
    assert data[HEADER_LEN + 12] == 3 and data[HEADER_LEN + 13:HEADER_LEN + 21] == b"default\0"
    # first record: RLE (4 identical pixels compress), held 3 frames
    rec = HEADER_LEN + SECTION_LEN
    enc, hold = data[rec], data[rec + 1]
    length, = struct.unpack_from("<H", data, rec + 2)
    assert (enc, hold) == (1, 3) and rle_decompress(data[rec + 4:rec + 4 + length], BLOCK) == frame_a
    assert max_len >= length


def test_encode_anim_rejects_bad_input():
    with pytest.raises(ValueError):
        encode_anim(2, 2, 12, [(b"\0" * 15, 1)])
    with pytest.raises(ValueError):
        encode_anim(2, 2, 0, [(b"\0" * 16, 1)])
    with pytest.raises(ValueError):
        encode_anim(2, 2, 12, [])
    long = encode_anim(1, 1, 1, [(b"\0\0\0\0", 300)])              # holds longer than 255 split into records
    assert struct.unpack_from("<II", long, 28) == (2, 300)                  # record_count, display_frames
