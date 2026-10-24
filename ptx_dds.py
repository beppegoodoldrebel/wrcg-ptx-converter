# PTX <-> DDS converter for WRC Generations textures (KT Engine, "PATX-SP2").
#
#   python ptx_dds.py todds  FILE.PTX  FILE.DDS
#   python ptx_dds.py toptx  FILE.DDS  ORIGINAL.PTX  NEW.PTX
#   python ptx_dds.py verify FILE.PTX [MORE.PTX ...]     (PTX -> DDS -> PTX must be byte-identical)
#   python ptx_dds.py split   FILE.PTX  COLOUR.DDS  MASK.DDS              (DXT5 only, e.g. BODY_DIFF)
#   python ptx_dds.py combine COLOUR.DDS  MASK.DDS|-  ORIGINAL.PTX  NEW.PTX   ("-" = original mask)
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
# Legacy DDS fourccs for BC4, as saved by GIMP and Paint.NET
FOURCC_ALIASES = {b"ATI1": b"BC4 ", b"BC4U": b"BC4 "}


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


def write_dds(fourcc, w, h, levels, legacy_tag=None):
    # legacy_tag: write this fourcc (e.g. b"ATI1" for BC4) instead of a DX10 header, for older editors
    flags = 0x1 | 0x2 | 0x4 | 0x1000 | 0x20000 | 0x80000  # CAPS|HEIGHT|WIDTH|PIXELFORMAT|MIPMAPCOUNT|LINEARSIZE
    dxgi = None if legacy_tag else FORMATS[fourcc][1]
    pf = struct.pack("<II4s5I", 32, 0x4, b"DX10" if dxgi else legacy_tag or fourcc, 0, 0, 0, 0, 0)  # DDPF_FOURCC
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
    fourcc = FOURCC_ALIASES.get(fourcc, fourcc)
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


# --- Colour + mask: DXT5 textures whose alpha is a mask, not transparency (BODY_DIFF) ---
# Image editors show that alpha as transparency, so the painted bodywork looks empty. "split" saves
# the colour as an opaque DXT1 DDS and the alpha as a separate BC4 DDS; "combine" puts them back
# into a DXT5 PTX. A DXT5 block is a BC4 alpha block followed by a colour block, so both steps
# copy the compressed blocks: nothing is re-compressed (except the rare DXT1 blocks that use the
# 3-colour mode, which DXT5 does not have).

