# PTX <-> DDS converter for WRC Generations textures (KT Engine, "PATX-SP2").
#
#   python ptx_dds.py todds  FILE.PTX  FILE.DDS
#   python ptx_dds.py toptx  FILE.DDS  ORIGINAL.PTX  NEW.PTX
#   python ptx_dds.py verify FILE.PTX [MORE.PTX ...]     (PTX -> DDS -> PTX must be byte-identical)
#
# PTX layout (RIFF, little-endian):
#   RIFF "PA__"
#     Head (78 bytes): "PATX-SP2" ... fourcc @40 (DXT1/DXT5/BC4/BC5S/BC7), width @44, height @48,
#                      depth @52, mipmap count @56, other undocumented fields
#     one per mipmap: LIST "Levl" -> LIST "Surf" -> "Pixl" chunks of up to 512 KB
#   Mipmaps stop at 4x4 (a single compressed block).
# When converting back to PTX the header of the original PTX is reused (unknown fields stay
# untouched) and only format, size and mipmap count are updated.

import struct
import sys
from pathlib import Path

PIXL_CHUNK = 512 * 1024
# PTX format -> (bytes per 4x4 block, DXGI format for a "DX10" DDS header, or None = legacy fourcc)
FORMATS = {b"DXT1": (8, None), b"DXT5": (16, None), b"BC4 ": (8, 80), b"BC5S": (16, 84), b"BC7 ": (16, 98)}
BLOCK_BYTES = {k: v[0] for k, v in FORMATS.items()}
# DXGI formats accepted from DDS files (BC1/BC3/BC7 also in their sRGB variants)
DXGI = {71: b"DXT1", 72: b"DXT1", 77: b"DXT5", 78: b"DXT5", 80: b"BC4 ", 84: b"BC5S", 98: b"BC7 ", 99: b"BC7 "}


def level_size(fourcc, w, h):
    return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * BLOCK_BYTES[fourcc]


def describe(fourcc, w, h, levels):
    return f"{fourcc.decode().strip()} {w}x{h}, {len(levels)} mipmaps"


def chunk(cid, data):
    assert len(data) % 2 == 0
    return cid + struct.pack("<I", len(data)) + data


def read_ptx(data):
    assert data[:4] == b"RIFF" and data[8:12] == b"PA__", "not a PTX file"
    assert data[12:16] == b"Head", "missing Head chunk"
    head_size = struct.unpack_from("<I", data, 16)[0]
    head = data[20:20 + head_size]
    assert head[:8] == b"PATX-SP2", "unknown PTX header"
    fourcc = head[40:44]
    w, h, depth, mips = struct.unpack_from("<IIII", head, 44)
    assert fourcc in BLOCK_BYTES, f"format {fourcc!r} not supported"
    assert depth == 1, "3D textures are not supported"
    levels, pos = [], 20 + head_size
    while pos < len(data):
        assert data[pos:pos + 4] == b"LIST" and data[pos + 8:pos + 12] == b"Levl", f"unexpected chunk @{pos}"
        lsize = struct.unpack_from("<I", data, pos + 4)[0]
        assert data[pos + 12:pos + 16] == b"LIST" and data[pos + 20:pos + 24] == b"Surf", f"unexpected chunk @{pos + 12}"
        ssize = struct.unpack_from("<I", data, pos + 16)[0]
        p, end, pixels = pos + 24, pos + 20 + ssize, b""
        while p < end:
            assert data[p:p + 4] == b"Pixl", f"unexpected chunk {data[p:p + 4]!r} @{p}"
            n = struct.unpack_from("<I", data, p + 4)[0]
            pixels += data[p + 8:p + 8 + n]
            p += 8 + n
        levels.append(pixels)
        pos += 8 + lsize
    assert len(levels) == mips, f"{len(levels)} mipmaps found, {mips} declared"
    for i, lv in enumerate(levels):
        assert len(lv) == level_size(fourcc, max(1, w >> i), max(1, h >> i)), f"mipmap {i}: unexpected size"
    return head, fourcc, w, h, levels


def write_ptx(head, fourcc, w, h, levels):
    head = bytearray(head)
    head[40:44] = fourcc
    struct.pack_into("<IIII", head, 44, w, h, 1, len(levels))
    body = chunk(b"Head", bytes(head))
    for lv in levels:
        pixl = b"".join(chunk(b"Pixl", lv[i:i + PIXL_CHUNK]) for i in range(0, len(lv), PIXL_CHUNK))
        body += chunk(b"LIST", b"Levl" + chunk(b"LIST", b"Surf" + pixl))
    return chunk(b"RIFF", b"PA__" + body)


