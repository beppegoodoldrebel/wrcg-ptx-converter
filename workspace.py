# Livery workspace: open a livery folder (or one of its PTX files), list its textures, export the ones
# you want to edit as DDS into a work folder, and save the edited ones back to PTX in the livery folder.
#
# - A DXT5 texture (BODY_DIFF) is listed as two parts, "colour" and "mask", because its alpha channel is
#   a mask and not transparency (see split/combine in ptx_dds.py). Other textures are one "full" part.
# - The work folder keeps workspace.json (what was exported, with the file hashes), so every DDS shows as
#   "not exported", "exported" (unchanged), "modified" or "saved".
# - The first save of a texture copies the original PTX into <work folder>\ORIGINALI; that copy is the
#   template of every later save and is what "restore" puts back.
# - A DDS with the wrong format or size is reported and its PTX is not written.

import hashlib
import json
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path

import ptx_dds

MANIFEST = "workspace.json"
BACKUP = "ORIGINALI"


@dataclass
class Item:
    ptx: Path      # texture in the livery folder
    part: str      # "full", "colour" or "mask"
    fourcc: bytes
    w: int
    h: int
    mips: int
    note: str = ""  # why it cannot be edited (unsupported format)

    @property
    def dds_name(self):
        return {"full": f"{self.ptx.stem}.dds", "colour": f"{self.ptx.stem}_COLOUR.dds",
                "mask": f"{self.ptx.stem}_MASK.dds"}[self.part]

    @property
    def editable(self):
        return not self.note

    def describe(self):
        if self.note:
            return self.note
        fmt = {"colour": "DXT1 (or DXT5)", "mask": "BC4"}.get(self.part, self.fourcc.decode().strip())
        return f"{fmt} {self.w}x{self.h}, {self.mips} mipmaps"


def _sha1(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def scan(livery):
    """Items of every PTX in the livery folder (sorted, DXT5 as colour + mask)."""
    items = []
    for ptx in sorted(Path(livery).glob("*.PTX"), key=lambda p: p.name.upper()):
        data = ptx.read_bytes()
        try:
            _, fourcc, w, h, levels = ptx_dds.read_ptx(data)
        except AssertionError as e:
            fourcc = data[60:64] if len(data) > 64 else b"????"
            items.append(Item(ptx, "full", fourcc, 0, 0, 0, note=f"not editable ({e})"))
            continue
        parts = ("colour", "mask") if fourcc == b"DXT5" else ("full",)
        items += [Item(ptx, part, fourcc, w, h, len(levels)) for part in parts]
    return items


def default_work_folder(livery):
    # <Desktop>\WRCG_TEXTURES\<car folder>\<livery folder>
    livery = Path(livery)
    return Path.home() / "Desktop" / "WRCG_TEXTURES" / livery.parent.name / livery.name


class Workspace:
    def __init__(self, livery, work):
        self.livery, self.work = Path(livery), Path(work)
        self.items = scan(self.livery)
        self.manifest = {"livery": str(self.livery), "items": {}}
        path = self.work / MANIFEST
        if path.exists():
            self.manifest = json.loads(path.read_text(encoding="utf-8"))

    def _save_manifest(self):
        self.work.mkdir(parents=True, exist_ok=True)
        self.manifest["livery"] = str(self.livery)
        (self.work / MANIFEST).write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")

    def dds(self, item):
        return self.work / item.dds_name

    def status(self, item):
        if not item.editable:
            return "-"
        dds = self.dds(item)
        if not dds.exists():
            return "not exported"
        rec = self.manifest["items"].get(item.dds_name, {})
        h = _sha1(dds)
        if h == rec.get("saved"):
            return "saved"
        if h == rec.get("exported"):
            return "exported"
        return "modified"

    def template(self, ptx):
        # the original PTX: the backup if a save already happened, otherwise the livery's file
        backup = self.work / BACKUP / ptx.name
        return backup if backup.exists() else ptx

    def export(self, items):
        """Writes the DDS of the given items into the work folder; returns the written names."""
        done = []
        self.work.mkdir(parents=True, exist_ok=True)
        for item in items:
            if not item.editable:
                continue
            data = self.template(item.ptx).read_bytes()
            if item.part == "full":
                _, fourcc, w, h, levels = ptx_dds.read_ptx(data)
                out = ptx_dds.write_dds(fourcc, w, h, levels)
            else:
                colour, mask, _ = ptx_dds.split_ptx(data)
                out = colour if item.part == "colour" else mask
            self.dds(item).write_bytes(out)
            self.manifest["items"][item.dds_name] = {"ptx": item.ptx.name, "part": item.part,
                                                    "exported": hashlib.sha1(out).hexdigest()}
            done.append(item.dds_name)
        self._save_manifest()
        return done

    def save(self, items=None):
        """Converts every modified DDS (of items, default all) back to PTX in the livery folder.
        Returns (saved PTX names, {item name: error})."""
        items = [i for i in (items or self.items) if i.editable and self.status(i) == "modified"]
        by_ptx = {}
        for item in items:
            by_ptx.setdefault(item.ptx, []).append(item)
        saved, errors = [], {}
        for ptx, changed in by_ptx.items():
            template = self.template(ptx).read_bytes()
            try:
                if changed[0].part == "full":
                    data, _ = ptx_dds.dds_to_ptx(self.dds(changed[0]).read_bytes(), template)
                else:
                    # colour + mask: the part not edited comes from its DDS if exported, else the original
                    col = next((i for i in self.items if i.ptx == ptx and i.part == "colour"), None)
                    msk = next((i for i in self.items if i.ptx == ptx and i.part == "mask"), None)
                    if self.dds(col).exists():
                        colour = self.dds(col).read_bytes()
                    else:
                        colour = ptx_dds.split_ptx(template)[0]
                    mask = self.dds(msk).read_bytes() if self.dds(msk).exists() else None
                    data, _ = ptx_dds.combine_to_ptx(colour, mask, template)
            except (ValueError, AssertionError) as e:
                for item in changed:
                    errors[item.dds_name] = str(e)
                continue
            backup = self.work / BACKUP / ptx.name
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ptx, backup)
            ptx.write_bytes(data)
            for item in (i for i in self.items if i.ptx == ptx and self.dds(i).exists()):
                self.manifest["items"].setdefault(item.dds_name, {})["saved"] = _sha1(self.dds(item))
            saved.append(ptx.name)
        self._save_manifest()
        return saved, errors

    def restore(self):
        """Puts every backed-up original PTX back into the livery folder; returns their names."""
        done = []
        for backup in sorted((self.work / BACKUP).glob("*.PTX")):
            shutil.copy2(backup, self.livery / backup.name)
            done.append(backup.name)
        for rec in self.manifest["items"].values():
            rec.pop("saved", None)
        self._save_manifest()
        return done


