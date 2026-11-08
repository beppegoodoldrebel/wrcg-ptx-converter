# Teams & drivers window: edit the teams of TEAMS.CFG (names, crew, number, level, car...), enable or
# disable them (a disabled team is a free place for a new crew: TeamIDs cannot be created), give a team
# its own livery or let it share one, and check the whole set before saving (gamedata.py).

import tkinter as tk
from tkinter import colorchooser, messagebox, ttk

import gamedata
import sticker_editor

LEVEL_LABELS = (("Global", "Global"), ("Limit", "Limit"), ("LevelSnow", "Snow"), ("LevelTarmac", "Tarmac"),
                ("LevelGravel", "Gravel"), ("HighSpeed", "High speed"), ("MiddleSpeed", "Mid speed"),
                ("LowSpeed", "Low speed"), ("Fiability", "Reliability"))
LIMITS = ("PilotLimit.Best", "PilotLimit.Average", "PilotLimit.Bad")


class TeamEditor(tk.Toplevel):
    def __init__(self, master, root):
        super().__init__(master)
        self.game = gamedata.Game(root)
        self.title("Teams & drivers")
        self.geometry("1450x860")
        self.key = None
        self.build_ui()
        self.fill_tree()
        self.protocol("WM_DELETE_WINDOW", self.close)

    # --- UI
    def build_ui(self):
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        ttk.Label(top, text=str(self.game.teams.path), foreground="#555").pack(side="left")
        self.v_off = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Show disabled teams (free places)", variable=self.v_off,
                        command=self.fill_tree).pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        cols = ("driver", "codriver", "num", "car", "state")
        self.tree = ttk.Treeview(body, columns=cols, selectmode="browse")
        for c, text, w in (("#0", "Team", 230), ("driver", "Driver", 150), ("codriver", "Co-driver", 140),
                           ("num", "#", 40), ("car", "Car (CARS.CFG entry)", 260), ("state", "State", 70)):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, stretch=c in ("#0", "car"))
        self.tree.tag_configure("off", foreground="#999")
        self.tree.tag_configure("edited", foreground="#b05000")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        form = ttk.Frame(body, padding=(10, 0))
        form.grid(row=0, column=2, sticky="ns")
        self.v = {}

        def entry(parent, row, col, name, label, width=14, values=None, readonly=False):
            ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 4), pady=2)
            var = tk.StringVar()
            if values is not None:
                w = ttk.Combobox(parent, textvariable=var, values=values, width=width,
                                 state="readonly" if readonly else "normal")
            else:
                w = ttk.Entry(parent, textvariable=var, width=width)
            w.grid(row=row, column=col + 1, sticky="we", pady=2)
            self.v[name] = var
            return w

        g = self.game
        team_names = [f"{k} – {t}" for k, t in sorted(g.team_names.items())]
        t = ttk.LabelFrame(form, text="Team", padding=6)
        t.pack(fill="x")
        entry(t, 0, 0, "TeamID", "Team ID", 30).configure(state="readonly")
        entry(t, 1, 0, "TeamName", "Name", 30, team_names)
        entry(t, 2, 0, "TeamConstructor", "Make", 30, g.constructors)
        self.c_car = entry(t, 3, 0, "Car", "Car", 30, sorted(g.cars.entries))
        f = ttk.Frame(t)
        f.grid(row=4, column=0, columnspan=2, sticky="w")
        entry(f, 0, 0, "StickerNumber", "Number", 5)
        entry(f, 0, 2, "TeamColor", "  Colour", 8)
        self.swatch = tk.Label(f, width=3, relief="solid", borderwidth=1, cursor="hand2")
        self.swatch.grid(row=0, column=4, padx=4)
        self.swatch.bind("<Button-1>", self.pick_colour)
        f = ttk.Frame(t)
        f.grid(row=5, column=0, columnspan=2, sticky="w")
        entry(f, 0, 0, "TeamOrderIndex", "Team order", 5)
        entry(f, 0, 2, "PilotIndexInTeam", "  Driver in team", 5)

        for title, prefix, full in (("Driver", "P", True), ("Co-driver", "C", False)):
            fr = ttk.LabelFrame(form, text=title, padding=6)
            fr.pack(fill="x", pady=(6, 0))
            entry(fr, 0, 0, prefix + "Country", "Nationality", 8, g.nationalities, readonly=True)
            entry(fr, 1, 0, prefix + "FirstName", "First name", 30)
            entry(fr, 2, 0, prefix + "LastName", "Last name", 30)
            if full:
                entry(fr, 3, 0, prefix + "PathLastName", "Model (PathLastName)", 30, g.path_names)
                entry(fr, 4, 0, prefix + "Skin", "Suit (Skin)", 30, g.skins)

        lv = ttk.LabelFrame(form, text="AI level", padding=6)
        lv.pack(fill="x", pady=(6, 0))
        for i, (k, label) in enumerate(LEVEL_LABELS):
            entry(lv, i // 3, (i % 3) * 2, "L" + k, label, 16 if k == "Limit" else 6,
                  LIMITS if k == "Limit" else None, readonly=k == "Limit")
        rl = ttk.Frame(form)
        rl.pack(fill="x", pady=(6, 0))
        entry(rl, 0, 0, "Rallies", "Rallies", 40)
        ttk.Label(form, foreground="#666", wraplength=420, text="Rallies: comma separated, e.g. Rally_02, Rally_03 "
                  f"(used in the file: {', '.join(g.rallies)}). Empty fields are left out of the team.").pack(anchor="w")

        b = ttk.Frame(form)
        b.pack(fill="x", pady=8)
        for i, (text, cmd) in enumerate((("Apply", self.apply), ("New crew...", self.new_crew), ("Enable / disable", self.toggle),
                                         ("Copy crew from team...", self.copy_crew), ("Dedicated livery...", self.dedicated),
                                         ("Stickers...", self.stickers), ("Check", self.show_check))):
            ttk.Button(b, text=text, command=cmd).grid(row=i // 3, column=i % 3, sticky="we", padx=2, pady=2)
        for c in range(3):
            b.columnconfigure(c, weight=1)
        ttk.Button(form, text="Save all", command=self.save).pack(fill="x")
        ttk.Button(form, text="Reload from files", command=self.reload).pack(fill="x", pady=(4, 0))
        ttk.Label(form, foreground="#666", wraplength=420, justify="left", text=(
            "Apply keeps the changes in memory; Save all writes TEAMS.CFG, CARS.CFG, TYRES.CFG and LIVERIES.LUA "
            "(the first save of each keeps the original in an ORIGINALI folder next to it). Team IDs come from "
            "the game executable, so places are limited: New crew shows how many are left. Shared livery: choose another "
            "Car. Mod installers that write these files replace the changes.")).pack(fill="x", pady=(6, 0))
        self.status = tk.StringVar(value="Select a team.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w", padding=4).pack(fill="x", padx=8, pady=6)
        self.bind("<Return>", lambda e: self.apply())

    # --- list
    def fill_tree(self):
        g = self.game
        sel = self.key
        self.tree.delete(*self.tree.get_children())
        groups = {}
        keys = g.teams.keys()
        cats = {k: g.team_category(k) for k in keys}
        order = list(gamedata.CATEGORY_ORDER) + sorted(set(cats.values()) - set(gamedata.CATEGORY_ORDER))
        for c in order:
            if c in cats.values():
                groups[c] = self.tree.insert("", "end", iid="cat|" + c, text=c, open=c != "Legend")
        for k in keys:
            off = g.teams.disabled(k)
            if off and not self.v_off.get():
                continue
            p, c = g.teams.info(k, "PilotInfo") or {}, g.teams.info(k, "CopilotInfo") or {}
            name = lambda d: f"{d.get('FirstName') or ''} {d.get('LastName') or ''}".strip()
            self.tree.insert(groups[cats[k]], "end", iid=k, text=k, tags=("off",) if off else (),
                             values=(name(p), name(c), g.teams.get(k, "StickerNumber") or "", g.teams.car(k) or "",
                                     "disabled" if off else "active"))
        if sel and self.tree.exists(sel):
            self.tree.selection_set(sel)
            self.tree.see(sel)

    def on_select(self, _e=None):
        sel = self.tree.selection()
        if not sel or sel[0].startswith("cat|"):
            return
        if self.key and self.key != sel[0] and self.form_changed():
            if messagebox.askyesno("Teams", f"Apply the changes to {self.key} first?", parent=self):
                if not self.apply(refresh=False):
                    return self.tree.selection_set(self.key)
        self.key = sel[0]
        self.fill_form()

    # --- form <-> team
    def form_values(self, key):
        g, t = self.game, self.game.teams
        out = {"TeamID": t.get(key, "TeamID") or ""}
        name = t.get(key, "TeamName") or ""
        tid = name.split(".")[-1]
        out["TeamName"] = f"{tid} – {g.team_names[tid]}" if tid in g.team_names else name
        out["TeamConstructor"] = (t.get(key, "TeamConstructor") or "").strip('"')
        out["Car"] = t.car(key) or ""
        out["StickerNumber"] = t.get(key, "StickerNumber") or ""
        out["TeamColor"] = (t.get(key, "TeamColor") or "").strip('"')
        out["TeamOrderIndex"] = t.get(key, "TeamOrderIndex") or ""
        out["PilotIndexInTeam"] = t.get(key, "PilotIndexInTeam") or ""
        for prefix, field in (("P", "PilotInfo"), ("C", "CopilotInfo")):
            info = t.info(key, field) or {}
            for k in ("Country", "FirstName", "LastName", "PathLastName", "Skin"):
                out[prefix + k] = info.get(k) or ""
        level = gamedata.parse_level(t.get(key, "PilotLevel") or "")
        for k, _ in LEVEL_LABELS:
            out["L" + k] = level.get(k, "")
        out["Rallies"] = ", ".join(gamedata.parse_rallies(t.get(key, "Rallies") or ""))
        return out

    def fill_form(self):
        for name, value in self.form_values(self.key).items():
            if name in self.v:
                self.v[name].set(value)
        self.show_swatch()
        g = self.game
        cat = g.team_category(self.key)
        same = sorted(c for c in g.cars.entries if g.cars.category(c) == cat)
        self.c_car["values"] = same + ["—"] + sorted(set(g.cars.entries) - set(same))
        off = g.teams.disabled(self.key)
        self.status.set(f"{self.key}: {cat}, {'disabled (free place)' if off else 'active'}"
                        + (f", used by the challenges of CONTESTS.CFG" if g.teams.team_id(self.key) in g.contest_ids else ""))

    def form_changed(self):
        if not self.key:
            return False
        now = self.form_values(self.key)
        return any(self.v[n].get().strip() != str(now.get(n, "")).strip() for n in self.v if n != "TeamID")

    def apply(self, refresh=True):
        """Form -> TEAMS.CFG text in memory (only the changed fields). Returns False on bad input."""
        if not self.key:
            return False
        t, key, v = self.game.teams, self.key, {n: var.get().strip() for n, var in self.v.items()}
        old = self.form_values(key)
        try:
            for n in ("StickerNumber", "TeamOrderIndex", "PilotIndexInTeam") + tuple("L" + k for k, _ in LEVEL_LABELS if k != "Limit"):
                if v[n] and not v[n].lstrip("-").isdigit():
                    raise ValueError(f"{n}: not a whole number")
            if v["TeamColor"] and (len(v["TeamColor"]) != 6 or any(c not in "0123456789abcdefABCDEF" for c in v["TeamColor"])):
                raise ValueError("Colour: 6 hex digits, e.g. 30A9DE")
            if v["Car"] and v["Car"] not in self.game.cars.entries:
                raise ValueError(f"Car {v['Car']} is not in CARS.CFG")
            for prefix in ("P", "C"):
                if not v[prefix + "Country"] or not v[prefix + "LastName"]:
                    raise ValueError("Driver and co-driver need a nationality and a last name")
                for n in ("FirstName", "LastName", "PathLastName", "Skin"):  # the co-driver has no model / suit
                    if '"' in v.get(prefix + n, ""):
                        raise ValueError("Names cannot contain \"")
        except ValueError as e:
            messagebox.showerror("Teams", str(e), parent=self)
            return False

        def changed(*names):
            return any(v[n] != str(old.get(n, "")) for n in names)

        if changed("TeamName"):
            t.set(key, "TeamName", "LocalesId." + v["TeamName"].split(" – ")[0].strip())
        if changed("TeamConstructor"):
            t.set(key, "TeamConstructor", f'"{v["TeamConstructor"]}"' if v["TeamConstructor"] else None)
        if changed("Car"):
            t.set(key, "Car", f'"{v["Car"]}"')
        for n in ("StickerNumber", "TeamOrderIndex", "PilotIndexInTeam"):
            if changed(n):
                t.set(key, n, v[n] or None)
        if changed("TeamColor"):
            t.set(key, "TeamColor", f'"{v["TeamColor"].upper()}"' if v["TeamColor"] else None)
        for prefix, field in (("P", "PilotInfo"), ("C", "CopilotInfo")):
            names = [prefix + k for k in ("Country", "FirstName", "LastName", "PathLastName", "Skin") if prefix + k in v]
            if changed(*names):
                t.set(key, field, gamedata.format_info({k[1:]: v[k] for k in names}))
        if changed(*("L" + k for k, _ in LEVEL_LABELS)):
            level = gamedata.parse_level(t.get(key, "PilotLevel") or "")
            for k, _ in LEVEL_LABELS:
                if v["L" + k]:
                    level[k] = v["L" + k]
                else:
                    level.pop(k, None)
            t.set(key, "PilotLevel", gamedata.format_level(level))
        if changed("Rallies"):
            rallies = [r.strip() for r in v["Rallies"].split(",") if r.strip()]
            t.set(key, "Rallies", gamedata.format_rallies(rallies) if rallies else None)
        self.mark()
        if refresh:
            self.fill_tree()
            self.fill_form()
        return True

    def mark(self):
        self.title(("* " if self.game.modified else "") + "Teams & drivers")

    def show_swatch(self):
        c = self.v["TeamColor"].get().strip()
        try:
            self.swatch.configure(background="#" + c if len(c) == 6 else "SystemButtonFace")
        except tk.TclError:
            self.swatch.configure(background="SystemButtonFace")

    def pick_colour(self, _e=None):
        c = self.v["TeamColor"].get().strip()
        rgb, hexa = colorchooser.askcolor(color="#" + c if len(c) == 6 else None, parent=self)
        if hexa:
            self.v["TeamColor"].set(hexa[1:].upper())
            self.show_swatch()

    # --- actions
    def toggle(self):
        if not self.key:
            return
        g, key = self.game, self.key
        off = g.teams.disabled(key)
        if not off and g.teams.team_id(key) in g.contest_ids and not messagebox.askyesno(
                "Teams", f"{key} is used by challenges in CONTESTS.CFG: disabling it may break them. Disable anyway?",
                parent=self):
            return
        g.teams.set_enabled(key, off)
        self.mark()
        self.fill_tree()
        self.fill_form()

    def new_crew(self):
        """Dialog for a new crew on a free team id; returns it (or None when no id is left)."""
        if self.key and self.form_changed() and not self.apply(refresh=False):
            return None
        g = self.game
        slots = g.free_slots()
        if not slots:
            messagebox.showinfo("Teams", "No free team id is left: the ids are fixed in the game executable.", parent=self)
            return None
        dlg = tk.Toplevel(self)
        dlg.title("New crew")
        dlg.transient(self)
        tested = sum(s["tested"] for s in slots)
        ttk.Label(dlg, padding=8, wraplength=520, text=(
            f"Free places: {len(slots)} ({tested} already used this way, {len(slots) - tested} never tried in game). "
            "Team name, make, level, rallies and colour come from a team with the same car or category: "
            "edit them afterwards in the form.")).grid(row=0, column=0, columnspan=4, sticky="w")
        labels = [f"{s['id']}" + ("" if s["tested"] else "  (never tried in game)") for s in slots]
        cats = [c for c in gamedata.CATEGORY_ORDER if g.cars_of(c)]
        v = {n: tk.StringVar() for n in ("slot", "cat", "car", "PCountry", "PFirstName", "PLastName",
                                         "CCountry", "CFirstName", "CLastName", "number")}
        v["slot"].set(labels[0])
        v["cat"].set(cats[0])

        def row(r, text, name, values=None, width=48):
            ttk.Label(dlg, text=text, padding=(8, 2)).grid(row=r, column=0, sticky="w")
            w = (ttk.Combobox(dlg, textvariable=v[name], values=values, width=width, state="readonly")
                 if values is not None else ttk.Entry(dlg, textvariable=v[name], width=width + 3))
            w.grid(row=r, column=1, columnspan=3, sticky="we", padx=8, pady=2)
            return w

        row(1, "Team id", "slot", labels)
        row(2, "Category", "cat", cats)
        car_box = row(3, "Car (livery)", "car", [])

        def cars_for_category(_e=None):
            cars = g.cars_of(v["cat"].get())
            car_box["values"] = cars
            v["car"].set(cars[0] if cars else "")
        dlg.grid_slaves(row=2, column=1)[0].bind("<<ComboboxSelected>>", cars_for_category)
        cars_for_category()
        row(4, "Driver nationality", "PCountry", g.nationalities, 8)
        row(5, "Driver first name", "PFirstName")
        row(6, "Driver last name", "PLastName")
        row(7, "Co-driver nationality", "CCountry", g.nationalities, 8)
        row(8, "Co-driver first name", "CFirstName")
        row(9, "Co-driver last name", "CLastName")
        row(10, "Race number", "number", width=8)

        def ok():
            f = {n: var.get().strip() for n, var in v.items()}
            try:
                key = self.create_crew(slots[labels.index(f["slot"])]["id"], f)
            except ValueError as e:
                return messagebox.showerror("Teams", str(e), parent=dlg)
            dlg.destroy()
            self.key = key
            self.mark()
            self.fill_tree()
            self.fill_form()
            self.status.set(f"{key} added on {f['slot'].split()[0]} (not saved yet). "
                            f"Free places left: {len(g.free_slots())}.")
        ttk.Button(dlg, text="Create", command=ok).grid(row=11, column=0, columnspan=4, pady=8)
        return dlg

    def create_crew(self, team_id, f):
        """The checks of the dialog, then Game.new_crew. f: the dialog's fields."""
        for prefix, who in (("P", "Driver"), ("C", "Co-driver")):
            if not f[prefix + "Country"] or not f[prefix + "LastName"]:
                raise ValueError(f"{who}: nationality and last name are needed")
            if '"' in f[prefix + "FirstName"] + f[prefix + "LastName"]:
                raise ValueError("Names cannot contain \"")
        if not f["number"].isdigit():
            raise ValueError("Race number: a whole number")
        if not f["car"]:
            raise ValueError("Choose a car")
        info = lambda p: {k: f[p + k] for k in ("Country", "FirstName", "LastName")}
        return self.game.new_crew(team_id, f["car"], info("P"), info("C"), f["number"])

    def copy_crew(self):
        if not self.key:
            return
        dlg = tk.Toplevel(self)
        dlg.title("Copy crew")
        dlg.transient(self)
        ttk.Label(dlg, padding=8, text="Copy driver, co-driver and AI level from this team (e.g. a legend card):").pack(anchor="w")
        teams = self.game.teams
        items = []
        for k in teams.keys():
            p = teams.info(k, "PilotInfo") or {}
            items.append(f"{k} – {p.get('FirstName') or ''} {p.get('LastName') or ''}".rstrip())
        var = tk.StringVar()
        cb = ttk.Combobox(dlg, textvariable=var, values=items, width=60, state="readonly")
        cb.pack(padx=8, fill="x")

        def ok():
            src = var.get().split(" – ")[0]
            if not src:
                return
            for f in ("PilotInfo", "CopilotInfo", "PilotLevel"):
                value = teams.get(src, f)
                if value:
                    teams.set(self.key, f, value)
            dlg.destroy()
            self.mark()
            self.fill_tree()
            self.fill_form()
            self.status.set(f"Crew of {src} copied to {self.key} (not saved yet).")
        ttk.Button(dlg, text="Copy", command=ok).pack(pady=8)

    def dedicated(self):
        if not self.key:
            return
        if self.form_changed() and not self.apply(refresh=False):
            return
        g, key = self.game, self.key
        src = g.teams.car(key)
        try:
            _, _, src_dir_data, _ = g.livery_of(src)
        except ValueError as e:
            return messagebox.showerror("Teams", str(e), parent=self)
        sharing = [k for k in g.teams.keys() if k != key and g.teams.car(k) == src]
        last = (g.teams.info(key, "PilotInfo") or {}).get("LastName") or "NEW"
        folder = gamedata.ascii_upper(last)
        dlg = tk.Toplevel(self)
        dlg.title("Dedicated livery")
        dlg.transient(self)
        ttk.Label(dlg, padding=8, wraplength=560, justify="left", text=(
            f"{key} now drives {src} (livery folder {src_dir_data})"
            + (f", shared with {', '.join(sharing)}" if sharing else "") + ".\n\nA copy of that livery becomes this "
            "team's own: new livery folder next to it, new PACLOG, new CARS.CFG entry with the same tyres and stickers. "
            "All the changes are then saved.")).pack(anchor="w")
        f = ttk.Frame(dlg, padding=8)
        f.pack(fill="x")
        v_folder, v_car = tk.StringVar(value=folder), tk.StringVar(value=f"{src}_{folder}")
        ttk.Label(f, text="Livery folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=v_folder, width=40).grid(row=0, column=1, pady=2)
        ttk.Label(f, text="CARS.CFG entry").grid(row=1, column=0, sticky="w")
        ttk.Entry(f, textvariable=v_car, width=40).grid(row=1, column=1, pady=2)

        def ok():
            try:
                info = g.make_dedicated(key, v_car.get().strip(), v_folder.get().strip())
                saved = g.save()
            except (ValueError, OSError) as e:
                return messagebox.showerror("Teams", str(e), parent=dlg)
            dlg.destroy()
            self.mark()
            self.fill_tree()
            self.fill_form()
            messagebox.showinfo("Teams", f"{info}\n\nSaved: {', '.join(saved)}", parent=self)
        ttk.Button(dlg, text="Create and save", command=ok).pack(pady=8)

    def stickers(self):
        if not self.key:
            return
        g = self.game
        if g.liveries.text != g.liveries_saved:
            return messagebox.showwarning("Teams", "Save all first: LIVERIES.LUA has changes not saved yet.", parent=self)
        try:
            folder = g.livery_of(g.teams.car(self.key))[3]
            sticker_editor.StickerEditor(self, folder)
        except (ValueError, OSError) as e:
            messagebox.showerror("Teams", str(e), parent=self)

    def show_check(self):
        if self.form_changed() and not self.apply():
            return
        problems = self.game.check()
        if not problems:
            return messagebox.showinfo("Teams", "No problems found.", parent=self)
        messagebox.showwarning("Teams", "\n".join(f"{lvl.upper()}: {msg}" for lvl, msg in problems), parent=self)

    def save(self):
        if self.form_changed() and not self.apply():
            return False
        g = self.game
        if not g.modified:
            self.status.set("Nothing to save.")
            return True
        warnings = [m for lvl, m in g.check() if lvl == "warning"]
        if warnings and not messagebox.askyesno("Teams", "Warnings:\n\n" + "\n".join(warnings) + "\n\nSave anyway?", parent=self):
            return False
        try:
            saved = g.save()
        except (ValueError, OSError) as e:
            messagebox.showerror("Teams", str(e), parent=self)
            return False
        self.mark()
        self.status.set(f"Saved: {', '.join(saved)}. Restart the game to see the changes.")
        return True

    def reload(self):
        if (self.game.modified or self.form_changed()) and not messagebox.askyesno(
                "Teams", "Discard the changes not saved?", parent=self):
            return
        self.game = gamedata.Game(self.game.root)
        self.mark()
        self.fill_tree()
        if self.key and self.key in self.game.teams.keys():
            self.fill_form()

    def close(self):
        if self.game.modified or self.form_changed():
            answer = messagebox.askyesnocancel("Teams", "Save the changes?", parent=self)
            if answer is None or (answer and not self.save()):
                return
        self.destroy()
