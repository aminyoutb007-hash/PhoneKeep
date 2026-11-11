"""E1. First-run guide (docs/spec/05-ease-of-use.md), shown in the main window on first launch.

Five steps, one at a time, each with a picture. Every step that can detect its own completion does so:
the phone connecting, the Trust tap, the backup finishing. "Skip" is always there, never highlighted.

Target (00-user-experience.md, J1): 3 clicks and 1 password to a first backup, no other questions.
Here it is 2 clicks + the password: "Turn on encryption" (which is also the confirmation for writing
the password to the phone) and "Back up now".
"""
from __future__ import annotations

import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

import keychain
import phone_write
import phonekeep as wv
import ui
from ui import BG, CARD, GREEN, GREEN_SOFT, INK, LINE, MUTED, RED, font

NO_PHONE_SECONDS = 20
STEPS = ["Connect", "Trust", "Password", "Back up", "Done"]


class Picture(tk.Canvas):
    """Small vector pictures for the steps (drawn, so they look right at any scale and in both modes)."""

    def __init__(self, parent, which: str, bg=CARD):
        super().__init__(parent, width=300, height=190, bg=bg, highlightthickness=0)
        getattr(self, "_" + which)()

    def _phone(self, x=110, y=20, w=80, h=150, screen="#1f6f5f"):
        r = 14
        self.create_rectangle(x, y + r, x + w, y + h - r, fill="#111b21", outline="")
        self.create_rectangle(x + r, y, x + w - r, y + h, fill="#111b21", outline="")
        for cx, cy in ((x, y), (x + w - 2 * r, y), (x, y + h - 2 * r), (x + w - 2 * r, y + h - 2 * r)):
            self.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill="#111b21", outline="")
        self.create_rectangle(x + 6, y + 10, x + w - 6, y + h - 10, fill=screen, outline="")
        self.create_oval(x + w // 2 - 12, y + 12, x + w // 2 + 12, y + 20, fill="#111b21", outline="")
        return x, y, w, h

    def _connect(self):
        x, y, w, h = self._phone()
        # cable from the phone's bottom to the right edge
        self.create_line(x + w // 2, y + h, x + w // 2, y + h + 8, 230, y + h + 8, 230, 100, 300, 100,
                         width=5, fill="#8a949a", smooth=True)
        self.create_rectangle(x + w // 2 - 7, y + h - 2, x + w // 2 + 7, y + h + 8, fill="#c9cfd3", outline="")
        self.create_text(x + w // 2, y + h // 2 + 6, text="📱", font=font(30))

    def _trust(self):
        x, y, w, h = self._phone(screen="#cfe3dd")
        # the Trust prompt
        bx, by, bw, bh = x + 10, y + 46, w - 20, 70
        self.create_rectangle(bx, by, bx + bw, by + bh, fill="#ffffff", outline=LINE)
        self.create_text(bx + bw // 2, by + 14, text="Trust This\nComputer?", font=font(7, "bold"), fill=INK, justify="center")
        self.create_line(bx, by + 40, bx + bw, by + 40, fill=LINE)
        self.create_line(bx + bw // 2, by + 40, bx + bw // 2, by + bh, fill=LINE)
        self.create_text(bx + bw // 4, by + 55, text="Trust", font=font(8, "bold"), fill="#0a84ff")
        self.create_text(bx + 3 * bw // 4, by + 55, text="Don't", font=font(8), fill="#0a84ff")
        self.create_oval(bx + bw // 4 - 12, by + 43, bx + bw // 4 + 12, by + 67, outline=GREEN, width=2)

    def _password(self):
        self.create_text(150, 70, text="🔒", font=font(54))
        self.create_text(150, 135, text="Encrypted · on this computer", font=font(12, "bold"), fill=GREEN)

    def _backup(self):
        x, y, w, h = self._phone(x=40, y=30, w=60, h=120)
        self.create_text(x + w // 2, y + h // 2, text="📱", font=font(22))
        self.create_line(110, 90, 185, 90, width=4, fill=GREEN, arrow="last", arrowshape=(14, 16, 6))
        self.create_rectangle(195, 50, 290, 130, fill="#e8ecef", outline=LINE)
        self.create_rectangle(203, 58, 282, 112, fill="#ffffff", outline=LINE)
        self.create_rectangle(225, 130, 260, 140, fill="#c9cfd3", outline="")
        self.create_text(242, 86, text="🔒", font=font(18))

    def _done(self):
        self.create_oval(100, 30, 200, 130, fill=GREEN_SOFT, outline="")
        self.create_text(150, 80, text="✅", font=font(44))
        self.create_text(150, 160, text="Your iPhone is safely backed up", font=font(12, "bold"), fill=INK)


class FirstRunGuide(tk.Frame):
    def __init__(self, app):
        super().__init__(app.body, bg=BG)
        self.app = app
        self.step = 0
        self.started = time.time()
        self.pending_password: Optional[str] = None
        self.backup_done = False
        self.finished = False
        self._build()
        self.show_step(0)
        self.after(1000, self._watch)

    # layout ----------------------------------------------------------------------------------
    def _build(self):
        self.card = ui.card(self)
        self.card.pack(fill="both", expand=True)
        top = tk.Frame(self.card, bg=CARD)
        top.pack(fill="x", padx=22, pady=(16, 0))
        self.dots = []
        for i, name in enumerate(STEPS):
            d = tk.Label(top, text=f"{i + 1}  {name}", bg=CARD, fg=MUTED, font=font(11))
            d.pack(side="left", padx=(0, 14))
            self.dots.append(d)
        self.skip = tk.Label(top, text="Skip", bg=CARD, fg=MUTED, font=font(11), cursor="hand2")
        self.skip.pack(side="right")
        self.skip.bind("<Button-1>", lambda e: self.do_skip())
        self.inner = tk.Frame(self.card, bg=CARD)
        self.inner.pack(fill="both", expand=True, padx=22, pady=14)

    def _clear(self):
        for w in self.inner.winfo_children():
            w.destroy()

    def show_step(self, n: int):
        self.step = n
        for i, d in enumerate(self.dots):
            d.configure(fg=GREEN if i == n else (INK if i < n else MUTED), font=font(11, "bold" if i == n else "normal"))
        self._clear()
        [self._s_connect, self._s_trust, self._s_password, self._s_backup, self._s_done][n]()

    def _title(self, text: str, sub: str = ""):
        tk.Label(self.inner, text=text, bg=CARD, fg=INK, font=font(20, "bold"), anchor="w").pack(fill="x")
        if sub:
            tk.Label(self.inner, text=sub, bg=CARD, fg=MUTED, font=font(13), anchor="w", justify="left",
                     wraplength=560).pack(fill="x", pady=(4, 10))

    def _row(self):
        row = tk.Frame(self.inner, bg=CARD)
        row.pack(fill="both", expand=True, pady=(8, 0))
        return row

    # steps --------------------------------------------------------------------------------------
    def _s_connect(self):
        self._title("Connect your iPhone", "Use a cable for the first backup. Wi-Fi backups can be set up at the end.")
        row = self._row()
        Picture(row, "connect").pack(side="left", padx=(0, 20))
        right = tk.Frame(row, bg=CARD)
        right.pack(side="left", fill="both", expand=True)
        self.status = tk.Label(right, text="Looking for your iPhone…", bg=CARD, fg=MUTED, font=font(13),
                               anchor="w", justify="left", wraplength=360)
        self.status.pack(fill="x", pady=(30, 0))
        self.fixes = tk.Label(right, text="", bg=CARD, fg=INK, font=font(12), anchor="w", justify="left", wraplength=360)
        self.fixes.pack(fill="x", pady=(14, 0))

    def _s_trust(self):
        self._title("Tap Trust on your iPhone",
                    "Unlock your iPhone. It asks \"Trust This Computer?\": tap Trust and enter your passcode.")
        row = self._row()
        Picture(row, "trust").pack(side="left", padx=(0, 20))
        right = tk.Frame(row, bg=CARD)
        right.pack(side="left", fill="both", expand=True)
        self.status = tk.Label(right, text="Waiting for you to tap Trust…", bg=CARD, fg=MUTED, font=font(13),
                               anchor="w", justify="left", wraplength=360)
        self.status.pack(fill="x", pady=(30, 0))
        self.fixes = tk.Label(right, text="", bg=CARD, fg=INK, font=font(12), anchor="w", justify="left", wraplength=360)
        self.fixes.pack(fill="x", pady=(14, 0))

    def _s_password(self):
        already = getattr(self, "phone_encrypts", None)
        self._title("Choose a backup password" if not already else "Enter your backup password",
                    "Your iPhone encrypts every backup with this password, so only you can open them."
                    if not already else "This iPhone already encrypts its backups. PhoneKeep needs the password once.")
        row = self._row()
        Picture(row, "password").pack(side="left", padx=(0, 20))
        right = tk.Frame(row, bg=CARD)
        right.pack(side="left", fill="both", expand=True)
        frow = tk.Frame(right, bg=CARD)
        frow.pack(fill="x", pady=(24, 0))
        self.pw_var = tk.StringVar()
        self.pw_entry = ttk.Entry(frow, textvariable=self.pw_var, show="•", font=font(15), width=24)
        self.pw_entry.pack(side="left", fill="x", expand=True, ipady=5)
        eye = tk.Label(frow, text="Show", bg=CARD, fg=GREEN, font=font(11), cursor="hand2")
        eye.pack(side="left", padx=(8, 0))
        eye.bind("<Button-1>", lambda e: (self.pw_entry.configure(show="" if self.pw_entry.cget("show") else "•"),
                                          eye.configure(text="Hide" if eye.cget("text") == "Show" else "Show")))
        self.hint = tk.Label(right, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w")
        self.hint.pack(fill="x", pady=(4, 0))
        if not already:
            self.pw_var.trace_add("write", lambda *_: self._strength())
        where = "your Keychain" if sys.platform == "darwin" else "Windows Credential Manager"
        note = (f"Saved in {where}. You won't need to type it again.\nIf you forget it, the backup can't be opened."
                if keychain.available() else
                "This computer has no keychain, so PhoneKeep will ask for the password when it needs it.\n"
                "If you forget it, the backup can't be opened.")
        tk.Label(right, text=note, bg=CARD, fg=MUTED, font=font(11), anchor="w", justify="left").pack(fill="x", pady=(10, 0))
        if already:
            lk = tk.Label(right, text="I don't know the password", bg=CARD, fg=GREEN, font=font(11), cursor="hand2", anchor="w")
            lk.pack(fill="x", pady=(8, 0))
            lk.bind("<Button-1>", lambda e: messagebox.showinfo("Forgotten backup password", wv.RESET_PASSWORD_HELP, parent=self))
        verb = "Turn on encryption" if not already else "Continue"
        self.pw_btn = ui.RoundButton(right, verb, self.do_password, "primary", 210, 42, bg=CARD)
        self.pw_btn.pack(anchor="w", pady=(16, 0))
        self.pw_entry.bind("<Return>", lambda e: self.do_password())
        self.pw_entry.focus_set()

    def _s_backup(self):
        self._title("Back up now", "You can close this window; we'll tell you when it's done.")
        row = self._row()
        Picture(row, "backup").pack(side="left", padx=(0, 20))
        right = tk.Frame(row, bg=CARD)
        right.pack(side="left", fill="both", expand=True)
        self.status = tk.Label(right, text="", bg=CARD, fg=MUTED, font=font(13), anchor="w", justify="left", wraplength=360)
        self.status.pack(fill="x", pady=(20, 6))
        self.bar = ttk.Progressbar(right, mode="determinate", maximum=100)
        self.bar.pack(fill="x")
        self.eta = tk.Label(right, text="", bg=CARD, fg=MUTED, font=font(12), anchor="w")
        self.eta.pack(fill="x", pady=(4, 0))
        self.backup_btn = ui.RoundButton(right, "Back up now", self.do_backup, "primary", 190, 42, bg=CARD)
        self.backup_btn.pack(anchor="w", pady=(16, 0))
        self.bar.pack_forget()
        self.eta.pack_forget()

    def _s_done(self):
        self._title("Your iPhone is safely backed up", "")
        row = self._row()
        Picture(row, "done").pack(side="left", padx=(0, 20))
        right = tk.Frame(row, bg=CARD)
        right.pack(side="left", fill="both", expand=True)
        ui.RoundButton(right, "Open iPhone  ›", self.do_open, "primary", 180, 42, bg=CARD).pack(anchor="w", pady=(6, 14))
        self.choices = {}
        q = [("auto_daily", "Back up automatically every day?"),
             ("wifi", "Back up over Wi-Fi from now on?")]
        if sys.platform == "darwin" and not getattr(self.app, "has_touch_id", lambda: False)():
            q.append(("app_lock", "Lock PhoneKeep with your computer password?"))
        for key, text in q:
            fr = tk.Frame(right, bg=CARD)
            fr.pack(fill="x", pady=4)
            tk.Label(fr, text=text, bg=CARD, fg=INK, font=font(13), anchor="w").pack(side="left")
            lab = tk.Label(fr, text="", bg=CARD, fg=GREEN, font=font(12, "bold"))
            lab.pack(side="right", padx=(8, 0))
            ui.RoundButton(fr, "Not now", lambda k=key, l=lab: self.answer(k, False, l), "secondary", 90, 30, 12, bg=CARD).pack(side="right", padx=4)
            ui.RoundButton(fr, "Yes", lambda k=key, l=lab: self.answer(k, True, l), "light", 70, 30, 12, bg=CARD).pack(side="right")
            self.choices[key] = lab
        self.skip.configure(text="Finish")

    # behaviour -------------------------------------------------------------------------------
    def _watch(self):
        """Every second: let steps 1 and 2 detect their own completion."""
        if self.finished or not self.winfo_exists():
            return
        app = self.app
        if self.step == 0:
            if app.device is not None:
                self.show_step(1)
                self.after(100, self._watch)
                return
            err = getattr(app, "detect_error", "") or ""
            if "trust" in err.lower():
                self.show_step(1)
            elif time.time() - self.started > NO_PHONE_SECONDS and hasattr(self, "fixes"):
                win = sys.platform == "win32"
                self.status.configure(text="Still no iPhone found. Three things that usually fix it:")
                self.fixes.configure(text="1.  Try a different cable or USB port.\n"
                                          "2.  Unlock your iPhone and keep it unlocked.\n"
                                          + ("3.  Install the Apple Devices app (from the Microsoft Store) or iTunes."
                                             if win else "3.  Tap Trust if your iPhone asks."))
        elif self.step == 1:
            if app.device is not None:
                self.start_password_step()
            else:
                err = getattr(app, "detect_error", "") or ""
                if hasattr(self, "fixes") and err and "trust" not in err.lower():
                    self.fixes.configure(text=err)
        self.after(1000, self._watch)

    def start_password_step(self):
        """Step 3 needs to know whether the phone already encrypts; asked in the background."""
        self.phone_encrypts = None
        self.show_step(2)
        self.pw_btn.set_enabled(False)
        self.hint.configure(text="Checking your iPhone…")
        udid = self.app.udid

        def work():
            on = wv.backup_will_encrypt(udid)
            self.app.call(lambda: self._password_ready(on))
        threading.Thread(target=work, daemon=True).start()

    def _password_ready(self, on):
        if self.step != 2:
            return
        if on and keychain.get_password(self.app.udid or ""):
            self.show_step(3)          # already encrypted and the password is known: nothing to ask
            return
        if on != getattr(self, "phone_encrypts", None):
            self.phone_encrypts = bool(on)
            self.show_step(2)
        self.hint.configure(text="")
        self.pw_btn.set_enabled(True)

    def _strength(self):
        score, word = keychain.strength(self.pw_var.get())
        self.hint.configure(text=f"Strength: {word}" if word else "", fg={0: MUTED, 1: RED, 2: "#b06000", 3: GREEN, 4: GREEN}[score])

    def do_password(self):
        pw = self.pw_var.get()
        if not pw:
            self.hint.configure(text="Please type a password.", fg=RED)
            return
        if not self.phone_encrypts and keychain.strength(pw)[0] < 1:
            self.hint.configure(text="Use at least 8 characters.", fg=RED)
            return
        self.pw_btn.set_enabled(False)
        self.hint.configure(text="Your iPhone may ask for its passcode…", fg=MUTED)
        udid, name = self.app.udid, (self.app.device or {}).get("DeviceName", "your iPhone")
        already = self.phone_encrypts

        def work():
            try:
                if not already:
                    # the "Turn on encryption" click above is the owner's confirmation (04-security.md, S1)
                    phone_write.turn_on_encryption(udid, name, pw, confirmed=True, log=self.app.log)
                keychain.set_password(udid, pw)
                self.app.call(lambda: self.show_step(3))
            except Exception as e:
                self.app.call(lambda e=e: self._password_failed(e))
        threading.Thread(target=work, daemon=True).start()

    def _password_failed(self, e):
        pr = self.app.problem_of(e)
        self.hint.configure(text=pr.message, fg=RED)
        self.pw_btn.set_enabled(True)

    def do_backup(self):
        self.backup_btn.set_enabled(False)
        self.bar.pack(fill="x")
        self.eta.pack(fill="x", pady=(4, 0))
        self.status.configure(text="Your iPhone is getting the backup ready, keep it unlocked.")
        t0 = [None]
        app = self.app

        def progress(pct):
            self.app.call(lambda: self.bar.configure(value=pct))
            app._progress_backup(pct, t0)

        def status(text):
            self.app.call(lambda: self.status.configure(text=text))

        def work():
            from pathlib import Path
            return wv.make_backup(Path(app.s["backup_dir"]), app.udid, log=app.log, progress=progress, status=status)

        def done(result):
            if result is not None:
                self.backup_done = True
                self.app.s["first_run_done"] = True
                self.show_step(4)
                self.app.detect(silent=True)
            else:
                self.backup_btn.set_enabled(True)
        app._run(work, done)

    def answer(self, key, yes, label):
        label.configure(text=("Turning on…" if key == "wifi" else "Yes") if yes else "Not now")
        if key == "auto_daily":
            self.app.s["auto_backup"] = "daily" if yes else "off"
            if yes and not hasattr(self.app, "scheduler"):      # B2 not in this version yet: say so
                label.configure(text="Yes · starts with the next update")
        elif key == "app_lock":
            self.app.s["app_lock"] = bool(yes)
        elif key == "wifi" and yes:
            name = (self.app.device or {}).get("DeviceName", "your iPhone")
            if not messagebox.askokcancel(f"Turn on Wi-Fi backups for {name}?",
                                          f"{name} will let this computer back it up over Wi-Fi when they're on the same "
                                          "network. You can turn this off on the iPhone in Settings → General → "
                                          "iTunes Wi-Fi Sync or in Finder.", parent=self):
                label.configure(text="")
                return
            self.app.s["wifi_sync"] = True

            def work():
                phone_write.turn_on_wifi_sync(self.app.udid, name, confirmed=True, log=self.app.log)
                return True
            self.app._run(work, lambda r: label.configure(text="Yes" if r else "Not done"))

    def do_open(self):
        self.finish()
        self.app.open_phone()

    def do_skip(self):
        self.finish()

    def finish(self):
        if self.finished:
            return
        self.finished = True
        self.app.s["first_run_done"] = True
        self.app.end_first_run()


def wanted(app) -> bool:
    """Show the guide on first launch only: nothing backed up yet and the guide not finished or skipped."""
    from pathlib import Path
    if app.s["first_run_done"]:
        return False
    root = Path(app.s["backup_dir"])
    try:
        return not any((p / "Manifest.db").exists() for p in root.iterdir() if p.is_dir())
    except OSError:
        return True