# --- small previews (for the GUI): RGB of a mipmap about `size` pixels wide ---

def _rgb565(c):
    return ((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31


def _bc4(block):
    a0, a1 = block[0], block[1]
    pal = [a0, a1] + ([((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)] if a0 > a1
                      else [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255])
    bits = int.from_bytes(block[2:8], "little")
    return [pal[(bits >> 3 * i) & 7] for i in range(16)]


def _colour(block, four):
    c0, c1, idx = struct.unpack("<HHI", block)
    a, b = _rgb565(c0), _rgb565(c1)
    if c0 > c1 or four:
        pal = [a, b, tuple((2 * x + y) // 3 for x, y in zip(a, b)), tuple((x + 2 * y) // 3 for x, y in zip(a, b))]
    else:
        pal = [a, b, tuple((x + y) // 2 for x, y in zip(a, b)), (0, 0, 0)]
    return [pal[(idx >> 2 * i) & 3] for i in range(16)]


def preview(item, size=128):
    """(width, height, rgb bytes) of a small mipmap of the item, or None if there is no preview."""
    if not item.editable or item.fourcc == b"BC7 ":
        return None
    _, fourcc, w, h, levels = ptx_dds.read_ptx(item.ptx.read_bytes())
    lvl = 0
    while lvl + 1 < len(levels) and (w >> lvl) > size:
        lvl += 1
    lw, lh = max(4, w >> lvl), max(4, h >> lvl)
    data, step = levels[lvl], ptx_dds.BLOCK_BYTES[fourcc]
    img = bytearray(lw * lh * 3)
    bw = lw // 4
    for n in range(len(data) // step):
        blk = data[n * step:(n + 1) * step]
        if fourcc == b"DXT1":
            px = _colour(blk, False)
        elif fourcc == b"DXT5":
            px = [(a, a, a) for a in _bc4(blk[:8])] if item.part == "mask" else _colour(blk[8:], True)
        elif fourcc == b"BC4 ":
            px = [(a, a, a) for a in _bc4(blk)]
        else:  # BC5 normal map: red and green channels (signed values shifted to 0..255)
            r, g = _bc4(blk[:8]), _bc4(blk[8:])
            px = [((x + 128) % 256, (y + 128) % 256, 255) for x, y in zip(r, g)]
        bx, by = n % bw * 4, n // bw * 4
        for i, p in enumerate(px):
            x, y = bx + i % 4, by + i // 4
            if x < lw and y < lh:
                o = (y * lw + x) * 3
                img[o:o + 3] = bytes(p)
    return lw, lh, bytes(img)
