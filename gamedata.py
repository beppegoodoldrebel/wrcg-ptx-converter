# Teams, drivers and their liveries in the game's config files (used by team_editor.py).
#
#   Common\Tuning\FACTORIES\TEAMS.CFG   Teams = { Key = { TeamID, TeamName, PilotInfo, Car, ... }, ... }
#                                       a disabled team is the same block with every line commented ("--")
#   Common\Tuning\FACTORIES\CARS.CFG    livery entries: Key = { BaseCar, Skin, LiveryPaclog, ... }
#   Common\Tuning\FACTORIES\TYRES.CFG   tyre sets, given by livery name (Car / Cars) or by category
#   Common\Tuning\LIVERIES.LUA          stickers of each livery entry (liveries.py)
#   Common\Tuning\CONTESTS.CFG          challenges: refer to teams by TeamID (read only here)
#
# What can and cannot be done:
# - TeamID values (WrcTeamDriversId.eTeam...) are known only by the game executable: no new ones. A
#   "new" team or driver takes the place of an existing team, e.g. one that is disabled, or uses one of
#   the few ids the executable knows and TEAMS.CFG never uses (UNTESTED_TEAM_IDS). free_slots() lists them
#   and new_crew() makes a crew on one.
# - TeamName is a LocalesId.TEAM_... text id: the list comes from Common\SCRIPTS\LOCALISATION.LUA, the
#   English text from Common\LOCALISATION\LOCALISATION_EN.PLOC.
# - A team drives the livery of the CARS.CFG entry in its Car field. Several teams can share one entry
#   (shared livery). make_dedicated() gives a team its own livery: a copy of the livery folder (materials
#   rewritten to it), a new PACLOG, a new CARS.CFG entry, the same tyre sets and the same stickers.
#
# Every file keeps its encoding and line ends; the first save of a file keeps the original in an
# ORIGINALI folder next to it.

import re
import shutil
from pathlib import Path

import liveries

BACKUP = "ORIGINALI"
LEVEL_KEYS = ("Global", "Limit", "LevelSnow", "LevelTarmac", "LevelGravel", "HighSpeed", "MiddleSpeed",
              "LowSpeed", "Fiability")
CATEGORY_ORDER = ("WRC", "WRC2", "JWRC", "Legend")
# Team ids in the executable (game 1.5.26) that no TEAMS.CFG block uses, not even commented. They look like
# driver slots but have not been tried in game. The eTeamCustomLivery... ids are left out on purpose: they
# belong to the livery editor and the neutral cars.
UNTESTED_TEAM_IDS = ("eTeamGryazin", "eTeamOstberg", "eTeamRoustemis", "eTeamTilley", "eTeamTimur")


# --- text files with their encoding, line ends and backup

class TextFile:
    def __init__(self, path):
        self.path = Path(path)
        self.reload()

    def reload(self):
        data = self.path.read_bytes()
        self.bom = data.startswith(b"\xef\xbb\xbf")
        try:
            self.encoding = "utf-8"
            self.text = data[3 if self.bom else 0:].decode("utf-8")
        except UnicodeDecodeError:
            self.encoding = "latin-1"
            self.text = data.decode("latin-1")
        self.saved_text = self.text
        self.eol = "\r\n" if "\r\n" in self.text else "\n"

    @property
    def modified(self):
        return self.text != self.saved_text

    def save(self):
        if not self.modified:
            return False
        backup = self.path.parent / BACKUP / self.path.name
        if not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.path, backup)
        self.path.write_bytes((b"\xef\xbb\xbf" if self.bom else b"") + self.text.encode(self.encoding))
        self.saved_text = self.text
        return True


def braced_end(text, start):
    """Index just after the "}" closing the first "{" at or after start (skips strings and comments)."""
    depth, i = 0, text.index("{", start)
    while i < len(text):
        c = text[i]
        if c == '"':
            i = text.index('"', i + 1)
        elif text.startswith("--", i):
            i = text.find("\n", i)
            if i < 0:
                break
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced braces")


# --- TEAMS.CFG

