# Read and write the livery stickers of Common\Tuning\LIVERIES.LUA (race numbers, names, flags,
# rally plates... drawn by the game on top of BODY_DIFF).
#
# File layout (LF, no BOM): a LiveryType = { Name = n, ... } enum, a placeholder table, then
#   Liveries = {
#   	KEY = {                       -- KEY = a CARS.CFG entry name in upper case
#   		EditorDiffuseTexture = "DATA:/GRAPH/CARS/.../BODY_DIFF.PTX",
#   		Stickers = {
#   			{ Type = LiveryType.X, Position = {x, y}, Size = {w, h}, Rotation = r, Order = n, },
#   			...
#   		}
#   	},
# Coordinates are texture UV (0..1, top-down). Position is a corner of the sticker box and the pivot of
# the rotation; the box spans Size along the rotated x and y axes; Rotation is in degrees, clockwise on
# the texture (values like 540 or -181.8 are used as they are). Checked on the Fiat 131 Röhrl livery,
# whose two NumberBlack boxes (0° and 180°) fall exactly on the white squares painted for the number.
#
# The livery folder -> entry keys: entries whose EditorDiffuseTexture is the folder's BODY_DIFF, plus the
# CARS.CFG entries whose LiveryPaclog loads that BODY_DIFF (several keys can share one livery, e.g. a
# livery and its MOD_ copy). The first save keeps the original file in Tuning\ORIGINALI\LIVERIES.LUA.

import math
import re
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

BACKUP = "ORIGINALI"
ENCODING = "latin-1"  # byte-exact round trip whatever the content


@dataclass
class Sticker:
    type: str
    x: float
    y: float
    w: float
    h: float
    rotation: float
    order: int = 0

    def copy(self):
        return replace(self)

    def corners(self):
        """The 4 box corners in UV: position, +w, +w+h, +h (along the rotated axes)."""
        a = math.radians(self.rotation)
        ca, sa = math.cos(a), math.sin(a)
        return [(self.x + px * ca - py * sa, self.y + px * sa + py * ca)
                for px, py in ((0, 0), (self.w, 0), (self.w, self.h), (0, self.h))]

    def to_local(self, u, v):
        """UV point -> coordinates along the sticker's own axes, from its position."""
        a = math.radians(self.rotation)
        du, dv = u - self.x, v - self.y
        return du * math.cos(a) + dv * math.sin(a), -du * math.sin(a) + dv * math.cos(a)

    def contains(self, u, v):
        lx, ly = self.to_local(u, v)
        return 0 <= lx <= self.w and 0 <= ly <= self.h


STICKER_RE = re.compile(
    r"\t\t\t\{\n"
    r"\t\t\t\tType = LiveryType\.(\w+),\n"
    r"\t\t\t\tPosition = \{([-\d.]+), ([-\d.]+)\},\n"
    r"\t\t\t\tSize = \{([-\d.]+), ([-\d.]+)\},\n"
    r"\t\t\t\tRotation = ([-\d.]+),\n"
    r"\t\t\t\tOrder = (-?\d+),\n"
    r"\t\t\t\},\n")
STICKERS_RE = re.compile(r"(\t\tStickers = \{\n)((?:" + STICKER_RE.pattern + r")*)(\t\t\}\n)")


def format_sticker(s):
    return (f"\t\t\t{{\n\t\t\t\tType = LiveryType.{s.type},\n"
            f"\t\t\t\tPosition = {{{s.x:.6f}, {s.y:.6f}}},\n"
            f"\t\t\t\tSize = {{{s.w:.6f}, {s.h:.6f}}},\n"
            f"\t\t\t\tRotation = {s.rotation:.6f},\n"
            f"\t\t\t\tOrder = {int(s.order)},\n\t\t\t}},\n")


def game_root(path):
    """Game folder (the one holding WIN32 and Common) of a file or folder inside WIN32, or None."""
    for p in [Path(path)] + list(Path(path).parents):
        if p.name.upper() == "WIN32" and (p.parent / "Common").is_dir():
            return p.parent
    return None


def data_path(root, path):
    """Game file -> its DATA:/ path (upper case, as used in the game files for comparison)."""
    rel = Path(path).resolve().relative_to((Path(root) / "WIN32").resolve())
    return "DATA:/" + "/".join(rel.parts).upper()


def _find_ci(folder, rel_parts):
    # case-insensitive path lookup (game paths are written in mixed case)
    p = Path(folder)
    for part in rel_parts:
        if not p.is_dir():
            return None
        nxt = p / part
        if not nxt.exists():
            nxt = next((c for c in p.iterdir() if c.name.upper() == part.upper()), None)
            if nxt is None:
                return None
        p = nxt
    return p


