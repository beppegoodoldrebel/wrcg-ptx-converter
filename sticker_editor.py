# Sticker editor (opened from the livery workspace): shows the livery's BODY_DIFF with the boxes of the
# stickers the game draws on it (LIVERIES.LUA: names, numbers, flags, rally plates...) and lets you move,
# resize, rotate, add, delete and retype them, then save them into the game's LIVERIES.LUA (liveries.py).
#
# Mouse: click a box to select it, drag it to move it, drag the square handle to resize it, drag the round
# handle to rotate it (Shift: 15° steps). Middle button drags the view, wheel scrolls (Shift: sideways),
# Ctrl+wheel zooms. Keys: arrows move the selected sticker by one texel of the 4096 texture (Shift: 10),
# Delete removes it, Ctrl+D duplicates, Ctrl+Z / Ctrl+Y undo / redo, Ctrl+S saves, Esc deselects.

import math
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import liveries
import workspace

BASE = 1024              # size of the texture preview (a mipmap of BODY_DIFF)
ZOOMS = (0.5, 1, 2, 3, 4)
NUDGE = 1 / 4096         # arrow keys: one texel of a 4096 texture
HANDLE = 6               # handle radius in screen pixels


def type_colour(t):
    if "Black" in t and "Name" in t:
        return "#ff40ff"
    if "Name" in t:
        return "#00e5ff"
    if "Flag" in t:
        return "#30ff70"
    if "Number" in t:
        return "#ffd400"
    if t.startswith("Career"):
        return "#ff5050"
    if "Country" in t or "WindScreen" in t:
        return "#ff9900"
    return "#ffffff"


def _photo(w, h, rgb):
    # binary PPM: tk.PhotoImage reads it directly
    return tk.PhotoImage(data=b"P6 %d %d 255\n" % (w, h) + rgb, format="PPM")