TEAM_HEAD = re.compile(r"^(--)?[ \t]*(\w+)[ \t]*=[ \t]*\r?\n(?:--)?[ \t]*\{[ \t]*\r?\n", re.M)
TEAM_CLOSE = re.compile(r"^(?:--)?[ \t]*\},[^\n]*\n", re.M)
INFO_RE = {"Country": r"Country\s*=\s*WrcNationality\.(\w+)", "FirstName": r'FirstName\s*=\s*L"([^"]*)"',
           "LastName": r'LastName\s*=\s*L"([^"]*)"', "PathLastName": r'PathLastName\s*=\s*"([^"]*)"',
           "Skin": r'Skin\s*=\s*"([^"]*)"'}


def parse_info(value):
    return {k: (m.group(1) if (m := re.search(p, value)) else None) for k, p in INFO_RE.items()}


def format_info(d):
    parts = [f"Country = WrcNationality.{d['Country']}", f'FirstName = L"{d["FirstName"]}"',
             f'LastName = L"{d["LastName"]}"']
    if d.get("PathLastName"):
        parts.append(f'PathLastName= "{d["PathLastName"]}"')
    if d.get("Skin"):
        parts.append(f'Skin = "{d["Skin"]}"')
    return "{ " + ", ".join(parts) + " }"


def parse_level(value):
    return dict(re.findall(r"(\w+)\s*=\s*(PilotLimit\.\w+|-?\d+)", value))


def format_level(d):
    keys = [k for k in LEVEL_KEYS if k in d] + [k for k in d if k not in LEVEL_KEYS]
    return "{ " + ", ".join(f"{k} = {d[k]}" for k in keys) + " }"


def parse_rallies(value):
    return re.findall(r'"([^"]+)"', value)


def format_rallies(lst):
    return "{ " + ", ".join(f'"{r}"' for r in lst) + " }"


class Teams(TextFile):
    def reload(self):
        super().reload()
        start = re.search(r"^Teams\s*=", self.text, re.M)
        if not start:
            raise ValueError("TEAMS.CFG: no Teams table")
        self.section = (start.start(), braced_end(self.text, start.start()))

    def spans(self):
        """{key: (start, end, disabled)} of every team block (end = after its closing line)."""
        a, b = self.section
        out, pos = {}, self.text.index("{", a) + 1  # inside "Teams = {"
        while True:
            m = TEAM_HEAD.search(self.text, pos, b)
            if not m:
                return out
            close = TEAM_CLOSE.search(self.text, m.end(), b)
            if not close:
                return out
            out[m.group(2)] = (m.start(), close.end(), bool(m.group(1)))
            pos = close.end()

    def keys(self):
        return list(self.spans())

    def disabled(self, key):
        return self.spans()[key][2]

    def block(self, key):
        """Block text without the "--" of a disabled team."""
        a, b, off = self.spans()[key]
        text = self.text[a:b]
        return re.sub(r"^--", "", text, flags=re.M) if off else text

    def _put(self, key, block):
        a, b, off = self.spans()[key]
        if off:
            block = "".join("--" + line for line in block.splitlines(keepends=True))
        self.text = self.text[:a] + block + self.text[b:]

    # a field line: name = value, then optional comma, tabs and "--" comment
    def get(self, key, field):
        m = re.search(rf"^[ \t]*{field}[ \t]*=[ \t]*(.*?)[ \t]*,?[ \t]*(?:--[^\r\n]*)?\r?$", self.block(key), re.M)
        return m.group(1) if m else None

    def fields(self, key):
        found = re.findall(r"^[ \t]*(\w+)[ \t]*=[ \t]*(.*?)[ \t]*,?[ \t]*(?:--[^\r\n]*)?\r?$", self.block(key), re.M)
        return dict(found[1:])  # the first one is the team's own name line

    def set(self, key, field, value):
        """Sets a field (raw Lua value text); None removes it. Other lines, and what follows the value on
        its line (comma, tabs, comment), stay as they are."""
        block = self.block(key)
        m = re.search(rf"^([ \t]*{field}[ \t]*=[ \t]*)(.*?)([ \t]*,?[ \t]*(?:--[^\r\n]*)?)\r?$", block, re.M)
        if value is None:
            if m:
                end = block.index("\n", m.start()) + 1
                block = block[:m.start()] + block[end:]
        elif m:
            tail = m.group(3) if "," in m.group(3) else "," + m.group(3)
            block = block[:m.start(2)] + value + tail + block[m.end(3):]
        else:
            close = list(TEAM_CLOSE.finditer(block))[-1]
            block = block[:close.start()] + f"\t\t{field}\t\t= {value},{self.eol}" + block[close.start():]
        self._put(key, block)

    def set_enabled(self, key, on):
        a, b, off = self.spans()[key]
        if off == (not on):
            return
        block = self.block(key)  # without "--"
        new = block if on else "".join("--" + line for line in block.splitlines(keepends=True))
        self.text = self.text[:a] + new + self.text[b:]

    # convenient typed access
    def info(self, key, field):
        v = self.get(key, field)
        return parse_info(v) if v else None

    def car(self, key):
        v = self.get(key, "Car")
        return v.strip('"') if v else None

    def team_id(self, key):
        v = self.get(key, "TeamID")
        return v.split(".")[-1] if v else None


