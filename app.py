#!/usr/bin/env python3
"""PhoneKeep desktop window. Run: python app.py"""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import sections as sx
import phonekeep as wv


class ChatPicker(tk.Toplevel):
    """Lists the WhatsApp / WhatsApp Business chats; the person ticks which ones to export."""

    def __init__(self, parent, lists: dict):
        super().__init__(parent)
        self.title("Choose chats to export")
        self.geometry("720x560")
        self.minsize(560, 400)
        self.transient(parent)
        self.result = None
        self.rows = []  # (key, app label, chat)
        for key, (label, chats) in lists.items():
            for c in chats:
                self.rows.append((key, label, c))
        self.selected = {(k, c["id"]) for k, _l, c in self.rows}
        multi = len(lists) > 1

        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(top, text="Tick the chats you want to keep. Click a chat to tick or untick it.").pack(anchor="w")
        row = ttk.Frame(top)
        row.pack(fill="x", pady=(8, 0))
        ttk.Label(row, text="Search:").pack(side="left")
        self.q = tk.StringVar()
        self.q.trace_add("write", lambda *_: self._fill())
        ent = ttk.Entry(row, textvariable=self.q)
        ent.pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(row, text="Select all", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(row, text="Select none", command=lambda: self._set_all(False)).pack(side="left", padx=(6, 0))

        cols = ("tick", "name") + (("app",) if multi else ()) + ("messages", "last")
        frame = ttk.Frame(self)
        frame.pack(fill="both", expand=True, padx=12)
        self.tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="none")
        heads = {"tick": ("", 34), "name": ("Chat", 300), "app": ("App", 140),
                 "messages": ("Messages", 90), "last": ("Last message", 110)}
        for c in cols:
            self.tree.heading(c, text=heads[c][0])
            self.tree.column(c, width=heads[c][1], stretch=(c == "name"),
                             anchor="center" if c in ("tick", "messages") else "w")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<space>", lambda e: self._toggle(self.tree.focus()))

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=12, pady=12)
        self.count = ttk.Label(bottom)
        self.count.pack(side="left")
        ttk.Button(bottom, text="Export selected chats", command=self._ok).pack(side="right")
        ttk.Button(bottom, text="Cancel", command=self.destroy).pack(side="right", padx=8)
        self.multi = multi
        self._fill()
        ent.focus_set()
        self.grab_set()

    def _fill(self):
        q = self.q.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for i, (key, label, c) in enumerate(self.rows):
            if q and q not in c["name"].lower():
                continue
            tick = "☑" if (key, c["id"]) in self.selected else "☐"
            name = ("👥 " if c["group"] else "") + c["name"]
            vals = (tick, name) + ((label,) if self.multi else ()) + (f"{c['messages']:,}", c["last"])
            self.tree.insert("", "end", iid=str(i), values=vals)
        self._update_count()

    def _toggle(self, iid):
        if not iid:
            return
        key, _label, c = self.rows[int(iid)]
        k = (key, c["id"])
        self.selected.symmetric_difference_update({k})
        self.tree.set(iid, "tick", "☑" if k in self.selected else "☐")
        self._update_count()

    def _click(self, event):
        if self.tree.identify_region(event.x, event.y) == "cell":
            self._toggle(self.tree.identify_row(event.y))
            return "break"

    def _set_all(self, on: bool):
        visible = [self.rows[int(i)] for i in self.tree.get_children()]
        for key, _l, c in visible:
            (self.selected.add if on else self.selected.discard)((key, c["id"]))
        self._fill()

    def _update_count(self):
        self.count.configure(text=f"{len(self.selected):,} of {len(self.rows):,} chats selected")

    def _ok(self):
        if not self.selected:
            messagebox.showinfo(wv.APP_NAME, "Tick at least one chat.", parent=self)
            return
        out = {key: set() for key, _l, _c in self.rows}
        for key, cid in self.selected:
            out[key].add(cid)
        self.result = out
        self.destroy()


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{wv.APP_NAME} – iPhone backup & archive")
        self.geometry("820x760")
        self.minsize(680, 640)
        self.q: queue.Queue = queue.Queue()
        self.busy = False
        self.backups: list[dict] = []
        self.backup_dir = tk.StringVar(value=str(wv.DEFAULT_BACKUP_DIR))
        self.archive_dir = tk.StringVar(value=str(wv.DEFAULT_ARCHIVE_DIR))
        self.media = tk.BooleanVar(value=True)
        self.direct_photos = tk.BooleanVar(value=True)
        self.pick_chats = tk.BooleanVar(value=True)
        self.device_text = tk.StringVar(value="Looking for iPhone…")
        self.udid: str | None = None
        self.picks = {k: tk.BooleanVar(value=(k in sx.DEFAULT_SECTIONS)) for k, *_ in sx.SECTIONS}
        self._build()
        self.after(100, self._pump)
        self.after(300, self.detect)
        self.after(400, self.refresh_backups)

    # ---------- layout ----------
    def _build(self):
        pad = {"padx": 12, "pady": 5}
        ttk.Style(self).configure("Big.TButton", padding=(14, 8), font=("", 11, "bold"))

        f1 = ttk.LabelFrame(self, text="1. Connect your iPhone")
        f1.pack(fill="x", **pad)
        ttk.Label(f1, textvariable=self.device_text).pack(side="left", padx=10, pady=8)
        ttk.Button(f1, text="Detect", command=self.detect).pack(side="right", padx=(4, 10))
        ttk.Button(f1, text="🔒 Backup encryption…", command=self.encryption).pack(side="right")

        f2 = ttk.LabelFrame(self, text="2. Choose what to include")
        f2.pack(fill="x", **pad)
        grid = ttk.Frame(f2)
        grid.pack(fill="x", padx=10, pady=6)
        for i, (k, label, *_r) in enumerate(sx.SECTIONS):
            text = label + (" – every file, large" if k == "files" else "")
            ttk.Checkbutton(grid, text=text, variable=self.picks[k]).grid(
                row=i // 3, column=i % 3, sticky="w", padx=(0, 18), pady=1)
        opt = ttk.Frame(f2)
        opt.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Checkbutton(opt, text="Include attachments & media files", variable=self.media).pack(side="left")
        ttk.Checkbutton(opt, text="Copy photos directly from the phone (works with iCloud Photos)",
                        variable=self.direct_photos).pack(side="left", padx=14)
        opt2 = ttk.Frame(f2)
        opt2.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Checkbutton(opt2, text="Let me choose which WhatsApp chats to export",
                        variable=self.pick_chats).pack(side="left")

        f3 = ttk.LabelFrame(self, text="3. Back up & build the archive")
        f3.pack(fill="x", **pad)
        for var, label in ((self.backup_dir, "Backups folder:"), (self.archive_dir, "Archive folder:")):
            row = ttk.Frame(f3)
            row.pack(fill="x", padx=10, pady=3)
            ttk.Label(row, text=label, width=14).pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True, padx=6)
            ttk.Button(row, text="Browse", command=lambda v=var: self._browse(v)).pack(side="left")
        row = ttk.Frame(f3)
        row.pack(fill="x", padx=10, pady=(4, 8))
        ttk.Button(row, text="Back up iPhone & build archive", style="Big.TButton",
                   command=self.backup_and_export).pack(side="left")
        ttk.Button(row, text="Back up only", command=self.backup_only).pack(side="left", padx=8)
        ttk.Button(row, text="Open archive", command=self.open_archive).pack(side="right")

        f4 = ttk.LabelFrame(self, text="…or build the archive from an existing backup")
        f4.pack(fill="x", **pad)
        row = ttk.Frame(f4)
        row.pack(fill="x", padx=10, pady=6)
        self.combo = ttk.Combobox(row, state="readonly")
        self.combo.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="↻", width=3, command=self.refresh_backups).pack(side="left", padx=4)
        ttk.Button(row, text="Other folder…", command=self.pick_backup_folder).pack(side="left")
        ttk.Button(row, text="Build archive", command=self.export_selected).pack(side="left", padx=(8, 0))

        self.bar = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.bar.pack(fill="x", padx=12, pady=(6, 0))
        self.log_box = tk.Text(self, height=10, wrap="word", state="disabled",
                               font=("Menlo" if sys.platform == "darwin" else "Consolas", 10))
        self.log_box.pack(fill="both", expand=True, padx=12, pady=10)

    # ---------- plumbing ----------
    def log(self, msg: str):
        self.q.put(("log", msg))

    def progress(self, pct: float):
        self.q.put(("pct", pct))

    def _pump(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log_box.configure(state="normal")
                    self.log_box.insert("end", val + "\n")
                    self.log_box.see("end")
                    self.log_box.configure(state="disabled")
                elif kind == "pct":
                    self.bar.stop()
                    self.bar.configure(mode="determinate")
                    self.bar["value"] = val
                elif kind == "call":
                    val()
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def _browse(self, var: tk.StringVar):
        d = filedialog.askdirectory(initialdir=var.get() or str(Path.home()))
        if d:
            var.set(d)

    def _run(self, fn, done=None, quiet=False):
        if self.busy:
            if not quiet:
                messagebox.showinfo(wv.APP_NAME, "Already working, please wait.")
            return
        self.busy = True
        self.bar.configure(mode="indeterminate")
        self.bar.start(12)

        def worker():
            result, err = None, None
            try:
                result = fn()
            except wv.PhoneKeepError as e:
                err = str(e)
            except Exception as e:
                err = f"{type(e).__name__}: {e}"
            self.q.put(("call", lambda: self._finish(result, err, done, quiet)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, result, err, done, quiet):
        self.busy = False
        self.bar.stop()
        self.bar.configure(mode="determinate")
        if err:
            self.bar["value"] = 0
            self.log("ERROR: " + err)
            if not quiet:
                messagebox.showerror(wv.APP_NAME, err)
            elif done:
                done(None)
        elif done:
            done(result)

    def _ask(self, prompt: str) -> str | None:
        """Ask for a password on the UI thread; blocks the worker until answered."""
        box, ev = {}, threading.Event()

        def ask():
            box["v"] = simpledialog.askstring(wv.APP_NAME, prompt, show="•", parent=self)
            ev.set()
        self.q.put(("call", ask))
        ev.wait()
        return box.get("v")

    def _choose_chats(self, lists: dict):
        """Show the chat picker on the UI thread; the worker waits for the answer."""
        if not any(chats for _label, chats in lists.values()):
            return {}  # nothing to pick from: export normally and let each section report it
        box, ev = {}, threading.Event()

        def show():
            picker = ChatPicker(self, lists)
            self.wait_window(picker)
            box["v"] = picker.result
            ev.set()
        self.q.put(("call", show))
        ev.wait()
        if box.get("v") is not None:
            n = sum(len(v) for v in box["v"].values())
            self.log(f"You selected {n} chat{'s' if n != 1 else ''} to export.")
        return box.get("v")

    def _selected(self) -> list[str]:
        return [k for k, v in self.picks.items() if v.get()]

    def _export(self, path: Path) -> Path:
        info = wv.backup_info(path)
        pw = None
        if info["encrypted"]:
            pw = self._ask(f"The backup of '{info['name']}' is encrypted.\nEnter the backup password:")
            if not pw:
                raise wv.PhoneKeepError("Cancelled: a password is needed for encrypted backups.")
        chosen = self._selected()
        if not chosen:
            raise wv.PhoneKeepError("Tick at least one thing to include.")
        self.log(f"Building archive from backup of {info['name']} ({info['date']})")
        wants_pick = self.pick_chats.get() and ({"whatsapp", "whatsappbusiness"} & set(chosen))
        return sx.export_all(path, Path(self.archive_dir.get()), pw, chosen,
                             include_media=self.media.get(), log=self.log, progress=self.progress,
                             chooser=self._choose_chats if wants_pick else None)

    # ---------- actions ----------
    def detect(self):
        def done(devs):
            if devs:
                d = devs[0]
                self.udid = d.get("UniqueDeviceID") or d.get("Identifier")
                self.device_text.set(f"✅  {d.get('DeviceName', 'iPhone')} · iOS {d.get('ProductVersion', '?')}"
                                     f" · {d.get('ConnectionType', '')}")
            else:
                self.udid = None
                self.device_text.set("❌  No iPhone found – plug it in, unlock it and tap 'Trust'.")
        self.device_text.set("Looking for iPhone…")
        self._run(wv.list_devices, done, quiet=True)

    def encryption(self):
        on = messagebox.askyesnocancel(
            wv.APP_NAME,
            "Encrypted backups are protected by a password and also include call history, "
            "Safari history, Health data and saved Wi-Fi networks.\n\n"
            "Yes = turn encryption ON (choose a new password)\n"
            "No = turn encryption OFF (needs the current password)")
        if on is None:
            return
        if on:
            pw = simpledialog.askstring(wv.APP_NAME, "New backup password:", show="•", parent=self)
            if not pw:
                return
            if pw != simpledialog.askstring(wv.APP_NAME, "Repeat the password:", show="•", parent=self):
                messagebox.showerror(wv.APP_NAME, "Passwords don't match.")
                return
            messagebox.showinfo(wv.APP_NAME, "Write this password down. If you lose it, encrypted "
                                             "backups can't be opened and Apple can't recover it.")
        else:
            pw = simpledialog.askstring(wv.APP_NAME, "Current backup password:", show="•", parent=self)
            if not pw:
                return
        self.log("Changing backup encryption — the iPhone may ask for its passcode.")
        self._run(lambda: wv.set_backup_encryption(bool(on), pw, self.udid, self.log),
                  lambda _: messagebox.showinfo(wv.APP_NAME, "Done."))

    def refresh_backups(self):
        self.backups = wv.find_backups(self.log)
        labels = [f"{b['name']} – {b['date']}{'  🔒' if b['encrypted'] else ''}" for b in self.backups]
        self.combo["values"] = labels
        if labels:
            self.combo.current(0)
        else:
            self.combo.set("No backups found yet")

    def pick_backup_folder(self):
        d = filedialog.askdirectory(title="Choose an iPhone backup folder (contains Manifest.db)")
        if not d:
            return
        if not (Path(d) / "Manifest.db").exists():
            messagebox.showerror(wv.APP_NAME, "That folder is not an iPhone backup (no Manifest.db).")
            return
        info = wv.backup_info(Path(d))
        self.backups.insert(0, info)
        self.combo["values"] = [f"{info['name']} – {info['date']}"] + list(self.combo["values"])
        self.combo.current(0)

    def backup_only(self):
        self._run(lambda: wv.make_backup(Path(self.backup_dir.get()), log=self.log, progress=self.progress),
                  lambda _: (self.refresh_backups(), messagebox.showinfo(wv.APP_NAME, "Backup complete.")))

    def backup_and_export(self):
        photos = self.direct_photos.get() and self.picks["photos"].get() and self.media.get()

        def work():
            path = wv.make_backup(Path(self.backup_dir.get()), log=self.log, progress=self.progress)
            if photos:
                try:
                    wv.sync_photos(Path(self.archive_dir.get()) / "Photos" / "Originals",
                                   self.udid, self.log, self.progress)
                except wv.PhoneKeepError as e:
                    self.log(f"Direct photo copy skipped: {e}")
            return self._export(path)
        self._run(work, self._exported)

    def export_selected(self):
        i = self.combo.current()
        if i < 0 or i >= len(self.backups):
            messagebox.showinfo(wv.APP_NAME, "No backup selected. Back up your iPhone first.")
            return
        path = Path(self.backups[i]["path"])
        self._run(lambda: self._export(path), self._exported)

    def _exported(self, index: Path):
        self.refresh_backups()
        if messagebox.askyesno(wv.APP_NAME, "Your iPhone archive is ready. Open it now?"):
            webbrowser.open(index.resolve().as_uri())

    def open_archive(self):
        index = Path(self.archive_dir.get()) / "index.html"
        if index.exists():
            webbrowser.open(index.resolve().as_uri())
        else:
            messagebox.showinfo(wv.APP_NAME, "No archive yet. Build one first.")


if __name__ == "__main__":
    App().mainloop()