def write_dds(fourcc, w, h, levels):
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000  # CAPS|HEIGHT|WIDTH|PIXELFORMAT|MIPMAPCOUNT|LINEARSIZE
    dxgi = FORMATS[fourcc][1]
    pf = struct.pack("<II4s5I", 32, 0x4, b"DX10" if dxgi else fourcc, 0, 0, 0, 0, 0)  # DDPF_FOURCC
    caps = 0x8 | 0x1000 | 0x400000  # COMPLEX|TEXTURE|MIPMAP
    header = struct.pack("<7I", 124, flags, h, w, len(levels[0]), 0, len(levels)) + b"\0" * 44 + pf
    header += struct.pack("<5I", caps, 0, 0, 0, 0)
    assert len(header) == 124
    if dxgi:  # DXGI format, TEXTURE2D, misc flags, array size 1, alpha mode
        header += struct.pack("<5I", dxgi, 3, 0, 1, 0)
    return b"DDS " + header + b"".join(levels)


def read_dds(data):
    assert data[:4] == b"DDS ", "not a DDS file"
    h, w = struct.unpack_from("<II", data, 12)
    mips = struct.unpack_from("<I", data, 28)[0] or 1
    pf_flags, fourcc = struct.unpack_from("<I4s", data, 80)
    pos = 128
    if fourcc == b"DX10":
        dxgi = struct.unpack_from("<I", data, 128)[0]
        assert dxgi in DXGI, f"DXGI format {dxgi} not supported: save as BC3/DXT5 (or BC1/DXT1)"
        fourcc, pos = DXGI[dxgi], 148
    assert pf_flags & 0x4 and fourcc in BLOCK_BYTES, f"format {fourcc!r} not supported: save as BC3/DXT5 (or BC1/DXT1)"
    levels = []
    for i in range(mips):
        n = level_size(fourcc, max(1, w >> i), max(1, h >> i))
        levels.append(data[pos:pos + n])
        assert len(levels[-1]) == n, "truncated DDS file"
        pos += n
    return fourcc, w, h, levels


def dds_to_ptx(dds_data, template_data):
    # Builds a new PTX from an edited DDS, using the original PTX as template.
    # The DDS must match the original format and size and carry at least as many mipmaps
    # (extra small mipmaps are dropped: the game stops at 4x4).
    head, t_fourcc, t_w, t_h, t_levels = read_ptx(template_data)
    fourcc, w, h, levels = read_dds(dds_data)
    if (fourcc, w, h) != (t_fourcc, t_w, t_h):
        raise ValueError(f"the DDS is {describe(fourcc, w, h, levels)} but the original is "
                         f"{describe(t_fourcc, t_w, t_h, t_levels)}: save it with the same format and size")
    if len(levels) < len(t_levels):
        raise ValueError(f"the DDS has {len(levels)} mipmaps, {len(t_levels)} are needed: save it with mipmaps")
    levels = levels[:len(t_levels)]
    return write_ptx(head, fourcc, w, h, levels), describe(fourcc, w, h, levels)


def to_dds(ptx_path, dds_path):
    _, fourcc, w, h, levels = read_ptx(Path(ptx_path).read_bytes())
    Path(dds_path).write_bytes(write_dds(fourcc, w, h, levels))
    print(f"{ptx_path} -> {dds_path}  ({describe(fourcc, w, h, levels)})")


def to_ptx(dds_path, template_path, out_path):
    if Path(out_path).resolve() == Path(template_path).resolve():
        raise SystemExit("refusing to overwrite the original PTX: choose another output file")
    data, info = dds_to_ptx(Path(dds_path).read_bytes(), Path(template_path).read_bytes())
    Path(out_path).write_bytes(data)
    print(f"{dds_path} -> {out_path}  ({info})")


def verify(paths):
    ok = 0
    for p in paths:
        data = Path(p).read_bytes()
        try:
            head, fourcc, w, h, levels = read_ptx(data)
        except AssertionError as e:
            print(f"ERR  {e}  {p}")
            continue
        back = write_ptx(head, *read_dds(write_dds(fourcc, w, h, levels)))
        same = back == data
        ok += same
        print(f"{'OK  ' if same else 'DIFF'} {fourcc.decode()} {w:>4}x{h:<4} {p}")
    print(f"byte-identical: {ok}/{len(paths)}")
    return ok == len(paths)


USAGE = "usage: ptx_dds.py todds FILE.PTX FILE.DDS | toptx FILE.DDS ORIGINAL.PTX NEW.PTX | verify FILE.PTX ..."

if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(USAGE)
    cmd, args = sys.argv[1], sys.argv[2:]
    try:
        if cmd == "todds" and len(args) == 2:
            to_dds(*args)
        elif cmd == "toptx" and len(args) == 3:
            to_ptx(*args)
        elif cmd == "verify":
            sys.exit(0 if verify(args) else 1)
        else:
            raise SystemExit(USAGE)
    except (AssertionError, ValueError) as e:
        raise SystemExit(f"error: {e}")
