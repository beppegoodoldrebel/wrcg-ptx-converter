# Simple GUI for the PTX <-> DDS converter (uses ptx_dds.py from the same folder).
# Start it by double-clicking ptx_converter.bat (or this file, if .pyw is associated with Python).

import base64
import os
import string
import struct
import sys
import threading
import tkinter as tk
import zlib
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).parent))
import ptx_dds  # noqa: E402
import workspace  # noqa: E402

GAME_DIR = "WRC Generations - The FIA WRC Official Game"
PTX_TYPES = [("Game textures", "*.PTX"), ("All files", "*.*")]
DDS_TYPES = [("DDS textures", "*.dds"), ("All files", "*.*")]


def find_game_textures():
    # Looks for the game's car textures in the usual Steam locations on every drive
    for drive in string.ascii_uppercase:
        for library in (r"SteamLibrary\steamapps\common", r"Program Files (x86)\Steam\steamapps\common",
                        r"Program Files\Steam\steamapps\common", r"Steam\steamapps\common"):
            path = Path(f"{drive}:\\") / library / GAME_DIR / "WIN32" / "GRAPH" / "CARS"
            if path.is_dir():
                return path
    return None


def png_data(w, h, rgb):
    # base64 PNG for tk.PhotoImage
    raw = b"".join(b"\0" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))
    ch = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    png = (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))
    return base64.b64encode(png)