class LiveriesFile:
    def __init__(self, root):
        self.root = Path(root)
        self.path = self.root / "Common" / "Tuning" / "LIVERIES.LUA"
        self.reload()

    def reload(self):
        self.text = self.path.read_bytes().decode(ENCODING)
        self._parse()

    def _parse(self):
        enum = re.search(r"^LiveryType = \{\n(.*?)^\}", self.text, re.M | re.S)
        self.types = [n for n, _ in sorted(re.findall(r"^\t(\w+) = (\d+),", enum.group(1), re.M), key=lambda t: int(t[1]))]
        start = self.text.index("\nLiveries = {\n")
        self.entries = {m.group(1): m.span() for m in re.finditer(r"^\t(\w+) = \{\n.*?^\t\},\n", self.text[start:], re.M | re.S)}
        self.entries = {k: (a + start, b + start) for k, (a, b) in self.entries.items()}

    def keys(self):
        return list(self.entries)

    def block(self, key):
        a, b = self.entries[key]
        return self.text[a:b]

    def texture(self, key):
        m = re.search(r'EditorDiffuseTexture = "([^"]*)"', self.block(key))
        return m.group(1) if m else ""

    def stickers(self, key):
        m = STICKERS_RE.search(self.block(key))
        if not m:
            raise ValueError(f"{key}: Stickers table not in the expected layout")
        return [Sticker(t, float(x), float(y), float(w), float(h), float(r), int(o))
                for t, x, y, w, h, r, o in STICKER_RE.findall(m.group(2))]

    def set_stickers(self, key, stickers):
        """Replaces the stickers of an entry in memory (save() writes the file)."""
        for s in stickers:
            if s.type not in self.types:
                raise ValueError(f"unknown sticker type {s.type}")
        block = self.block(key)
        m = STICKERS_RE.search(block)
        new = block[:m.start(2)] + "".join(format_sticker(s) for s in stickers) + block[m.end(2):]
        a, b = self.entries[key]
        self.text = self.text[:a] + new + self.text[b:]
        shift = len(new) - (b - a)
        self.entries = {k: (s + shift if s > a else s, e + shift if e > a else e) for k, (s, e) in self.entries.items()}

    def add_entry(self, key, texture, stickers):
        """Adds an entry at the end of the Liveries table (in memory; save() writes the file)."""
        if key in self.entries:
            raise ValueError(f"{key} is already in LIVERIES.LUA")
        block = (f"\t{key} = {{\n\t\tEditorDiffuseTexture = \"{texture}\",\n\t\tStickers = {{\n"
                 + "".join(format_sticker(s) for s in stickers) + "\t\t}\n\t},\n")
        end = self.text.rindex("\n}") + 1  # closing brace of Liveries, the last table of the file
        self.text = self.text[:end] + block + self.text[end:]
        self._parse()

    def keys_for_livery(self, folder):
        """Entry keys that draw their stickers on the BODY_DIFF of this livery folder."""
        diff = data_path(self.root, Path(folder) / "BODY_DIFF.PTX")
        keys = [k for k in self.entries if self.texture(k).upper() == diff]
        cars = self.root / "Common" / "Tuning" / "FACTORIES" / "CARS.CFG"
        if cars.exists():
            text = cars.read_bytes().decode(ENCODING)
            cache = {}
            heads = list(re.finditer(r"^\t(\w+)\s*=\s*\r?\n\t\{", text, re.M))
            for n, head in enumerate(heads):
                end = heads[n + 1].start() if n + 1 < len(heads) else len(text)
                m = re.search(r'LiveryPaclog\s*=\s*"([^"]+)"', text[head.end():end])
                if not m:
                    continue
                key, paclog = head.group(1).upper(), m.group(1)
                if key in keys or key not in self.entries or not paclog.upper().startswith("DATA:/"):
                    continue
                if paclog not in cache:
                    f = _find_ci(self.root / "WIN32", paclog[6:].split("/"))
                    cache[paclog] = f.read_bytes().decode(ENCODING).upper() if f and f.is_file() else ""
                if diff in cache[paclog]:
                    keys.append(key)
        return keys

    def check(self):
        """Light syntax check of the whole file: balanced braces (outside strings and comments)
        and every entry still parsable."""
        depth, i, t = 0, 0, self.text
        while i < len(t):
            c = t[i]
            if c == '"':
                i = t.index('"', i + 1)
            elif t.startswith("--", i):
                i = t.find("\n", i)
                i = len(t) if i < 0 else i
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth < 0:
                    raise ValueError("LIVERIES.LUA: unbalanced braces")
            i += 1
        if depth:
            raise ValueError("LIVERIES.LUA: unbalanced braces")
        for k in self.entries:
            self.stickers(k)

    def backup_path(self):
        return self.path.parent / BACKUP / self.path.name

    def save(self):
        """Writes the file; the first time, the current one is kept in Tuning\\ORIGINALI."""
        self.check()
        backup = self.backup_path()
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, backup)
        self.path.write_bytes(self.text.encode(ENCODING))

    def original_stickers(self, key):
        """Stickers of the entry in the kept original file, or None (no backup or no such entry)."""
        backup = self.backup_path()
        if not backup.exists():
            return None
        orig = LiveriesFile.__new__(LiveriesFile)
        orig.root, orig.path = self.root, backup
        orig.reload()
        return orig.stickers(key) if key in orig.entries else None