class StickerEditor(tk.Toplevel):
    def __init__(self, master, livery):
        super().__init__(master)
        self.livery = Path(livery)
        self.root_dir = liveries.game_root(self.livery)
        if not self.root_dir:
            self.destroy()
            raise ValueError("The livery folder is not inside the game's WIN32 folder: LIVERIES.LUA not found.")
        self.lf = liveries.LiveriesFile(self.root_dir)
        self.keys = self.lf.keys_for_livery(self.livery)
        if not self.keys:
            self.destroy()
            raise ValueError(f"No entry of LIVERIES.LUA uses {self.livery.name}\\BODY_DIFF.PTX: this livery has no "
                             "stickers to edit.")
        self.title(f"Stickers – {self.livery.parent.name}\\{self.livery.name}")
        self.geometry("1400x900")
        self.key = self.keys[0]
        self.stickers, self.sel = [], None
        self.undo_stack, self.redo_stack = [], []
        self.dirty = False
        self.zoom = 1
        self.images, self.rgb, self.rgb_masked = {}, None, None
        self.drag = None
        self.build_ui()
        self.load_key(self.key)
        self.protocol("WM_DELETE_WINDOW", self.close)
        # the texture is decoded in a thread; the window polls for the result (Tk calls stay in its thread)
        self.decoded = None
        threading.Thread(target=self.decode_texture, daemon=True).start()
        self.after(100, self.poll_texture)

    # --- UI
    def build_ui(self):
        top = ttk.Frame(self, padding=(8, 6))
        top.pack(fill="x")
        ttk.Label(top, text="Entry:").pack(side="left")
        self.v_key = tk.StringVar(value=self.key)
        cb = ttk.Combobox(top, textvariable=self.v_key, values=self.keys, state="readonly", width=40)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", self.change_key)
        self.v_all = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, variable=self.v_all, text=f"Save to all {len(self.keys)} entries of this livery"
                        if len(self.keys) > 1 else "").pack(side="left", padx=8)
        if len(self.keys) == 1:
            self.v_all.set(False)
        ttk.Label(top, text="Zoom:").pack(side="left", padx=(16, 2))
        self.v_zoom = tk.StringVar(value="100%")
        z = ttk.Combobox(top, textvariable=self.v_zoom, values=[f"{int(v * 100)}%" for v in ZOOMS], state="readonly", width=6)
        z.pack(side="left")
        z.bind("<<ComboboxSelected>>", lambda e: self.set_zoom(ZOOMS[z.current()]))
        self.v_mask = tk.BooleanVar(value=False)  # off by default: the texture as it is
        ttk.Checkbutton(top, variable=self.v_mask, text="Dim non-painted parts (mask)",
                        command=self.show_image).pack(side="left", padx=12)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, padx=8)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        self.cv = tk.Canvas(body, background="#202020", highlightthickness=0,
                            scrollregion=(0, 0, BASE, BASE))
        self.cv.grid(row=0, column=0, sticky="nsew")
        sy = ttk.Scrollbar(body, orient="vertical", command=self.cv.yview)
        sx = ttk.Scrollbar(body, orient="horizontal", command=self.cv.xview)
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="we")
        self.cv.configure(xscrollcommand=sx.set, yscrollcommand=sy.set)
        self.cv.create_text(BASE / 2, BASE / 2, text="Loading texture...", fill="#aaa", tags="loading")
        self.cv.bind("<ButtonPress-1>", self.press)
        self.cv.bind("<B1-Motion>", self.motion)
        self.cv.bind("<ButtonRelease-1>", self.release)
        self.cv.bind("<ButtonPress-2>", lambda e: self.cv.scan_mark(e.x, e.y))
        self.cv.bind("<B2-Motion>", lambda e: self.cv.scan_dragto(e.x, e.y, gain=1))
        self.cv.bind("<MouseWheel>", self.wheel)
        self.cv.bind("<Shift-MouseWheel>", lambda e: self.cv.xview_scroll(-1 if e.delta > 0 else 1, "units"))
        self.cv.bind("<Control-MouseWheel>", self.ctrl_wheel)

        side = ttk.Frame(body, padding=(8, 0))
        side.grid(row=0, column=2, rowspan=2, sticky="ns")
        cols = ("type", "x", "y", "rot")
        self.tree = ttk.Treeview(side, columns=cols, show="headings", height=16, selectmode="browse")
        for c, text, w in (("type", "Type", 170), ("x", "X", 70), ("y", "Y", 70), ("rot", "Rotation", 75)):
            self.tree.heading(c, text=text)
            self.tree.column(c, width=w, stretch=False)
        self.tree.pack(fill="x")
        self.tree.bind("<<TreeviewSelect>>", self.tree_select)

        form = ttk.LabelFrame(side, text="Selected sticker", padding=6)
        form.pack(fill="x", pady=8)
        self.v_type = tk.StringVar()
        ttk.Label(form, text="Type").grid(row=0, column=0, sticky="w")
        self.c_type = ttk.Combobox(form, textvariable=self.v_type, values=self.lf.types, state="readonly", width=26)
        self.c_type.grid(row=0, column=1, columnspan=3, sticky="we", pady=2)
        self.c_type.bind("<<ComboboxSelected>>", lambda e: self.apply_fields())
        self.v = {}
        for row, pair in enumerate((("x", "y"), ("w", "h"), ("rotation", "order")), start=1):
            for col, name in enumerate(pair):
                label = {"x": "X", "y": "Y", "w": "Width", "h": "Height", "rotation": "Rotation", "order": "Order"}[name]
                ttk.Label(form, text=label).grid(row=row, column=col * 2, sticky="w", padx=(0 if col == 0 else 8, 2))
                var = tk.StringVar()
                e = ttk.Entry(form, textvariable=var, width=11)
                e.grid(row=row, column=col * 2 + 1, pady=2)
                e.bind("<Return>", lambda ev: self.apply_fields())
                e.bind("<FocusOut>", lambda ev: self.apply_fields())
                self.v[name] = var
        ttk.Label(form, foreground="#666", wraplength=330, text="X, Y, width and height in texture units (0-1); "
                  "rotation in degrees, clockwise. Enter applies.").grid(row=4, column=0, columnspan=4, sticky="w", pady=(4, 0))

        btns = ttk.Frame(side)
        btns.pack(fill="x")
        for i, (text, cmd) in enumerate((("Add", self.add), ("Duplicate", self.duplicate), ("Delete", self.delete),
                                         ("Undo", self.undo), ("Redo", self.redo), ("Copy from entry...", self.copy_from),
                                         ("Reload from file", self.reload), ("Original stickers", self.original))):
            ttk.Button(btns, text=text, command=cmd).grid(row=i // 3, column=i % 3, sticky="we", padx=2, pady=2)
        for c in range(3):
            btns.columnconfigure(c, weight=1)
        ttk.Button(side, text="Save to LIVERIES.LUA", command=self.save).pack(fill="x", pady=(10, 2))
        ttk.Label(side, foreground="#666", wraplength=340, justify="left", text=(
            f"{self.lf.path}\nThe first save keeps the original file in Tuning\\{liveries.BACKUP}. "
            "The game reads LIVERIES.LUA when it starts. Tools that regenerate LIVERIES.LUA (e.g. a mod installer) "
            "overwrite these changes.")).pack(fill="x")

        self.status = tk.StringVar()
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w", padding=4).pack(fill="x", padx=8, pady=6)
        for seq, fn in (("<Left>", lambda e: self.nudge(e, -1, 0)), ("<Right>", lambda e: self.nudge(e, 1, 0)),
                        ("<Up>", lambda e: self.nudge(e, 0, -1)), ("<Down>", lambda e: self.nudge(e, 0, 1)),
                        ("<Shift-Left>", lambda e: self.nudge(e, -10, 0)), ("<Shift-Right>", lambda e: self.nudge(e, 10, 0)),
                        ("<Shift-Up>", lambda e: self.nudge(e, 0, -10)), ("<Shift-Down>", lambda e: self.nudge(e, 0, 10)),
                        ("<Delete>", lambda e: self.typing(e) or self.delete()),
                        ("<Control-d>", lambda e: self.duplicate()), ("<Control-z>", lambda e: self.undo()),
                        ("<Control-y>", lambda e: self.redo()), ("<Control-s>", lambda e: self.save()),
                        ("<Escape>", lambda e: self.select(None))):
            self.bind(seq, fn)

    # --- texture
    def decode_texture(self):
        try:
            items = [i for i in workspace.scan(self.livery) if i.ptx.stem.upper() == "BODY_DIFF" and i.editable]
            colour = next((i for i in items if i.part in ("colour", "full")), None)
            mask = next((i for i in items if i.part == "mask"), None)
            w, h, rgb = workspace.preview(colour, BASE)
            dim = None
            if mask:
                _, _, m = workspace.preview(mask, BASE)
                d = bytearray(rgb)
                for p in range(0, len(d), 3):
                    if m[p] > 127:  # mask 255 = not painted bodywork (glass, interior, mechanics...)
                        d[p], d[p + 1], d[p + 2] = d[p] // 3, d[p + 1] // 3, d[p + 2] // 3
                dim = bytes(d)
            self.decoded = (w, h, rgb, dim)
        except (AssertionError, ValueError, OSError, StopIteration, TypeError) as e:
            self.decoded = e

    def poll_texture(self):
        if self.decoded is None:
            return self.after(100, self.poll_texture)
        self.cv.delete("loading")
        if isinstance(self.decoded, Exception):
            return self.status.set(f"Texture preview not available: {self.decoded}")
        w, h, rgb, dim = self.decoded
        self.rgb, self.rgb_masked = (w, h, rgb), ((w, h, dim) if dim else None)
        self.show_image()

    def show_image(self):
        if not self.rgb:
            return
        src = self.rgb_masked if self.v_mask.get() and self.rgb_masked else self.rgb
        key = (self.zoom, src is self.rgb_masked)
        if key not in self.images:
            base = self.images.get((1, key[1])) or _photo(*src)
            self.images[(1, key[1])] = base
            self.images[key] = base.subsample(2) if self.zoom == 0.5 else base if self.zoom == 1 else base.zoom(self.zoom)
        self.cv.delete("tex")
        self.cv.create_image(0, 0, image=self.images[key], anchor="nw", tags="tex")
        self.cv.tag_lower("tex")

    def set_zoom(self, z):
        # keep the centre of the view in place
        size = BASE * self.zoom
        cx = (self.cv.canvasx(self.cv.winfo_width() / 2)) / size
        cy = (self.cv.canvasy(self.cv.winfo_height() / 2)) / size
        self.zoom = z
        self.v_zoom.set(f"{int(z * 100)}%")
        size = BASE * z
        self.cv.configure(scrollregion=(0, 0, size, size))
        self.show_image()
        self.redraw()
        self.cv.xview_moveto(max(0, cx - self.cv.winfo_width() / 2 / size))
        self.cv.yview_moveto(max(0, cy - self.cv.winfo_height() / 2 / size))

    def wheel(self, e):
        self.cv.yview_scroll(-1 if e.delta > 0 else 1, "units")

    def ctrl_wheel(self, e):
        i = ZOOMS.index(self.zoom) + (1 if e.delta > 0 else -1)
        if 0 <= i < len(ZOOMS):
            self.set_zoom(ZOOMS[i])

    # --- stickers <-> screen
    def to_screen(self, u, v):
        s = BASE * self.zoom
        return u * s, v * s

    def to_uv(self, e):
        s = BASE * self.zoom
        return self.cv.canvasx(e.x) / s, self.cv.canvasy(e.y) / s

    def handles(self, s):
        # resize handle at the far corner; rotate handle out of the middle of the far side
        p = [self.to_screen(*c) for c in s.corners()]
        a = math.radians(s.rotation)
        mid = ((p[1][0] + p[2][0]) / 2, (p[1][1] + p[2][1]) / 2)
        rot = (mid[0] + 22 * math.cos(a), mid[1] + 22 * math.sin(a))
        return p, p[2], rot, mid

    def redraw(self):
        self.cv.delete("stk")
        for n, s in enumerate(self.stickers):
            p, _, _, _ = self.handles(s)
            colour = type_colour(s.type)
            sel = n == self.sel
            self.cv.create_polygon(*[c for pt in p for c in pt], outline=colour, fill="", width=3 if sel else 1.5,
                                   tags="stk")
            self.cv.create_line(*p[0], *p[1], fill=colour, width=4 if sel else 2.5, tags="stk")  # text baseline side
            cx, cy = sum(x for x, _ in p) / 4, sum(y for _, y in p) / 4
            size = max(6, min(14, int(abs(s.h) * BASE * self.zoom * 0.6)))
            self.cv.create_text(cx, cy, text=s.type, fill=colour, angle=-s.rotation, font=("Segoe UI", size, "bold"),
                                tags="stk")
        if self.sel is not None:
            s = self.stickers[self.sel]
            p, rs, rot, mid = self.handles(s)
            self.cv.create_oval(p[0][0] - 3, p[0][1] - 3, p[0][0] + 3, p[0][1] + 3, fill="#ffffff", outline="", tags="stk")
            self.cv.create_rectangle(rs[0] - HANDLE, rs[1] - HANDLE, rs[0] + HANDLE, rs[1] + HANDLE, fill="#ffffff",
                                     outline="#000", tags="stk")
            self.cv.create_line(*mid, *rot, fill="#ffffff", tags="stk")
            self.cv.create_oval(rot[0] - HANDLE, rot[1] - HANDLE, rot[0] + HANDLE, rot[1] + HANDLE, fill="#ffffff",
                                outline="#000", tags="stk")

    def refresh_list(self):
        self.tree.delete(*self.tree.get_children())
        for n, s in enumerate(self.stickers):
            self.tree.insert("", "end", iid=str(n), values=(s.type, f"{s.x:.4f}", f"{s.y:.4f}", f"{s.rotation:.1f}"))
        if self.sel is not None:
            self.tree.selection_set(str(self.sel))
            self.tree.see(str(self.sel))

    def fill_fields(self):
        if self.sel is None:
            self.v_type.set("")
            for v in self.v.values():
                v.set("")
            return
        s = self.stickers[self.sel]
        self.v_type.set(s.type)
        for name in ("x", "y", "w", "h", "rotation"):
            self.v[name].set(f"{getattr(s, name):.6f}")
        self.v["order"].set(str(s.order))

    def changed(self, list_too=True):
        self.dirty = True
        self.title("* " + self.title().lstrip("* "))
        self.redraw()
        if list_too:
            self.refresh_list()
        self.fill_fields()

    def select(self, n):
        self.sel = n
        self.redraw()
        self.refresh_list()
        self.fill_fields()

    def tree_select(self, _e=None):
        sel = self.tree.selection()
        n = int(sel[0]) if sel else None
        if n != self.sel:
            self.sel = n
            self.redraw()
            self.fill_fields()

    # --- undo
    def snapshot(self):
        return [s.copy() for s in self.stickers]

    def push_undo(self, snap=None):
        self.undo_stack.append(snap if snap is not None else self.snapshot())
        self.redo_stack.clear()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.snapshot())
            self.stickers = self.undo_stack.pop()
            self.sel = None if self.sel is None or self.sel >= len(self.stickers) else self.sel
            self.changed()

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.snapshot())
            self.stickers = self.redo_stack.pop()
            self.sel = None if self.sel is None or self.sel >= len(self.stickers) else self.sel
            self.changed()

    # --- mouse
    def press(self, e):
        self.cv.focus_set()
        u, v = self.to_uv(e)
        x, y = self.cv.canvasx(e.x), self.cv.canvasy(e.y)
        mode = None
        if self.sel is not None:
            _, rs, rot, _ = self.handles(self.stickers[self.sel])
            if math.dist((x, y), rot) <= HANDLE + 3:
                mode = "rotate"
            elif math.dist((x, y), rs) <= HANDLE + 3:
                mode = "resize"
        if not mode:
            hit = next((n for n in reversed(range(len(self.stickers))) if self.stickers[n].contains(u, v)), None)
            if hit is None:
                return self.select(None)
            if hit != self.sel:
                self.select(hit)
            mode = "move"
        s = self.stickers[self.sel]
        self.drag = {"mode": mode, "u": u, "v": v, "orig": s.copy(), "snap": self.snapshot(), "moved": False}

    def motion(self, e):
        d = self.drag
        if not d:
            return
        u, v = self.to_uv(e)
        s, o = self.stickers[self.sel], d["orig"]
        # values rounded to the 6 decimals LIVERIES.LUA keeps
        if d["mode"] == "move":
            s.x, s.y = round(o.x + u - d["u"], 6), round(o.y + v - d["v"], 6)
        elif d["mode"] == "resize":
            lx, ly = o.to_local(u, v)
            s.w, s.h = round(max(0.001, lx), 6), round(max(0.001, ly), 6)
        else:
            a0 = math.degrees(math.atan2(d["v"] - o.y, d["u"] - o.x))
            a1 = math.degrees(math.atan2(v - o.y, u - o.x))
            delta = (a1 - a0 + 180) % 360 - 180
            rot = o.rotation + delta
            if e.state & 0x1:  # Shift: 15° steps
                rot = round(rot / 15) * 15
            s.rotation = round(rot, 6)
        d["moved"] = True
        self.changed(list_too=False)

    def release(self, _e):
        d, self.drag = self.drag, None
        if d and d["moved"]:
            self.push_undo(d["snap"])
            self.refresh_list()

    # --- keys and buttons
    @staticmethod
    def typing(e):
        return isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Combobox))

    def nudge(self, e, dx, dy):
        if self.typing(e) or self.sel is None:
            return
        self.push_undo()
        s = self.stickers[self.sel]
        s.x = round(s.x + dx * NUDGE, 6)
        s.y = round(s.y + dy * NUDGE, 6)
        self.changed()
        return "break"

    def apply_fields(self):
        if self.sel is None:
            return
        s = self.stickers[self.sel]
        try:
            new = liveries.Sticker(self.v_type.get(), float(self.v["x"].get()), float(self.v["y"].get()),
                                   float(self.v["w"].get()), float(self.v["h"].get()),
                                   float(self.v["rotation"].get()), int(float(self.v["order"].get())))
        except ValueError:
            self.status.set("Not a number: the sticker was not changed.")
            return self.fill_fields()
        if new != s:
            self.push_undo()
            self.stickers[self.sel] = new
            self.changed()

    def view_centre(self):
        s = BASE * self.zoom
        return (self.cv.canvasx(self.cv.winfo_width() / 2) / s, self.cv.canvasy(self.cv.winfo_height() / 2) / s)

    def add(self):
        self.push_undo()
        u, v = self.view_centre()
        self.stickers.append(liveries.Sticker("DriverName", round(u, 6), round(v, 6), 0.1, 0.014, 0.0, 0))
        self.sel = len(self.stickers) - 1
        self.changed()

    def duplicate(self):
        if self.sel is None:
            return
        self.push_undo()
        s = self.stickers[self.sel].copy()
        s.x += 0.01
        s.y += 0.01
        self.stickers.append(s)
        self.sel = len(self.stickers) - 1
        self.changed()

    def delete(self):
        if self.sel is None:
            return
        self.push_undo()
        del self.stickers[self.sel]
        self.sel = None
        self.changed()

    def copy_from(self):
        dlg = tk.Toplevel(self)
        dlg.title("Copy stickers from entry")
        dlg.transient(self)
        ttk.Label(dlg, text="Replace the stickers with those of this LIVERIES.LUA entry (type to search):",
                  padding=8).pack(anchor="w")
        var = tk.StringVar()
        cb = ttk.Combobox(dlg, textvariable=var, values=sorted(self.lf.keys()), width=50)
        cb.pack(padx=8, fill="x")

        def filt(_e=None):
            text = var.get().upper()
            cb["values"] = [k for k in sorted(self.lf.keys()) if text in k]
        cb.bind("<KeyRelease>", filt)

        def ok():
            key = var.get().strip().upper()
            if key not in self.lf.entries:
                return messagebox.showwarning("Stickers", f"No entry named {key}.", parent=dlg)
            self.push_undo()
            self.stickers = self.lf.stickers(key)
            self.sel = None
            self.changed()
            self.status.set(f"Copied {len(self.stickers)} stickers from {key} (not saved yet).")
            dlg.destroy()
        ttk.Button(dlg, text="Copy", command=ok).pack(pady=8)
        cb.focus_set()

    def reload(self):
        if self.dirty and not messagebox.askyesno("Stickers", "Discard the changes not saved?", parent=self):
            return
        self.lf.reload()
        self.load_key(self.key)

    def original(self):
        orig = self.lf.original_stickers(self.key)
        if orig is None:
            return messagebox.showinfo("Stickers", "No original kept for this entry: LIVERIES.LUA has not been saved "
                                       "from here yet (or the entry was not in it).", parent=self)
        self.push_undo()
        self.stickers, self.sel = orig, None
        self.changed()
        self.status.set("Original stickers loaded (not saved yet).")

    def load_key(self, key):
        self.key = key
        self.stickers, self.sel = self.lf.stickers(key), None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.dirty = False
        self.title(self.title().lstrip("* "))
        same = all(self.lf.stickers(k) == self.stickers for k in self.keys)
        self.v_all.set(len(self.keys) > 1 and same)
        self.redraw()
        self.refresh_list()
        self.fill_fields()
        note = "" if same else "  The entries of this livery have different stickers: only this one will be saved."
        self.status.set(f"{key}: {len(self.stickers)} stickers.{note}")

    def change_key(self, _e=None):
        new = self.v_key.get()
        if new == self.key:
            return
        if self.dirty and not messagebox.askyesno("Stickers", "Discard the changes not saved?", parent=self):
            return self.v_key.set(self.key)
        self.load_key(new)

    def save(self):
        keys = self.keys if self.v_all.get() else [self.key]
        try:
            fresh = liveries.LiveriesFile(self.root_dir)  # the file may have changed since it was opened
            missing = [k for k in keys if k not in fresh.entries]
            if missing:
                raise ValueError("entries no longer in LIVERIES.LUA: " + ", ".join(missing))
            for k in keys:
                fresh.set_stickers(k, self.stickers)
            fresh.save()
        except (ValueError, OSError) as e:
            return messagebox.showerror("Stickers", f"Not saved: {e}", parent=self)
        self.lf = fresh
        self.dirty = False
        self.title(self.title().lstrip("* "))
        self.status.set(f"Saved {len(self.stickers)} stickers to {', '.join(keys)}. Restart the game to see them.")

    def close(self):
        if self.dirty:
            answer = messagebox.askyesnocancel("Stickers", "Save the changes to LIVERIES.LUA?", parent=self)
            if answer is None:
                return
            if answer:
                self.save()
                if self.dirty:
                    return
        self.destroy()
