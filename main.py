import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk, ImageOps

import config
import search as search_mod
from database import ExifDB, VectorDB, build_exif_db, build_vector_db

SETTINGS_FIELDS = [
    ("llm_base_url", "LLM base URL", str),
    ("llm_api_key", "LLM API key", str),
    ("llm_model", "LLM model", str),
    ("llm_temperature", "LLM temperature", float),
    ("embed_base_url", "Embedding base URL", str),
    ("embed_api_key", "Embedding API key", str),
    ("embed_model", "Embedding model", str),
    ("embed_batch_size", "Embedding batch size", int),
    ("embed_workers", "Embedding parallel requests", int),
    ("exif_db_path", "EXIF DB (sqlite) path", str),
    ("vector_db_path", "Vector DB (chroma) folder", str),
    ("chroma_collection", "Chroma collection", str),
    ("extensions", "Extensions (comma separated)", list),
    ("search_candidates", "Vector candidates", int),
    ("search_max_results", "Max results shown", int),
    ("request_timeout", "Request timeout (s)", int),
]


class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Settings")
        self.transient(app)
        self.vars = {}
        cfg = app.cfg
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Photo folders").grid(row=0, column=0, sticky="nw")
        box = ttk.Frame(frm)
        box.grid(row=0, column=1, sticky="ew", pady=2)
        self.folders = tk.Listbox(box, height=4, width=60)
        self.folders.pack(side="left", fill="both", expand=True)
        for f in cfg["photo_folders"]:
            self.folders.insert("end", f)
        btns = ttk.Frame(box)
        btns.pack(side="left", padx=4)
        ttk.Button(btns, text="Add...", command=self.add_folder).pack(fill="x")
        ttk.Button(btns, text="Remove", command=self.remove_folder).pack(fill="x")

        self.recursive = tk.BooleanVar(value=cfg["recursive"])
        ttk.Checkbutton(frm, text="Scan subfolders", variable=self.recursive).grid(row=1, column=1, sticky="w")
        self.rerank = tk.BooleanVar(value=cfg["use_llm_rerank"])
        ttk.Checkbutton(frm, text="LLM selects final results", variable=self.rerank).grid(row=2, column=1, sticky="w")

        for r, (key, label, typ) in enumerate(SETTINGS_FIELDS, start=3):
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky="w", pady=2)
            val = cfg[key]
            v = tk.StringVar(value=", ".join(val) if typ is list else str(val))
            self.vars[key] = (v, typ)
            ttk.Entry(frm, textvariable=v, width=60,
                      show="*" if key.endswith("api_key") else "").grid(row=r, column=1, sticky="ew", pady=2)
        frm.columnconfigure(1, weight=1)
        bar = ttk.Frame(frm)
        bar.grid(row=99, column=0, columnspan=2, sticky="e", pady=8)
        ttk.Button(bar, text="Save", command=self.save).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="left")
        self.grab_set()

    def add_folder(self):
        d = filedialog.askdirectory(parent=self)
        if d:
            self.folders.insert("end", d)

    def remove_folder(self):
        for i in reversed(self.folders.curselection()):
            self.folders.delete(i)

    def save(self):
        new = dict(self.app.cfg)
        try:
            for key, (v, typ) in self.vars.items():
                s = v.get().strip()
                if typ is list:
                    new[key] = ["." + e.strip().lower().lstrip(".") for e in s.split(",") if e.strip()]
                else:
                    new[key] = typ(s)
        except ValueError as e:
            messagebox.showerror("Invalid value", str(e), parent=self)
            return
        new["photo_folders"] = list(self.folders.get(0, "end"))
        new["recursive"] = self.recursive.get()
        new["use_llm_rerank"] = self.rerank.get()
        config.save(new)
        self.app.apply_config(new)
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PhotoSearch")
        self.geometry("1100x700")
        self.q = queue.Queue()
        self.stop_flag = threading.Event()
        self.busy = False
        self.results = []
        self._photo = None
        self.apply_config(config.load())
        self.build_ui()
        self.after(100, self.pump)

    def apply_config(self, cfg):
        self.cfg = cfg
        self.vdb = VectorDB(cfg)
        if hasattr(self, "stats"):
            self.refresh_stats()

    def build_ui(self):
        menu = tk.Menu(self)
        menu.add_command(label="Settings...", command=lambda: SettingsDialog(self))
        self.config(menu=menu)
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        s = ttk.Frame(nb, padding=8)
        nb.add(s, text="Search")
        top = ttk.Frame(s)
        top.pack(fill="x")
        self.query = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.query, font=("Segoe UI", 12))
        e.pack(side="left", fill="x", expand=True)
        e.bind("<Return>", lambda _: self.do_search())
        self.search_btn = ttk.Button(top, text="Search", style="Accent.TButton", command=self.do_search)
        self.search_btn.pack(side="left", padx=4)
        body = ttk.PanedWindow(s, orient="horizontal")
        body.pack(fill="both", expand=True, pady=6)
        left = ttk.Frame(body)
        body.add(left, weight=1)
        self.listbox = tk.Listbox(left, exportselection=False, borderwidth=0, highlightthickness=1, activestyle="none")
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        self.info = tk.Text(left, height=7, width=40, wrap="word", state="disabled")
        self.info.pack(fill="x")
        self.canvas = tk.Label(body, background="#222", foreground="white", anchor="center")
        body.add(self.canvas, weight=3)
        self.canvas.bind("<Configure>", lambda _: self.on_select())
        status_row = ttk.Frame(s)
        status_row.pack(fill="x")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(status_row, textvariable=self.status, foreground="#555").pack(side="left", fill="x", expand=True)
        self.search_progress = ttk.Progressbar(status_row, mode="indeterminate", length=120)
        self.dbbar = tk.StringVar()
        ttk.Label(s, textvariable=self.dbbar, relief="sunken", anchor="w", padding=(6, 3)).pack(fill="x", pady=(4, 0))

        b = ttk.Frame(nb, padding=8)
        nb.add(b, text="Build databases")
        row = ttk.Frame(b)
        row.pack(fill="x")
        self.buttons = [
            ttk.Button(row, text="Build / update EXIF DB", command=self.run_exif),
            ttk.Button(row, text="Build / update vector DB", command=lambda: self.run_vector(False)),
            ttk.Button(row, text="Rebuild vector DB", command=lambda: self.run_vector(True)),
        ]
        for btn in self.buttons:
            btn.pack(side="left", padx=2)
        ttk.Button(row, text="Stop", command=self.stop_flag.set).pack(side="left", padx=2)
        self.bar = ttk.Progressbar(b)
        self.bar.pack(fill="x", pady=6)
        self.stats = tk.StringVar()
        ttk.Label(b, textvariable=self.stats).pack(anchor="w")
        self.log_box = tk.Text(b, state="disabled", wrap="word")
        self.log_box.pack(fill="both", expand=True)
        self.refresh_stats()

    def pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log_box.config(state="normal")
                    self.log_box.insert("end", val + "\n")
                    self.log_box.see("end")
                    self.log_box.config(state="disabled")
                elif kind == "progress":
                    self.bar.config(maximum=max(val[1], 1), value=val[0])
                elif kind == "done":
                    self.busy = False
                    self.search_progress.stop()
                    self.search_progress.pack_forget()
                    self.refresh_stats()
                    self.search_btn.config(state="normal")
                    for b in self.buttons:
                        b.config(state="normal")
                elif kind == "results":
                    self.show_results(val)
                elif kind == "status":
                    self.status.set(val)
        except queue.Empty:
            pass
        self.after(100, self.pump)

    def refresh_stats(self):
        total, desc, emb = ExifDB(self.cfg).count()
        self.stats.set(f"Images: {total or 0}   Described: {desc or 0}   Embedded: {emb or 0}   "
                       f"Vectors in Chroma: {self.vdb.col.count()}")
        edb = ExifDB(self.cfg)
        try:
            tags = edb.tag_count()
        finally:
            edb.con.close()
        self.dbbar.set(
            f"EXIF DB: {config.resolve(self.cfg['exif_db_path']).name}  |  Photos: {total or 0}  |  "
            f"Described: {desc or 0}  |  Distinct tags: {tags}  ||  "
            f"Vector DB: {self.cfg['chroma_collection']}  |  Vectors: {self.vdb.col.count()}  |  "
            f"Embedded: {emb or 0}  |  Folders: {len(self.cfg['photo_folders'])}")

    def start(self, fn):
        if self.busy:
            return
        self.busy = True
        self.stop_flag.clear()
        self.search_btn.config(state="disabled")
        for b in self.buttons:
            b.config(state="disabled")

        def wrapper():
            try:
                fn()
            except Exception as e:
                self.q.put(("log", f"[error] {e}"))
                self.q.put(("status", f"Error: {e}"))
            finally:
                self.q.put(("done", None))
        threading.Thread(target=wrapper, daemon=True).start()

    def _cbs(self):
        return (lambda m: self.q.put(("log", m)), self.stop_flag.is_set,
                lambda i, n: self.q.put(("progress", (i, n))))

    def run_exif(self):
        if not self.cfg["photo_folders"]:
            messagebox.showinfo("No folders", "Add photo folders in Settings first.")
            return
        cfg = self.cfg
        self.start(lambda: build_exif_db(cfg, ExifDB(cfg), *self._cbs()))

    def run_vector(self, rebuild):
        if rebuild and not messagebox.askyesno("Rebuild", "Delete and re-embed everything?"):
            return
        cfg, vdb = self.cfg, self.vdb
        self.start(lambda: build_vector_db(cfg, ExifDB(cfg), vdb, *self._cbs(), rebuild=rebuild))

    def do_search(self):
        if self.busy:
            return
        text = self.query.get().strip()
        if not text:
            return
        self.clear_results()
        self.status.set("Searching...")
        self.search_progress.pack(side="right")
        self.search_progress.start(12)
        cfg, vdb = self.cfg, self.vdb

        def job():
            res = search_mod.search(cfg, ExifDB(cfg), vdb, text, lambda m: self.q.put(("log", m)))
            self.q.put(("results", res))
        self.start(job)

    def clear_results(self):
        self.results = []
        self.listbox.delete(0, "end")
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.config(state="disabled")
        self._photo = None
        self.canvas.config(image="", text="")

    def show_results(self, res):
        self.clear_results()
        self.results = res
        for r in res:
            self.listbox.insert("end", r["name"])
        self.status.set(f"{len(res)} result(s)" if res else "No matching photos found")
        if res:
            self.listbox.selection_set(0)
            self.on_select()

    def on_select(self, _=None):
        sel = self.listbox.curselection()
        if not sel or not self.results:
            return
        r = self.results[sel[0]]
        self.info.config(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("end", f"{r['name']}\n{r['path']}\n\n{r['description']}")
        self.info.config(state="disabled")
        w, h = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        try:
            with Image.open(r["path"]) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((w, h))
                self._photo = ImageTk.PhotoImage(img)
            self.canvas.config(image=self._photo, text="")
        except Exception as e:
            self._photo = None
            self.canvas.config(image="", text=f"Cannot display image: {e}")


if __name__ == "__main__":
    App().mainloop()
