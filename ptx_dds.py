# PTX <-> DDS converter for WRC Generations textures (KT Engine, "PATX-SP2").
#
#   python ptx_dds.py todds  FILE.PTX  FILE.DDS
#   python ptx_dds.py toptx  FILE.DDS  ORIGINAL.PTX  NEW.PTX
#   python ptx_dds.py verify FILE.PTX [MORE.PTX ...]     (PTX -> DDS -> PTX must be byte-identical)
#   python ptx_dds.py split   FILE.PTX  COLOUR.DDS  MASK.DDS              (DXT5 only, e.g. BODY_DIFF)
#   python ptx_dds.py combine COLOUR.DDS  MASK.DDS|-  ORIGINAL.PTX  NEW.PTX   ("-" = original mask)
#
# Normal maps (BC5S) are exported as BC5 unsigned ("ATI2") and imported from BC5, BC3/DXT5 or BC1/DXT1
# (see to_bc5s).
# NEW.PTX can be ORIGINAL.PTX itself: a PTX that gets overwritten is first kept in <its folder>\ORIGINALI
# (only the first time, so that copy stays the real original).
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
# PTX format -> (bytes per 4x4 block, DXGI format for a "DX10" DDS header, or None = legacy fourcc).
# BC5U (unsigned BC5) is not a game format: it is how normal maps are exported for image editors.
FORMATS = {b"DXT1": (8, None), b"DXT5": (16, None), b"BC4 ": (8, 80), b"BC5S": (16, 84), b"BC7 ": (16, 98),
           b"BC5U": (16, 83)}
BLOCK_BYTES = {k: v[0] for k, v in FORMATS.items()}
# DXGI formats accepted from DDS files (BC1/BC3/BC7 also in their sRGB variants)
DXGI = {71: b"DXT1", 72: b"DXT1", 77: b"DXT5", 78: b"DXT5", 80: b"BC4 ", 84: b"BC5S", 98: b"BC7 ", 99: b"BC7 ",
        82: b"BC5U", 83: b"BC5U"}
# Legacy DDS fourccs for BC4 and BC5, as saved by GIMP, Paint.NET and the NVIDIA tools
FOURCC_ALIASES = {b"ATI1": b"BC4 ", b"BC4U": b"BC4 ", b"ATI2": b"BC5U", b"BC5U": b"BC5U"}


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


# --- Normal maps (*_NRM): the game reads BC5 signed (BC5S, x and y of the normal, flat = 0), which most
# image editors cannot open or save. They are exported as BC5 unsigned (legacy "ATI2" DDS, flat = 128) and
# imported from BC5 unsigned or signed, BC3/DXT5 (x, y in red, green, or x in alpha for "DXT5nm") or BC1/DXT1
# (x, y in red, green). Compressed blocks are converted, not re-compressed: a BC4 channel block becomes signed
# by flipping the top bit of its two endpoints (value - 128, the order of the endpoints is kept, so the block
# keeps its mode), which is exact both ways; a colour block's red or green channel is two endpoints plus the
# 1/3 and 2/3 points between them, which a BC4 block holds at its palette positions 3 and 6.

NORMAL_INPUTS = (b"BC5S", b"BC5U", b"DXT5", b"DXT1")


def _flip_bc4(level):
    """BC4 blocks (8 bytes each) unsigned <-> signed: top bit of both endpoints flipped."""
    out = bytearray(level)
    for o in range(0, len(out), 8):
        out[o] ^= 0x80
        out[o + 1] ^= 0x80
    return bytes(out)


_flip_bc5 = _flip_bc4            # a BC5 block is two BC4 blocks


def _bc4_tables():
    # one byte of colour indices (4 pixels) -> 12 bits of BC4 indices. Colour index 0 = c0, 1 = c1,
    # 2 = 1/3 of the way to c1, 3 = 2/3; BC4 (e0 > e1) index 0 = e0, 1 = e1, k = (k - 1)/7 of the way
    cases = {"c0": (0, 1, 3, 6), "c1": (1, 0, 6, 3), "eq": (0, 0, 0, 0)}
    return {c: [sum(m[(b >> 2 * p) & 3] << 3 * p for p in range(4)) for b in range(256)] for c, m in cases.items()}


_BC4_FROM_COLOUR = _bc4_tables()


def _bc4_from_colour(a, b, idx):
    """Unsigned BC4 block of one channel of a 4-colour block: endpoint values a (c0), b (c1), 32-bit indices."""
    case, e0, e1 = ("c0", a, b) if a > b else ("c1", b, a) if b > a else ("eq", a, a)
    t = _BC4_FROM_COLOUR[case]
    bits = 0
    for p in range(4):
        bits |= t[(idx >> 8 * p) & 255] << 12 * p
    return bytes((e0, e1)) + bits.to_bytes(6, "little")