# --- CARS.CFG

CAR_HEAD = re.compile(r"^\t+(\w+)\s*=\s*\r?\n\t+\{", re.M)


class Cars(TextFile):
    def reload(self):
        super().reload()
        self._parse()

    def _parse(self):
        # entries: (start of the name line, index after the closing "}")
        self.entries = {}
        for m in CAR_HEAD.finditer(self.text):
            try:
                self.entries[m.group(1)] = (m.start(), braced_end(self.text, m.start()))
            except ValueError:
                pass
        # top-level templates (BaseCar definitions) carry the category of their liveries
        self.templates = {}
        for m in re.finditer(r"^(\w+)\s*=\s*\r?\n\{", self.text, re.M):
            body = self.text[m.end():braced_end(self.text, m.start())]
            cat = re.search(r"Category\s*=\s*WrcChampionships\.(\w+)", body)
            shape = re.search(r"Shape\s*=\s*([\w.]+)", body)
            if cat:
                self.templates[m.group(1)] = (cat.group(1), shape.group(1) if shape else None)

    def block(self, name):
        a, b = self.entries[name]
        return self.text[a:b]

    def field(self, name, field):
        m = re.search(rf"\b{field}\s*=\s*([^,\r\n]+)", self.block(name))
        return m.group(1).strip().strip('"') if m else None

    def category(self, name):
        own = self.field(name, "Category")
        if own:
            return own.split(".")[-1]
        base = self.field(name, "BaseCar")
        if base and base in self.templates:
            return self.templates[base][0]
        shape = self.field(name, "Shape")
        return next((c for c, s in self.templates.values() if shape and s == shape), None)

    def insert_after(self, name, block):
        """Inserts an entry block (name line ... closing "}") on the line after the entry <name>."""
        _, b = self.entries[name]
        end = self.text.index("\n", b) + 1
        self.text = self.text[:end] + block + "," + self.eol + self.text[end:]
        self._parse()


# --- TYRES.CFG

class Tyres(TextFile):
    def named(self, car):
        return f'"{car}"' in self.text

    def category_sets(self, category):
        return bool(re.search(rf"Availability\s*=\s*\{{[^}}]*WrcChampionships\.{category}\b", self.text))

    def add_alias(self, existing, new):
        """The new livery name gets the same tyre sets as <existing> (where it is named)."""
        q = re.escape(f'"{existing}"')
        self.text, n1 = re.subn(rf'\bCar(\s*=\s*){q}', rf'Cars\1{{ "{existing}", "{new}" }}', self.text)
        self.text, n2 = re.subn(rf'(\bCars\s*=\s*\{{[^}}]*?){q}(?!, "{re.escape(new)}")', rf'\1"{existing}", "{new}"', self.text)
        return n1 + n2


# --- the whole game

def ascii_upper(text):
    import unicodedata
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]+", "_", text.upper()).strip("_")


def read_texts(root):
    """{TEAM_... id: English text} from LOCALISATION.LUA + LOCALISATION_EN.PLOC (empty if not found)."""
    lua = Path(root) / "Common" / "SCRIPTS" / "LOCALISATION.LUA"
    ploc = Path(root) / "Common" / "LOCALISATION" / "LOCALISATION_EN.PLOC"
    if not lua.exists():
        return {}
    ids = {k: int(v) for k, v in re.findall(r"^\s*(TEAM_\w+)\s*=\s*(\d+)\s*,", lua.read_text(encoding="utf-8", errors="replace"), re.M)}
    strings = ploc.read_bytes()[4:].decode("utf-16-le", errors="replace").split("\x00") if ploc.exists() else []
    return {k: (strings[v] if v < len(strings) else "") for k, v in ids.items()}