class FileRow:
    # Label + entry field + "Browse..." button
    def __init__(self, parent, row, label, types, save=False, on_change=None, initialdir=None):
        self.var = tk.StringVar()
        self.types, self.save, self.on_change, self.initialdir = types, save, on_change, initialdir
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(parent, textvariable=self.var, width=70).grid(row=row, column=1, sticky="we", padx=6)
        ttk.Button(parent, text="Browse...", command=self.browse).grid(row=row, column=2, padx=6)

    def browse(self):
        start = Path(self.var.get()).parent if self.var.get() else self.initialdir
        kwargs = dict(filetypes=self.types, initialdir=str(start) if start and Path(start).exists() else None)
        if self.save:
            path = filedialog.asksaveasfilename(defaultextension=self.types[0][1][1:], **kwargs)
        else:
            path = filedialog.askopenfilename(**kwargs)
        if path:
            self.var.set(str(Path(path)))
            if self.on_change:
                self.on_change(Path(path))

    def get(self):
        return Path(self.var.get().strip().strip('"')) if self.var.get().strip() else None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PTX ↔ DDS converter – WRC Generations")
        self.resizable(True, True)
        textures = find_game_textures()
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        # --- tab 1: PTX -> DDS
        t1 = ttk.Frame(nb, padding=8)
        nb.add(t1, text="  PTX → DDS (export)  ")
        t1.columnconfigure(1, weight=1)
        self.e_ptx = FileRow(t1, 0, "Game texture (.PTX):", PTX_TYPES, on_change=self.suggest_dds, initialdir=textures)
        self.e_dds = FileRow(t1, 1, "Save as (.dds):", DDS_TYPES, save=True)
        self.b1 = ttk.Button(t1, text="Convert to DDS", command=self.export)
        self.b1.grid(row=2, column=1, pady=8)

        # --- tab 2: DDS -> PTX
        t2 = ttk.Frame(nb, padding=8)
        nb.add(t2, text="  DDS → PTX (import)  ")
        t2.columnconfigure(1, weight=1)
        self.i_dds = FileRow(t2, 0, "Edited texture (.dds):", DDS_TYPES, on_change=self.suggest_ptx)
        self.i_tpl = FileRow(t2, 1, "Original PTX (template):", PTX_TYPES, initialdir=textures)
        self.i_out = FileRow(t2, 2, "Save as (.PTX):", PTX_TYPES, save=True)
        ttk.Label(t2, foreground="#555", text="The DDS must have the same format and size as the original PTX "
                  "(liveries: DXT5/BC3, 4096×4096, with mipmaps).").grid(row=3, column=0, columnspan=3, sticky="w", padx=6)
        self.b2 = ttk.Button(t2, text="Convert to PTX", command=self.import_)
        self.b2.grid(row=4, column=1, pady=8)

        # --- tab 3: livery colour and mask as two files (the BODY_DIFF alpha is a mask, not transparency)
        t3 = ttk.Frame(nb, padding=8)
        nb.add(t3, text="  Colour + mask (liveries)  ")
        t3.columnconfigure(1, weight=1)
        ttk.Label(t3, foreground="#555", text="BODY_DIFF keeps a mask in its alpha channel: editors show it as "
                  "transparency. Split it to paint the colour without alpha.").grid(row=0, column=0, columnspan=3, sticky="w", padx=6)
        ttk.Label(t3, text="Split", font=("", 9, "bold")).grid(row=1, column=0, sticky="w", padx=6, pady=(8, 0))
        self.s_ptx = FileRow(t3, 2, "Game texture (.PTX):", PTX_TYPES, on_change=self.suggest_split, initialdir=textures)
        self.s_col = FileRow(t3, 3, "Save colour as (.dds):", DDS_TYPES, save=True)
        self.s_msk = FileRow(t3, 4, "Save mask as (.dds):", DDS_TYPES, save=True)
        self.b3 = ttk.Button(t3, text="Split", command=self.split)
        self.b3.grid(row=5, column=1, pady=8)
        ttk.Label(t3, text="Combine", font=("", 9, "bold")).grid(row=6, column=0, sticky="w", padx=6, pady=(8, 0))
        self.c_col = FileRow(t3, 7, "Colour (.dds):", DDS_TYPES, on_change=self.suggest_combine)
        self.c_msk = FileRow(t3, 8, "Mask (.dds, optional):", DDS_TYPES)
        self.c_tpl = FileRow(t3, 9, "Original PTX (template):", PTX_TYPES, initialdir=textures)
        self.c_out = FileRow(t3, 10, "Save as (.PTX):", PTX_TYPES, save=True)
        ttk.Label(t3, foreground="#555", text="Colour: BC1/DXT1 (or BC3/DXT5), mask: BC4/ATI1, both 4096×4096 with mipmaps. "
                  "Without a mask the original one is kept.").grid(row=11, column=0, columnspan=3, sticky="w", padx=6)
        self.b4 = ttk.Button(t3, text="Combine to PTX", command=self.combine)
        self.b4.grid(row=12, column=1, pady=8)

        # --- tab 4: livery workspace (all the textures of a livery folder at once)
        t4 = ttk.Frame(nb, padding=8)
        nb.insert(0, t4, text="  Livery workspace  ")
        nb.select(t4)
        t4.columnconfigure(1, weight=1)
        t4.rowconfigure(3, weight=1)
        self.ws = None
        self.textures_dir = textures
        self.w_livery, self.w_work = tk.StringVar(), tk.StringVar()
        ttk.Label(t4, text="Livery folder:").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(t4, textvariable=self.w_livery, width=70, state="readonly").grid(row=0, column=1, sticky="we", padx=6)
        bar = ttk.Frame(t4)
        bar.grid(row=0, column=2, sticky="e")
        ttk.Button(bar, text="Open PTX...", command=self.ws_open_ptx).pack(side="left", padx=2)
        ttk.Button(bar, text="Open folder...", command=self.ws_open_folder).pack(side="left", padx=2)
        ttk.Label(t4, text="Work folder:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(t4, textvariable=self.w_work, width=70, state="readonly").grid(row=1, column=1, sticky="we", padx=6)
        bar = ttk.Frame(t4)
        bar.grid(row=1, column=2, sticky="e")
        ttk.Button(bar, text="Change...", command=self.ws_change_work).pack(side="left", padx=2)
        ttk.Button(bar, text="Show in Explorer", command=self.ws_explore).pack(side="left", padx=2)
        ttk.Label(t4, foreground="#555", text="Select the textures (Ctrl/Shift for several), export them, edit the DDS "
                  "in the work folder, then save: only the modified ones are converted back to PTX. "
                  "The first save keeps the original PTX in the work folder (ORIGINALI).", wraplength=1000).grid(
            row=2, column=0, columnspan=3, sticky="w", padx=6, pady=(4, 6))
        body = ttk.Frame(t4)
        body.grid(row=3, column=0, columnspan=3, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)
        cols = ("part", "format", "status", "dds")
        self.tree = ttk.Treeview(body, columns=cols, height=14, selectmode="extended")
        for col, text, width in (("#0", "Texture", 200), ("part", "Part", 70), ("format", "Format", 230),
                                 ("status", "Status", 100), ("dds", "DDS file", 220)):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, stretch=col in ("#0", "dds"))
        self.tree.tag_configure("modified", foreground="#b05000")
        self.tree.tag_configure("saved", foreground="#2a7a2a")
        self.tree.tag_configure("locked", foreground="#999")
        self.tree.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<<TreeviewSelect>>", self.ws_preview)
        self.preview = ttk.Label(body, text="(preview)", anchor="center", width=24)
        self.preview.grid(row=0, column=2, sticky="n", padx=8)
        self.preview_img = None
        bar = ttk.Frame(t4)
        bar.grid(row=4, column=0, columnspan=3, pady=8)
        self.b5 = ttk.Button(bar, text="Export selected to DDS", command=self.ws_export)
        self.b6 = ttk.Button(bar, text="Save modified to PTX", command=self.ws_save)
        self.b7 = ttk.Button(bar, text="Refresh", command=self.ws_refresh)
        self.b8 = ttk.Button(bar, text="Restore originals", command=self.ws_restore)
        for b in (self.b5, self.b6, self.b7, self.b8):
            b.pack(side="left", padx=4)
        self.buttons = (self.b1, self.b2, self.b3, self.b4, self.b5, self.b6, self.b7, self.b8)

        self.status = tk.StringVar(value="Ready." if textures else "Ready (game folder not found: browse to it manually).")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w", padding=4).pack(fill="x", padx=8, pady=(0, 8))

    # --- livery workspace
    def ws_load(self, livery, work=None):
        self.ws = workspace.Workspace(livery, work or workspace.default_work_folder(livery))
        self.w_livery.set(str(self.ws.livery))
        self.w_work.set(str(self.ws.work))
        self.ws_refresh()
        self.status.set(f"Opened {self.ws.livery.name}: {len(self.ws.items)} textures.")

    def ws_open_ptx(self):
        start = self.ws.livery if self.ws else self.textures_dir
        path = filedialog.askopenfilename(filetypes=PTX_TYPES, initialdir=str(start) if start else None)
        if path:
            self.ws_load(Path(path).parent)
            name = Path(path).stem.upper()
            pick = [i for i in self.tree.get_children() if i.split("|")[0].upper() == name]
            self.tree.selection_set(pick)
            if pick:
                self.tree.see(pick[0])

    def ws_open_folder(self):
        start = self.ws.livery if self.ws else self.textures_dir
        path = filedialog.askdirectory(initialdir=str(start) if start else None)
        if path:
            self.ws_load(Path(path))

    def ws_change_work(self):
        if not self.ws:
            return messagebox.showwarning("PTX converter", "Open a livery first.")
        path = filedialog.askdirectory(initialdir=str(self.ws.work.parent))
        if path:
            self.ws_load(self.ws.livery, Path(path))

    def ws_explore(self):
        if self.ws:
            self.ws.work.mkdir(parents=True, exist_ok=True)
            os.startfile(self.ws.work)

    def ws_item(self, iid):
        stem, part = iid.split("|")
        return next(i for i in self.ws.items if i.ptx.stem == stem and i.part == part)

    def ws_refresh(self):
        if not self.ws:
            return
        selected = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        for item in self.ws.items:
            st = self.ws.status(item)
            tag = "locked" if not item.editable else st if st in ("modified", "saved") else ""
            self.tree.insert("", "end", iid=f"{item.ptx.stem}|{item.part}", text=item.ptx.stem, tags=(tag,),
                             values=(item.part, item.describe(), st, item.dds_name if item.editable else ""))
        self.tree.selection_set([s for s in selected if self.tree.exists(s)])

    def ws_preview(self, _event=None):
        sel = self.tree.selection()
        if not sel or not self.ws:
            return
        try:
            pv = workspace.preview(self.ws_item(sel[0]))
        except (AssertionError, ValueError, OSError):
            pv = None
        if pv:
            self.preview_img = tk.PhotoImage(data=png_data(*pv))
            self.preview.configure(image=self.preview_img, text="")
        else:
            self.preview_img = None
            self.preview.configure(image="", text="(no preview)")

    def ws_export(self):
        if not self.ws:
            return messagebox.showwarning("PTX converter", "Open a livery first.")
        items = [self.ws_item(i) for i in self.tree.selection()]
        items = [i for i in items if i.editable]
        if not items:
            return messagebox.showwarning("PTX converter", "Select one or more editable textures.")
        exported = [i for i in items if self.ws.status(i) in ("modified", "saved")]
        if exported and not messagebox.askyesno("PTX converter", "These DDS files already exist and will be overwritten "
                                                "with the textures of the PTX:\n\n" + "\n".join(i.dds_name for i in exported)
                                                + "\n\nContinue?"):
            return

        def job():
            done = self.ws.export(items)
            return f"{len(done)} files in {self.ws.work}"

        self.run(job, "exported", after=self.ws_refresh)

    def ws_save(self):
        if not self.ws:
            return messagebox.showwarning("PTX converter", "Open a livery first.")
        modified = [i for i in self.ws.items if self.ws.status(i) == "modified"]
        if not modified:
            return messagebox.showinfo("PTX converter", "No modified DDS: edit and save a DDS in the work folder first.")

        def job():
            saved, errors = self.ws.save()
            msg = f"{len(saved)} PTX saved: " + ", ".join(saved) if saved else "nothing saved"
            if errors:
                raise ValueError(msg + "\n\nNot saved:\n" + "\n".join(f"{k}: {v}" for k, v in errors.items()))
            return msg

        self.run(job, "saved", after=self.ws_refresh)

    def ws_restore(self):
        if not self.ws:
            return messagebox.showwarning("PTX converter", "Open a livery first.")
        backups = sorted(p.name for p in (self.ws.work / workspace.BACKUP).glob("*.PTX"))
        if not backups:
            return messagebox.showinfo("PTX converter", "Nothing to restore: no PTX has been saved from this work folder.")
        if messagebox.askyesno("PTX converter", "Put the original PTX back into the livery folder?\n\n" + "\n".join(backups)):
            self.run(lambda: f"{len(self.ws.restore())} PTX restored", "restored", after=self.ws_refresh)

    # default output names
    def suggest_dds(self, ptx):
        if not self.e_dds.get():
            self.e_dds.var.set(str(Path.home() / "Desktop" / f"{ptx.parent.name}_{ptx.stem}.dds"))

    def suggest_ptx(self, dds):
        if not self.i_out.get():
            self.i_out.var.set(str(dds.with_suffix(".PTX")))

    def suggest_split(self, ptx):
        base = Path.home() / "Desktop" / f"{ptx.parent.name}_{ptx.stem}"
        if not self.s_col.get():
            self.s_col.var.set(f"{base}_COLOUR.dds")
        if not self.s_msk.get():
            self.s_msk.var.set(f"{base}_MASK.dds")

    def suggest_combine(self, colour):
        mask = colour.with_name(colour.name.upper().replace("_COLOUR.DDS", "_MASK.DDS"))
        if not self.c_msk.get() and mask != colour and mask.exists():
            self.c_msk.var.set(str(mask))
        if not self.c_out.get():
            self.c_out.var.set(str(colour.with_name(colour.stem.upper().replace("_COLOUR", "") + ".PTX")))

    # conversions run in a background thread so the window stays responsive
    def run(self, job, done_msg, after=None):
        # after: called in the window thread once the job ends (ok or not), e.g. to refresh the list
        for b in self.buttons:
            b.state(["disabled"])
        self.status.set("Converting...")

        def work():
            try:
                info = job()
                self.after(0, lambda: self.finish(True, f"{done_msg} ({info})", after))
            except (AssertionError, ValueError, OSError) as e:
                self.after(0, lambda e=e: self.finish(False, str(e) or type(e).__name__, after))

        threading.Thread(target=work, daemon=True).start()

    def finish(self, ok, msg, after=None):
        for b in self.buttons:
            b.state(["!disabled"])
        if after:
            after()
        self.status.set(("Done: " if ok else "Error: ") + msg.splitlines()[0])
        (messagebox.showinfo if ok else messagebox.showerror)("PTX converter", msg)

    def export(self):
        src, dst = self.e_ptx.get(), self.e_dds.get()
        if not src or not dst:
            return messagebox.showwarning("PTX converter", "Choose the PTX file and where to save the DDS.")

        def job():
            _, fourcc, w, h, levels = ptx_dds.read_ptx(src.read_bytes())
            dst.write_bytes(ptx_dds.write_dds(fourcc, w, h, levels))
            return ptx_dds.describe(fourcc, w, h, levels)

        self.run(job, f"saved {dst.name}")

    def import_(self):
        dds, tpl, out = self.i_dds.get(), self.i_tpl.get(), self.i_out.get()
        if not dds or not tpl or not out:
            return messagebox.showwarning("PTX converter", "Choose the DDS, the original PTX and where to save.")
        if out.resolve() == tpl.resolve():
            return messagebox.showwarning("PTX converter", "Don't overwrite the original PTX: save with another name or folder.")

        def job():
            data, info = ptx_dds.dds_to_ptx(dds.read_bytes(), tpl.read_bytes())
            out.write_bytes(data)
            return info

        self.run(job, f"saved {out.name}")

    def split(self):
        src, col, msk = self.s_ptx.get(), self.s_col.get(), self.s_msk.get()
        if not src or not col or not msk:
            return messagebox.showwarning("PTX converter", "Choose the PTX file and where to save colour and mask.")

        def job():
            colour, mask, info = ptx_dds.split_ptx(src.read_bytes())
            col.write_bytes(colour)
            msk.write_bytes(mask)
            return info

        self.run(job, f"saved {col.name} and {msk.name}")

    def combine(self):
        col, msk, tpl, out = self.c_col.get(), self.c_msk.get(), self.c_tpl.get(), self.c_out.get()
        if not col or not tpl or not out:
            return messagebox.showwarning("PTX converter", "Choose the colour DDS, the original PTX and where to save.")
        if out.resolve() == tpl.resolve():
            return messagebox.showwarning("PTX converter", "Don't overwrite the original PTX: save with another name or folder.")

        def job():
            data, info = ptx_dds.combine_to_ptx(col.read_bytes(), msk.read_bytes() if msk else None, tpl.read_bytes())
            out.write_bytes(data)
            return info

        self.run(job, f"saved {out.name}")


if __name__ == "__main__":
    App().mainloop()