def _x_in_alpha(level):
    """DXT5nm: x stored in alpha, red unused. True if red is (almost) constant and alpha is not."""
    reds, alphas = set(), set()
    for o in range(0, len(level), 16 * max(1, len(level) // 16 // 4096)):   # a sample of blocks is enough
        alphas.update(level[o:o + 2])
        c0, c1 = struct.unpack_from("<HH", level, o + 8)
        reds.update((c0 >> 11, c1 >> 11))
    return max(reds) - min(reds) <= 2 and max(alphas) - min(alphas) > 16


def to_bc5s(fourcc, levels):
    """Mipmap levels of a normal map DDS (NORMAL_INPUTS) as BC5S levels."""
    if fourcc == b"BC5S":
        return levels
    if fourcc == b"BC5U":
        return [_flip_bc5(lv) for lv in levels]
    if fourcc not in (b"DXT5", b"DXT1"):
        raise ValueError(f"a normal map can not be imported from {fourcc.decode().strip()}: save it as "
                         "BC5 (ATI2), BC3/DXT5 or BC1/DXT1")
    alpha_x = fourcc == b"DXT5" and _x_in_alpha(levels[0])
    out = []
    for lv in levels:
        blocks = bytearray()
        step = 16 if fourcc == b"DXT5" else 8
        for o in range(0, len(lv), step):
            c0, c1, idx = struct.unpack_from("<HHI", lv, o + step - 8)
            if fourcc == b"DXT1":
                c0, c1, idx = _dxt5_colour(c0, c1, idx)        # 3-colour blocks refitted to 4 colours
            r0, r1, g0, g1 = c0 >> 11, c1 >> 11, (c0 >> 5) & 63, (c1 >> 5) & 63
            x = lv[o:o + 8] if alpha_x else _bc4_from_colour(r0 << 3 | r0 >> 2, r1 << 3 | r1 >> 2, idx)
            y = _bc4_from_colour(g0 << 2 | g0 >> 4, g1 << 2 | g1 >> 4, idx)
            blocks += _flip_bc4(x + y)
        out.append(bytes(blocks))
    return out


def editable_dds(fourcc, w, h, levels):
    """DDS for an image editor: normal maps (BC5S) as unsigned BC5 with a legacy ATI2 header, the rest as
    they are. to_bc5s brings the unsigned one back byte for byte."""
    if fourcc == b"BC5S":
        return write_dds(b"BC5U", w, h, [_flip_bc5(lv) for lv in levels], b"ATI2")
    return write_dds(fourcc, w, h, levels)


def dds_to_ptx(dds_data, template_data):
    # Builds a new PTX from an edited DDS, using the original PTX as template.
    # The DDS must match the original format and size and carry at least as many mipmaps
    # (extra small mipmaps are dropped: the game stops at 4x4). Normal maps (BC5S) are also accepted as
    # BC5 unsigned, BC3/DXT5 or BC1/DXT1 and converted (see to_bc5s).
    head, t_fourcc, t_w, t_h, t_levels = read_ptx(template_data)
    fourcc, w, h, levels = read_dds(dds_data)
    if t_fourcc == b"BC5S" and fourcc in NORMAL_INPUTS and (w, h) == (t_w, t_h):
        levels, fourcc = to_bc5s(fourcc, levels), b"BC5S"
    if (fourcc, w, h) != (t_fourcc, t_w, t_h):
        raise ValueError(f"the DDS is {describe(fourcc, w, h, levels)} but the original is "
                         f"{describe(t_fourcc, t_w, t_h, t_levels)}: save it with the same format and size")
    if len(levels) < len(t_levels):
        raise ValueError(f"the DDS has {len(levels)} mipmaps, {len(t_levels)} are needed: save it with mipmaps")
    levels = levels[:len(t_levels)]
    return write_ptx(head, fourcc, w, h, levels), describe(fourcc, w, h, levels)


def to_dds(ptx_path, dds_path):
    _, fourcc, w, h, levels = read_ptx(Path(ptx_path).read_bytes())
    Path(dds_path).write_bytes(editable_dds(fourcc, w, h, levels))
    print(f"{ptx_path} -> {dds_path}  ({describe(fourcc, w, h, levels)}"
          + (", saved as BC5 unsigned (ATI2)" if fourcc == b"BC5S" else "") + ")")


BACKUP = "ORIGINALI"


def write_ptx_file(out_path, data):
    # Writes a PTX; if it replaces an existing file, the first time that file is kept in
    # <its folder>\ORIGINALI (later overwrites keep that first original). Returns the backup path or None.
    out = Path(out_path)
    backup = None
    if out.exists():
        backup = out.parent / BACKUP / out.name
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            backup.write_bytes(out.read_bytes())
    out.write_bytes(data)
    return backup


def to_ptx(dds_path, template_path, out_path):
    # the template is read before writing, so the output can be the original PTX itself
    data, info = dds_to_ptx(Path(dds_path).read_bytes(), Path(template_path).read_bytes())
    backup = write_ptx_file(out_path, data)
    print(f"{dds_path} -> {out_path}  ({info})" + (f"  original kept in {backup}" if backup else ""))


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
    mask = None if mask_path == "-" else Path(mask_path).read_bytes()
    data, info = combine_to_ptx(Path(colour_path).read_bytes(), mask, Path(template_path).read_bytes())
    backup = write_ptx_file(out_path, data)
    print(f"{colour_path} + {'original mask' if mask is None else mask_path} -> {out_path}  ({info})"
          + (f"  original kept in {backup}" if backup else ""))


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
        if fourcc == b"BC5S":     # also through the editor DDS (BC5 unsigned) and the import
            same = same and dds_to_ptx(editable_dds(fourcc, w, h, levels), data)[0] == data
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