class Game:
    def __init__(self, root):
        self.root = Path(root)
        tuning = self.root / "Common" / "Tuning"
        self.teams = Teams(tuning / "FACTORIES" / "TEAMS.CFG")
        self.cars = Cars(tuning / "FACTORIES" / "CARS.CFG")
        self.tyres = Tyres(tuning / "FACTORIES" / "TYRES.CFG")
        self.liveries = liveries.LiveriesFile(self.root)
        self.liveries_saved = self.liveries.text
        contests = tuning / "CONTESTS.CFG"
        text = contests.read_text(encoding="utf-8", errors="replace") if contests.exists() else ""
        self.contest_ids = set(re.findall(r"WrcTeamDriversId\.(\w+)", text))
        self.team_names = read_texts(self.root)
        all_text = self.teams.text
        self.nationalities = sorted(set(re.findall(r"WrcNationality\.(\w+)", all_text)))
        self.rallies = sorted(set(re.findall(r'"(Rally_\w+)"', all_text)))
        self.path_names = sorted(set(re.findall(r'PathLastName\s*=\s*"([^"]*)"', all_text)))
        self.skins = sorted(set(re.findall(r'Skin\s*=\s*"([^"]*)"', all_text)))
        self.constructors = sorted(set(re.findall(r'TeamConstructor\s*=\s*"([^"]*)"', all_text)))

    @property
    def modified(self):
        return (self.teams.modified or self.cars.modified or self.tyres.modified
                or self.liveries.text != self.liveries_saved)

    def team_category(self, key):
        car = self.teams.car(key)
        if key.startswith("Legends_"):
            return "Legend"
        cat = self.cars.category(car) if car and car in self.cars.entries else None
        return cat or "?"

    def save(self):
        problems = [p for p in self.check() if p[0] == "error"]
        if problems:
            raise ValueError("not saved, fix these first:\n" + "\n".join(p[1] for p in problems))
        saved = [f.path.name for f in (self.teams, self.cars, self.tyres) if f.save()]
        if self.liveries.text != self.liveries_saved:
            self.liveries.save()
            self.liveries_saved = self.liveries.text
            saved.append(self.liveries.path.name)
        return saved

    # --- new crews
    def free_slots(self):
        """Team ids a new crew can take: [{"id", "key" (disabled block, or None), "tested"}]. Ids of disabled
        blocks come first (the way already used in game); an id another active team uses is not free."""
        t = self.teams
        keys = t.keys()
        # the whole file: other tables (custom liveries) use team ids too
        active = set(re.findall(r"^[ \t]*TeamID\s*=\s*WrcTeamDriversId\.(\w+)", t.text, re.M))
        out, seen = [], set()
        for k in keys:
            tid = t.team_id(k)
            if t.disabled(k) and tid and tid not in active and tid not in seen:
                seen.add(tid)
                out.append({"id": tid, "key": k, "tested": True})
        out += [{"id": tid, "key": None, "tested": False} for tid in UNTESTED_TEAM_IDS if tid not in active | seen]
        return out

    def cars_of(self, category):
        return sorted(c for c in self.cars.entries if self.cars.category(c) == category)

    def new_crew(self, team_id, car, pilot, copilot, number):
        """Adds an active team (in memory; save() writes it) on a free id. pilot / copilot: dicts with Country,
        FirstName, LastName. Everything else (team name, make, level, rallies, colour) comes from a team
        driving the same car, or else the same category: edit it afterwards like any team. Returns the key."""
        if team_id not in {s["id"] for s in self.free_slots()}:
            raise ValueError(f"{team_id} is not a free team id")
        if car not in self.cars.entries:
            raise ValueError(f"{car} is not in CARS.CFG")
        t = self.teams
        active = [k for k in t.keys() if not t.disabled(k)]
        same = [k for k in active if t.car(k) == car]
        cat = self.cars.category(car)
        pool = same or [k for k in active if self.team_category(k) == cat]
        if not pool:
            raise ValueError(f"no active team in category {cat} to take the other fields from")
        template = pool[-1]
        key = "Team_NEW_" + team_id[len("eTeam"):]
        if key in t.keys():
            raise ValueError(f"{key} already exists")
        head = re.search(r"\w+", t.block(template))
        block = t.block(template)
        block = block[:head.start()] + key + block[head.end():]
        at = t.spans()[template][1]
        t.text = t.text[:at] + t.eol + block + t.text[at:]
        t.section = (t.section[0], braced_end(t.text, t.section[0]))
        name = t.get(key, "TeamName")
        squad = [k for k in active if t.get(k, "TeamName") == name]
        numbers = [int(v) for k in squad if (v := t.get(k, "PilotIndexInTeam")) and v.isdigit()]
        t.set(key, "TeamID", f"WrcTeamDriversId.{team_id}")
        t.set(key, "Car", f'"{car}"')
        t.set(key, "PilotInfo", format_info({**pilot, "PathLastName": "CUSTOM", "Skin": "[Generic]"}))
        t.set(key, "CopilotInfo", format_info(copilot))
        t.set(key, "StickerNumber", str(number))
        t.set(key, "TeamOrderIndex", None)                # only the first driver of a squad has it
        t.set(key, "PilotIndexInTeam", str(max(numbers) + 1 if numbers else len(squad)))
        return key

    # --- checks: [("error" | "warning", text)]
    def check(self):
        out = []
        ids, numbers = {}, {}
        for key in self.teams.keys():
            off = self.teams.disabled(key)
            tid = self.teams.team_id(key)
            if off:
                if tid in self.contest_ids:
                    out.append(("warning", f"{key} is disabled but CONTESTS.CFG uses its {tid} (a challenge may break)"))
                continue
            if tid:
                if tid in ids:
                    out.append(("error", f"{key} and {ids[tid]} have the same TeamID {tid}"))
                ids[tid] = key
            car = self.teams.car(key)
            if not car:
                continue
            if car not in self.cars.entries:
                out.append(("error", f"{key}: car {car} is not in CARS.CFG"))
                continue
            cat = self.team_category(key)
            if not self.tyres.named(car) and not self.tyres.category_sets(cat):
                out.append(("warning", f"{key}: {car} has no tyre set in TYRES.CFG (no tyres in game)"))
            if car.upper() not in self.liveries.entries:
                out.append(("warning", f"{key}: {car} has no LIVERIES.LUA entry (no race number or names on the car)"))
            num = self.teams.get(key, "StickerNumber")
            if num and cat != "Legend":
                if (cat, num) in numbers:
                    out.append(("warning", f"{key} and {numbers[(cat, num)]} both have number {num} in {cat}"))
                numbers[(cat, num)] = key
            paclog = self.cars.field(car, "LiveryPaclog")
            if paclog and paclog.upper().startswith("DATA:/"):
                f = liveries._find_ci(self.root / "WIN32", paclog[6:].split("/"))
                if not f or not f.is_file():
                    out.append(("error", f"{key}: livery package {paclog} of {car} not found"))
        return out

    # --- dedicated livery: copy of the car entry's livery folder + PACLOG + CARS/TYRES/LIVERIES entries
    def livery_of(self, car):
        """(PACLOG file, its DATA path, livery folder DATA path, livery folder on disk) of a CARS entry."""
        paclog = self.cars.field(car, "LiveryPaclog")
        if not paclog:
            raise ValueError(f"{car} has no LiveryPaclog: it uses the car's default livery")
        pac = liveries._find_ci(self.root / "WIN32", paclog[6:].split("/"))
        if not pac or not pac.is_file():
            raise ValueError(f"{paclog} not found")
        m = re.search(r"(DATA:/GRAPH/CARS/[^\s\"]+)/BODY_DIFF\.PTX", pac.read_bytes().decode("latin-1"), re.I)
        if not m:
            raise ValueError(f"{pac.name} loads no BODY_DIFF.PTX: no livery folder to copy")
        folder = liveries._find_ci(self.root / "WIN32", m.group(1)[6:].split("/"))
        if not folder:
            raise ValueError(f"{m.group(1)} not found")
        return pac, paclog, m.group(1), folder

    def make_dedicated(self, team, new_car, folder_name):
        """Gives the team its own copy of its current livery. Writes the new livery folder and PACLOG
        at once; CARS.CFG, TYRES.CFG, LIVERIES.LUA and TEAMS.CFG change in memory (save() writes them).
        Returns a description of what was made."""
        if self.liveries.text == self.liveries_saved:  # no pending change here: take the file as it is now
            self.liveries.reload()                       # (the sticker editor may have saved it meanwhile)
            self.liveries_saved = self.liveries.text
        src = self.teams.car(team)
        if not src or src not in self.cars.entries:
            raise ValueError(f"{team}: its car {src} is not in CARS.CFG")
        if not re.fullmatch(r"[A-Za-z_]\w*", new_car) or new_car in self.cars.entries:
            raise ValueError(f"{new_car}: not a valid new CARS.CFG name (letters, digits, _; must not exist)")
        if not re.fullmatch(r"[A-Z0-9_]+", folder_name):
            raise ValueError(f"{folder_name}: use capitals, digits and _ for the folder name")
        pac, pac_data, src_dir_data, src_dir = self.livery_of(src)
        new_dir = src_dir.parent / folder_name
        new_dir_data = src_dir_data.rsplit("/", 1)[0] + "/" + folder_name
        new_pac = pac.parent / f"{folder_name}.PACLOG"
        new_pac_data = pac_data.rsplit("/", 1)[0] + f"/{folder_name}.PACLOG"
        if new_dir.exists() or new_pac.exists():
            raise ValueError(f"{new_dir} or {new_pac.name} already exists")
        old_b, new_b = (src_dir_data + "/").encode(), (new_dir_data + "/").encode()
        new_dir.mkdir(parents=True)
        for f in sorted(src_dir.iterdir()):
            if f.is_file():
                data = f.read_bytes()
                (new_dir / f.name).write_bytes(rewrite_pma_paths(data, old_b, new_b) if f.suffix.upper() == ".PMA" else data)
        text = pac.read_bytes().decode("latin-1")
        text = re.sub(re.escape(src_dir_data + "/"), lambda m: new_dir_data + "/", text, flags=re.I)
        new_pac.write_bytes(text.encode("latin-1"))
        # CARS.CFG: copy of the entry with the new name and package
        block = self.cars.block(src)
        block = re.sub(rf"^(\t+){re.escape(src)}\b", lambda m: m.group(1) + new_car, block, count=1, flags=re.M)
        block = re.sub(r'(LiveryPaclog\s*=\s*)"[^"]*"', lambda m: m.group(1) + f'"{new_pac_data}"', block, count=1)
        self.cars.insert_after(src, block)
        # TYRES.CFG: same sets where the source is named (otherwise it gets them by category)
        tyres = self.tyres.add_alias(src, new_car) if self.tyres.named(src) else 0
        # LIVERIES.LUA: same stickers, on the new texture
        stickers = ""
        if src.upper() in self.liveries.entries:
            self.liveries.add_entry(new_car.upper(), new_dir_data + "/BODY_DIFF.PTX", self.liveries.stickers(src.upper()))
            stickers = ", stickers copied"
        self.teams.set(team, "Car", f'"{new_car}"')
        return (f"{new_car}: livery folder {new_dir_data}, package {new_pac_data}"
                + (f", tyre sets of {src} ({tyres})" if tyres else ", tyres by category") + stickers)


def rewrite_pma_paths(data, old, new):
    """Replaces the path prefix old with new (case-insensitive) in the DATA:/ strings of a .PMA,
    updating the int32 length in front of each string."""
    out, i, lo = bytearray(), 0, old.upper()
    while i < len(data):
        n = int.from_bytes(data[i:i + 4], "little") if i + 4 <= len(data) else 0
        if 6 <= n <= 300 and data[i + 4:i + 10] == b"DATA:/":
            path = data[i + 4:i + 4 + n]
            if path.upper().startswith(lo):
                path = new + path[len(old):]
            out += len(path).to_bytes(4, "little") + path
            i += 4 + n
        else:
            out.append(data[i])
            i += 1
    return bytes(out)