def _rgb565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def _to565(r, g, b):
    return ((r * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((b * 31 + 127) // 255)


def _dxt1_safe(c0, c1, idx):
    # DXT5 colour blocks always use 4 colours, while in DXT1 c0 <= c1 selects the 3-colour +
    # transparent mode: swap the endpoints (index 0<->1, 2<->3) so the block decodes the same
    if c0 > c1:
        return c0, c1, idx
    if c0 == c1:
        return c0, c1, 0  # a single colour
    return c1, c0, idx ^ 0x55555555


def _dxt5_colour(c0, c1, idx):
    # DXT1 colour block -> DXT5 colour block
    if c0 > c1 or not idx & 0xAAAAAAAA:
        return c0, c1, idx  # 4-colour block, or only the endpoints used: decodes the same
    # 3-colour mode (half-way colour or transparent black): fit a 4-colour block to its pixels
    a, b = _rgb565(c0), _rgb565(c1)
    palette = [a, b, tuple((x + y) // 2 for x, y in zip(a, b)), (0, 0, 0)]
    px = [palette[(idx >> 2 * i) & 3] for i in range(16)]
    e0 = _to565(*(max(p[k] for p in px) for k in range(3)))
    e1 = _to565(*(min(p[k] for p in px) for k in range(3)))
    if e0 == e1:
        return e0, e1, 0
    a, b = _rgb565(e0), _rgb565(e1)
    palette = [a, b, tuple((2 * x + y) // 3 for x, y in zip(a, b)), tuple((x + 2 * y) // 3 for x, y in zip(a, b))]
    new = 0
    for i, p in enumerate(px):
        best = min(range(4), key=lambda j: sum((p[k] - palette[j][k]) ** 2 for k in range(3)))
        new |= best << 2 * i
    return e0, e1, new


def _alpha_levels(levels):
    return [b"".join(lv[i:i + 8] for i in range(0, len(lv), 16)) for lv in levels]


def split_ptx(ptx_data):
    # DXT5 PTX -> (colour DDS in DXT1, mask DDS in BC4, description)
    _, fourcc, w, h, levels = read_ptx(ptx_data)
    if fourcc != b"DXT5":
        raise ValueError(f"the texture is {describe(fourcc, w, h, levels)}: only DXT5 textures "
                         "(e.g. BODY_DIFF) have a mask in their alpha channel")
    colour = [b"".join(struct.pack("<HHI", *_dxt1_safe(c0, c1, idx))
                       for _, c0, c1, idx in struct.iter_unpack("<8sHHI", lv)) for lv in levels]
    return (write_dds(b"DXT1", w, h, colour), write_dds(b"BC4 ", w, h, _alpha_levels(levels), b"ATI1"),
            describe(fourcc, w, h, levels))


def combine_to_ptx(colour_data, mask_data, template_data):
    # Colour DDS (DXT1 or DXT5) + mask DDS (BC4, or None = the original's) -> DXT5 PTX
    head, t_fourcc, t_w, t_h, t_levels = read_ptx(template_data)
    if t_fourcc != b"DXT5":
        raise ValueError(f"the original is {describe(t_fourcc, t_w, t_h, t_levels)}: combine needs a DXT5 texture")
    n = len(t_levels)

    def load(data, what, formats, hint):
        fourcc, w, h, levels = read_dds(data)
        if fourcc not in formats or (w, h) != (t_w, t_h):
            raise ValueError(f"the {what} DDS is {describe(fourcc, w, h, levels)}: save it as {hint}, {t_w}x{t_h}")
        if len(levels) < n:
            raise ValueError(f"the {what} DDS has {len(levels)} mipmaps, {n} are needed: save it with mipmaps")
        return fourcc, levels[:n]

    c_fourcc, colour = load(colour_data, "colour", (b"DXT1", b"DXT5"), "BC1/DXT1 (or BC3/DXT5)")
    mask = _alpha_levels(t_levels) if mask_data is None else load(mask_data, "mask", (b"BC4 ",), "BC4/ATI1")[1]
    levels = []
    for c, m in zip(colour, mask):
        if c_fourcc == b"DXT5":
            blocks = (c[i + 8:i + 16] for i in range(0, len(c), 16))
        else:
            blocks = (struct.pack("<HHI", *_dxt5_colour(*b)) for b in struct.iter_unpack("<HHI", c))
        levels.append(b"".join(m[i * 8:i * 8 + 8] + blk for i, blk in enumerate(blocks)))
    return write_ptx(head, b"DXT5", t_w, t_h, levels), describe(b"DXT5", t_w, t_h, levels)


def split(ptx_path, colour_path, mask_path):
    colour, mask, info = split_ptx(Path(ptx_path).read_bytes())
    Path(colour_path).write_bytes(colour)
    Path(mask_path).write_bytes(mask)
    print(f"{ptx_path} -> {colour_path} + {mask_path}  ({info})")


def combine(colour_path, mask_path, template_path, out_path):
    if Path(out_path).resolve() == Path(template_path).resolve():
        raise SystemExit("refusing to overwrite the original PTX: choose another output file")
    mask = None if mask_path == "-" else Path(mask_path).read_bytes()
    data, info = combine_to_ptx(Path(colour_path).read_bytes(), mask, Path(template_path).read_bytes())
    Path(out_path).write_bytes(data)
    print(f"{colour_path} + {'original mask' if mask is None else mask_path} -> {out_path}  ({info})")


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


USAGE = ("usage: ptx_dds.py todds FILE.PTX FILE.DDS | toptx FILE.DDS ORIGINAL.PTX NEW.PTX | verify FILE.PTX ...\n"
         "       ptx_dds.py split FILE.PTX COLOUR.DDS MASK.DDS | combine COLOUR.DDS MASK.DDS|- ORIGINAL.PTX NEW.PTX")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(USAGE)
    cmd, args = sys.argv[1], sys.argv[2:]
    try:
        if cmd == "todds" and len(args) == 2:
            to_dds(*args)
        elif cmd == "toptx" and len(args) == 3:
            to_ptx(*args)
        elif cmd == "split" and len(args) == 3:
            split(*args)
        elif cmd == "combine" and len(args) == 4:
            combine(*args)
        elif cmd == "verify":
            sys.exit(0 if verify(args) else 1)
        else:
            raise SystemExit(USAGE)
    except (AssertionError, ValueError) as e:
        raise SystemExit(f"error: {e}")
