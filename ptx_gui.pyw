# Simple GUI for the PTX <-> DDS converter (uses ptx_dds.py from the same folder).
# Start it by double-clicking ptx_converter.bat (or this file, if .pyw is associated with Python).

import string
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).parent))
import ptx_dds  # noqa: E402

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
        self.resizable(True, False)
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
        self.buttons = (self.b1, self.b2, self.b3, self.b4)

        self.status = tk.StringVar(value="Ready." if textures else "Ready (game folder not found: browse to it manually).")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w", padding=4).pack(fill="x", padx=8, pady=(0, 8))

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
    def run(self, job, done_msg):
        for b in self.buttons:
            b.state(["disabled"])
        self.status.set("Converting...")

        def work():
            try:
                info = job()
                self.after(0, lambda: self.finish(True, f"{done_msg} ({info})"))
            except (AssertionError, ValueError, OSError) as e:
                self.after(0, lambda e=e: self.finish(False, str(e) or type(e).__name__))

        threading.Thread(target=work, daemon=True).start()

    def finish(self, ok, msg):
        for b in self.buttons:
            b.state(["!disabled"])
        self.status.set(("Done: " if ok else "Error: ") + msg)
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
