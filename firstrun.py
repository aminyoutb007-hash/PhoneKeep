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
import theme
import ui
from ui import BG, CARD, GREEN, GREEN_SOFT, INK, LINE, MUTED, RED, font

NO_PHONE_SECONDS = 20
# E1 refresh (5.2, Direction A): four steps on the left; "done" is step 4's other side (docs/spec/14-layouts.md)
STEPS = [("Connect your iPhone", "With a cable, the first time"),
         ("Tap Trust", "On the iPhone, then enter its passcode"),
         ("Choose a backup password", "Keeps everything encrypted"),
         ("Back up now", "Takes 10–30 minutes the first time")]


class Picture(tk.Canvas):
    """Small vector pictures for the steps (drawn, so they look right at any scale and in both modes)."""

    def __init__(self, parent, which: str, bg=CARD):
        super().__init__(parent, width=300, height=190, bg=bg, highlightthickness=0)
        getattr(self, "_" + which)()

    def _phone(self, x=110, y=20, w=80, h=150, screen=theme.PHONE_SCREEN):
        r = 14
        self.create_rectangle(x, y + r, x + w, y + h - r, fill=theme.DRAW_INK, outline="")
        self.create_rectangle(x + r, y, x + w - r, y + h, fill=theme.DRAW_INK, outline="")
        for cx, cy in ((x, y), (x + w - 2 * r, y), (x, y + h - 2 * r), (x + w - 2 * r, y + h - 2 * r)):
            self.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, fill=theme.DRAW_INK, outline="")
        self.create_rectangle(x + 6, y + 10, x + w - 6, y + h - 10, fill=screen, outline="")
        self.create_oval(x + w // 2 - 12, y + 12, x + w // 2 + 12, y + 20, fill=theme.DRAW_INK, outline="")
        return x, y, w, h

    def _connect(self):
        x, y, w, h = self._phone()
        # cable from the phone's bottom to the right edge
        self.create_line(x + w // 2, y + h, x + w // 2, y + h + 8, 230, y + h + 8, 230, 100, 300, 100,
                         width=5, fill=theme.DRAW_GREY, smooth=True)
        self.create_rectangle(x + w // 2 - 7, y + h - 2, x + w // 2 + 7, y + h + 8, fill=theme.DRAW_LIGHT, outline="")
        # a simple app grid on the screen (no emoji: large emoji glyphs in a Tk canvas can abort Tk on macOS)
        for r in range(4):
            for c in range(3):
                self.create_rounded(x + 14 + c * 20, y + 30 + r * 24, 14, GREEN_SOFT if (r + c) % 2 else theme.WARN_BG)

    def _trust(self):
        x, y, w, h = self._phone(screen=theme.PHONE_SCREEN_SOFT)
        # the Trust prompt
        bx, by, bw, bh = x + 10, y + 46, w - 20, 70
        self.create_rectangle(bx, by, bx + bw, by + bh, fill=theme.CARD, outline=LINE)
        self.create_text(bx + bw // 2, by + 14, text="Trust This\nComputer?", font=font(7, "bold"), fill=INK, justify="center")
        self.create_line(bx, by + 40, bx + bw, by + 40, fill=LINE)
        self.create_line(bx + bw // 2, by + 40, bx + bw // 2, by + bh, fill=LINE)
        self.create_text(bx + bw // 4, by + 55, text="Trust", font=font(8, "bold"), fill=theme.LINK)
        self.create_text(bx + 3 * bw // 4, by + 55, text="Don't", font=font(8), fill=theme.LINK)
        self.create_oval(bx + bw // 4 - 12, by + 43, bx + bw // 4 + 12, by + 67, outline=GREEN, width=2)

    def create_rounded(self, x, y, size, fill):
        self.create_rectangle(x, y, x + size, y + size, fill=fill, outline="")

    def _lock(self, cx, cy, s):
        """A padlock drawn with shapes."""
        self.create_rectangle(cx - s * 0.5, cy - s * 0.05, cx + s * 0.5, cy + s * 0.6, fill=GREEN, outline="")
        self.create_arc(cx - s * 0.35, cy - s * 0.65, cx + s * 0.35, cy + s * 0.15, start=0, extent=180, style="arc", outline=GREEN, width=max(2, int(s * 0.12)))
        self.create_oval(cx - s * 0.08, cy + s * 0.15, cx + s * 0.08, cy + s * 0.31, fill=theme.ON_DARK, outline="")

    def _password(self):
        self._lock(150, 70, 60)
        self.create_text(150, 135, text="Encrypted with your password", font=font(12, "bold"), fill=GREEN)

    def _backup(self):
        x, y, w, h = self._phone(x=40, y=30, w=60, h=120)
        self.create_line(110, 90, 185, 90, width=4, fill=GREEN, arrow="last", arrowshape=(14, 16, 6))
        self.create_rectangle(195, 50, 290, 130, fill=theme.DRAW_PANEL, outline=LINE)
        self.create_rectangle(203, 58, 282, 112, fill=theme.CARD, outline=LINE)
        self.create_rectangle(225, 130, 260, 140, fill=theme.DRAW_LIGHT, outline="")
        self._lock(242, 86, 22)

    def _done(self):
        self.create_oval(100, 30, 200, 130, fill=GREEN_SOFT, outline="")
        self.create_line(125, 82, 143, 100, 178, 62, width=8, fill=GREEN, capstyle="round", joinstyle="round")
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
        self._watch_id = self.after(1000, self._watch)

    # layout ----------------------------------------------------------------------------------
    def _build(self):
        self.card = ui.card(self)
        self.card.pack(fill="both", expand=True)
        left = tk.Frame(self.card, bg=theme.SUBTLE, width=300)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Frame(self.card, bg=theme.BORDER, width=1).pack(side="left", fill="y")
        head = tk.Frame(left, bg=theme.SUBTLE)
        head.pack(fill="x", padx=20, pady=(22, 18))
        tk.Label(head, text="✓", bg=theme.ACCENT, fg=theme.ON_ACCENT, font=font(13, "bold"), width=2).pack(side="left")
        tk.Label(head, text="Welcome to PhoneKeep", bg=theme.SUBTLE, fg=INK, font=font(15, "bold"), anchor="w",
                 justify="left", wraplength=220).pack(side="left", padx=10, fill="x", expand=True)
        self.rows = []
        for i, (title, sub) in enumerate(STEPS):
            row = tk.Frame(left, bg=theme.SUBTLE)
            row.pack(fill="x", padx=12, pady=2)
            dot = tk.Canvas(row, width=28, height=28, bg=theme.SUBTLE, highlightthickness=0)
            dot.pack(side="left", padx=(8, 10), pady=10, anchor="n")
            words = tk.Frame(row, bg=theme.SUBTLE)
            words.pack(side="left", fill="x", expand=True, pady=8)
            t = tk.Label(words, text=title, bg=theme.SUBTLE, fg=INK, font=font(13), anchor="w", justify="left",
                         wraplength=210)
            t.pack(fill="x")
            st = tk.Label(words, text=sub, bg=theme.SUBTLE, fg=MUTED, font=font(11), anchor="w", justify="left",
                          wraplength=210)
            st.pack(fill="x")
            self.rows.append((row, dot, words, t, st))
        tk.Label(left, text="Everything stays on this computer. Nothing is sent online.", bg=theme.SUBTLE, fg=MUTED,
                 font=font(11), anchor="w", justify="left", wraplength=250).pack(side="bottom", fill="x", padx=20, pady=20)
        right = tk.Frame(self.card, bg=CARD)
        right.pack(side="left", fill="both", expand=True, padx=30, pady=(24, 20))
        self.kicker = tk.Label(right, text="", bg=CARD, fg=theme.ACCENT, font=font(13), anchor="w")
        self.kicker.pack(fill="x")
        foot = tk.Frame(right, bg=CARD)
        foot.pack(side="bottom", fill="x", pady=(12, 0))
        self.skip = tk.Label(foot, text="Skip for now", bg=CARD, fg=theme.ACCENT, font=font(13), cursor="hand2")
        self.skip.pack(side="left")
        self.skip.bind("<Button-1>", lambda e: self.do_skip())
        self.buttons = tk.Frame(foot, bg=CARD)
        self.buttons.pack(side="right")
        self.inner = tk.Frame(right, bg=CARD)
        self.inner.pack(fill="both", expand=True)

    def _draw_steps(self, n: int):
        """The list on the left: done (tick), now (accent, pale row), next (grey number)."""
        for i, (row, dot, words, t, st) in enumerate(self.rows):
            now = i == n
            bg = theme.ACCENT_PALE if now else theme.SUBTLE
            for w in (row, dot, words, t, st):
                w.configure(bg=bg)
            t.configure(fg=theme.ACCENT if now else INK if i < n else MUTED, font=font(13, "bold" if now else "normal"))
            dot.delete("all")
            if i < n:
                dot.create_oval(2, 2, 26, 26, fill=theme.ACCENT, outline=theme.ACCENT)
                dot.create_text(14, 14, text="✓", fill=theme.ON_ACCENT, font=font(11, "bold"))
            elif now:
                dot.create_oval(2, 2, 26, 26, outline=theme.ACCENT, width=2)
                dot.create_text(14, 14, text=str(i + 1), fill=theme.ACCENT, font=font(11, "bold"))
            else:
                dot.create_oval(2, 2, 26, 26, fill=theme.TILE_BG, outline=theme.TILE_BG)
                dot.create_text(14, 14, text=str(i + 1), fill=MUTED, font=font(11))

    def _button(self, text, cmd, kind="primary", width=190):
        b = ui.RoundButton(self.buttons, text, cmd, kind, width, 42, bg=CARD)
        b.pack(side="left", padx=(10, 0))
        return b

    def _clear(self):
        var = getattr(self, "pw_var", None)
        if var is not None:                      # drop traces before the entry goes (Tk dislikes the other order)
            for mode, cb in var.trace_info():
                try:
                    var.trace_remove(mode, cb)
                except Exception:
                    pass
            self.pw_var = None
        self.pw2_var = tk.StringVar()                # the confirmation goes with its step
        for w in self.inner.winfo_children() + self.buttons.winfo_children():
            w.destroy()

    def show_step(self, n: int):
        self.step = n
        self._draw_steps(n)
        self.kicker.configure(text=f"Step {n + 1} of {len(STEPS)}" if n < len(STEPS) else "All done")
        self.skip.configure(text="Skip for now" if n < len(STEPS) else "Finish")
        self._clear()
        [self._s_connect, self._s_trust, self._s_password, self._s_backup, self._s_done][n]()

    def _title(self, text: str, sub: str = ""):
        tk.Label(self.inner, text=text, bg=CARD, fg=INK, font=font(24, "bold"), anchor="w").pack(fill="x", pady=(2, 0))
        if sub:
            tk.Label(self.inner, text=sub, bg=CARD, fg=MUTED, font=font(13), anchor="w", justify="left",
                     wraplength=560).pack(fill="x", pady=(4, 10))

    def _row(self):
        row = tk.Frame(self.inner, bg=CARD)
        row.pack(fill="both", expand=True, pady=(8, 0))
        return row

    @staticmethod
    def _wrap(frame):
        """The labels in this column wrap to its width (it changes when the picture goes, or the window is resized)."""
        def fit(e):
            for w in frame.winfo_children() + [g for c in frame.winfo_children() for g in c.winfo_children()]:
                if isinstance(w, tk.Label) and int(w.cget("wraplength") or 0) > 0:
                    w.configure(wraplength=max(160, e.width - 8))
        frame.bind("<Configure>", fit, add="+")

    # steps --------------------------------------------------------------------------------------
    def _s_connect(self):
        self._title("Connect your iPhone", "Use a cable for the first backup. You can choose Wi-Fi backups at the next step.")
        row = self._row()
        Picture(row, "connect").pack(side="left", padx=(0, 20))
        right = tk.Frame(row, bg=CARD)
        right.pack(side="left", fill="both", expand=True)
        self._wrap(right)
        self.status = tk.Label(right, text="Looking for your iPhone…", bg=CARD, fg=MUTED, font=font(13),
                               anchor="w", justify="left", wraplength=360)
        self.status.pack(fill="x", pady=(30, 0))
        self.fixes = tk.Label(right, text="", bg=CARD, fg=INK, font=font(12), anchor="w", justify="left", wraplength=360)
        self.fixes.pack(fill="x", pady=(14, 0))

    def _s_trust(self):
        self.trusted = getattr(self, "trusted", False)
        self._title("Tap Trust on your iPhone",
                    "Unlock your iPhone. It asks \"Trust This Computer?\": tap Trust and enter your passcode.")
        row = self._row()
        self.trust_pic = Picture(row, "trust")
        self.trust_pic.pack(side="left", padx=(0, 20), anchor="n")
        right = tk.Frame(row, bg=CARD)
        right.pack(side="left", fill="both", expand=True)
        self._wrap(right)
        self.status = tk.Label(right, text="Waiting for you to tap Trust…", bg=CARD, fg=MUTED, font=font(13),
                               anchor="w", justify="left", wraplength=360)
        self.status.pack(fill="x", pady=(20, 0))
        self.fixes = tk.Label(right, text="", bg=CARD, fg=INK, font=font(12), anchor="w", justify="left", wraplength=360)
        self.fixes.pack(fill="x", pady=(10, 0))
        # "Use over Wi-Fi" (owner, 15 Nov): offered once the phone trusts this computer; off by default, and only
        # turning it on, then OK on the named confirmation, writes to the phone (through phone_write)
        self.wifi_box = tk.Frame(right, bg=CARD)
        self.wifi_var = tk.BooleanVar(value=self._wifi_on())
        self.wifi_chip = ui.Chip(self.wifi_box, "Turn on Wi-Fi backups", self.wifi_var, self.wifi_switched,
                                 size=13, bg=CARD)
        tk.Label(self.wifi_box, text="Use this iPhone over Wi-Fi from now on?", bg=CARD, fg=INK, font=font(14, "bold"),
                 anchor="w").pack(fill="x", pady=(0, 6))
        self.wifi_chip.pack(anchor="w")
        self.wifi_note = tk.Label(self.wifi_box, text="", bg=CARD, fg=theme.ACCENT, font=font(12, "bold"), anchor="w")
        self.wifi_note.pack(fill="x", pady=(4, 0))
        tk.Label(self.wifi_box, text="Then PhoneKeep can back it up when it's on the same Wi-Fi, without the cable. "
                                     "Only phones that have been plugged in and trusted like this can be seen over "
                                     "Wi-Fi (that's how Apple made it); PhoneKeep never looks for other phones on "
                                     "your network.", bg=CARD, fg=MUTED, font=font(11), anchor="w", justify="left",
                 wraplength=360).pack(fill="x", pady=(4, 0))
        self.continue_btn = self._button("Continue", self.start_password_step)
        if self._wifi_on():
            self.wifi_note.configure(text="Wi-Fi backups are on for this iPhone.")
        self._show_trusted(self.trusted)

    def _show_trusted(self, yes: bool):
        self.trusted = yes
        self.continue_btn.set_enabled(yes and not getattr(self, "_wifi_writing", False))   # not alongside the write
        if yes and self.trust_pic.winfo_manager():          # trusted: the picture has done its job; room for the text
            self.trust_pic.pack_forget()
        elif not yes and not self.trust_pic.winfo_manager():
            self.trust_pic.pack(side="left", padx=(0, 20), anchor="n", before=self.status.master)
        if yes:
            name = (self.app.device or {}).get("DeviceName", "Your iPhone")
            self.status.configure(text=f"✓  {name} trusts this computer.", fg=theme.ACCENT)
            self.fixes.configure(text="")
            if not self.wifi_box.winfo_manager():
                self.wifi_box.pack(fill="x", pady=(16, 0))

    def _wifi_on(self) -> bool:
        """Wi-Fi backups were turned on, from this guide, for the phone that's connected now."""
        return bool(self.app.udid) and getattr(self, "wifi_done_for", None) == self.app.udid

    def wifi_switched(self):
        """The Wi-Fi switch. On asks first, by the phone's name; Cancel turns it back off. Off writes nothing.
        The write goes only to the phone that is connected and trusted when the switch is turned on, and that is
        still the connected phone after OK (reviewer, #75: never to whichever phone the helper finds first)."""
        if self._wifi_on():                             # already written: it stays on (turn it off on the iPhone)
            self.wifi_var.set(True)
            return
        if not self.wifi_var.get():
            self.wifi_note.configure(text="", fg=theme.ACCENT)
            return
        udid = self.app.udid
        if getattr(self, "_wifi_writing", False):       # one write at a time; the switch shows it's on its way
            self.wifi_var.set(True)
            return
        if not udid or not self.trusted or self.app.busy:
            self.wifi_var.set(False)
            self.wifi_note.configure(text="PhoneKeep is busy; try again in a moment." if udid and self.trusted
                                     else "Plug in your iPhone and tap Trust first.", fg=MUTED)
            return
        name = (self.app.device or {}).get("DeviceName", "your iPhone")
        if not messagebox.askokcancel(f"Turn on Wi-Fi backups for {name}?",
                                      f"{name} will let this computer back it up over Wi-Fi when they're on the same "
                                      "network. You can turn this off on the iPhone in Settings → General → "
                                      "iTunes Wi-Fi Sync or in Finder.", parent=self):
            self.wifi_var.set(False)
            return
        if self.app.udid != udid or not self.trusted or self.app.busy:     # the phone changed while asking
            self.wifi_var.set(False)
            self.wifi_note.configure(text="The iPhone changed while asking; nothing was changed.", fg=MUTED)
            return
        self.wifi_note.configure(text="Turning on…", fg=MUTED)
        self._wifi_writing = True
        self.continue_btn.set_enabled(False)          # one conversation with the phone at a time

        def work():
            # a problem shows next to the switch, not as the window's banner: its "Try again" would repeat the
            # write without the switch and the named OK (reviewer, #75)
            try:
                phone_write.turn_on_wifi_sync(udid, name, confirmed=True, log=self.app.log)
                return True
            except Exception as e:
                pr = self.app.problem_of(e)
                self._wifi_problem = pr.message
                self.app.log("ERROR: " + pr.message + (f"  [{pr.details.splitlines()[0]}]" if pr.details else ""))
                return False

        def done(r):
            self._wifi_writing = False
            if r:
                self.wifi_done_for = udid
                self.app.s["wifi_sync"] = True
            try:
                on = self._wifi_on()
                self.wifi_var.set(on)
                self.wifi_note.configure(text="Wi-Fi backups are on for this iPhone." if on else "" if r else
                                         "Not done: " + getattr(self, "_wifi_problem", "the iPhone didn't answer."),
                                         fg=theme.ACCENT if on else RED)
                self.continue_btn.set_enabled(self.trusted)
            except tk.TclError:
                pass
        self.app._run(work, done, quiet=True)

    def _s_password(self):
        already = getattr(self, "phone_encrypts", None)
        self._title("Choose a backup password" if not already else "Enter your backup password",
                    "Encrypted backups keep your passwords, Health data and WhatsApp chats. You'll need this password "
                    "to open them, so pick one you'll remember."
                    if not already else "This iPhone already encrypts its backups. PhoneKeep needs the password once.")
        right = tk.Frame(self.inner, bg=CARD)
        right.pack(fill="both", expand=True, pady=(12, 0))
        tk.Label(right, text="Password", bg=CARD, fg=INK, font=font(13, "bold"), anchor="w").pack(fill="x")
        frow = tk.Frame(right, bg=CARD)
        frow.pack(fill="x", pady=(4, 0))
        self.pw_var = tk.StringVar()
        self.pw_entry = ttk.Entry(frow, textvariable=self.pw_var, show="•", font=font(15))
        self.pw_entry.pack(side="left", fill="x", expand=True, ipady=5)
        eye = tk.Label(frow, text="Show", bg=CARD, fg=GREEN, font=font(11), cursor="hand2")
        eye.pack(side="left", padx=(8, 0))
        self.meter = tk.Canvas(right, height=5, bg=CARD, highlightthickness=0)
        self.hint = tk.Label(right, text="", bg=CARD, fg=MUTED, font=font(12), anchor="w")
        self.pw2_var = tk.StringVar()
        self.pw2_entry = None
        if not already:
            self.meter.pack(fill="x", pady=(8, 0))
            self.meter.bind("<Configure>", lambda e: self._strength())
            self.hint.pack(fill="x", pady=(4, 0))
            self.pw_var.trace_add("write", lambda *_: self._strength())
            tk.Label(right, text="Type it again", bg=CARD, fg=INK, font=font(13, "bold"), anchor="w").pack(fill="x", pady=(12, 0))
            self.pw2_entry = ttk.Entry(right, textvariable=self.pw2_var, show="•", font=font(15))
            self.pw2_entry.pack(fill="x", pady=(4, 0), ipady=5)
            self.pw2_entry.bind("<Return>", lambda e: self.do_password())
        else:
            self.hint.pack(fill="x", pady=(4, 0))
        eye.bind("<Button-1>", lambda e: ([w.configure(show="" if w.cget("show") else "•")
                                            for w in (self.pw_entry, self.pw2_entry) if w is not None],
                                          eye.configure(text="Hide" if eye.cget("text") == "Show" else "Show")))
        where = "your Keychain" if sys.platform == "darwin" else "Windows Credential Manager"
        note = (f"🔒  Saved in {where}, so PhoneKeep can open backups for you. If you forget it, the backup can't be opened."
                if keychain.available() else
                "🔒  This computer has no keychain, so PhoneKeep will ask for the password when it needs it. "
                "If you forget it, the backup can't be opened.")
        tk.Label(right, text=note, bg=theme.ACCENT_PALE, fg=theme.ACCENT, font=font(12), anchor="w", justify="left",
                 wraplength=520, padx=14, pady=10).pack(fill="x", pady=(16, 0))
        if already:
            lk = tk.Label(right, text="I don't know the password", bg=CARD, fg=GREEN, font=font(11), cursor="hand2", anchor="w")
            lk.pack(fill="x", pady=(8, 0))
            lk.bind("<Button-1>", lambda e: messagebox.showinfo("Forgotten backup password", wv.RESET_PASSWORD_HELP, parent=self))
        self.back_btn = self._button("Back", lambda: self.show_step(1), "secondary", 100)
        self.pw_btn = self._button("Turn on encryption" if not already else "Continue", self.do_password, width=210)
        self.pw_entry.bind("<Return>", lambda e: (self.pw2_entry.focus_set() if self.pw2_entry is not None
                                                  else self.do_password()))
        self.pw_entry.focus_set()

    def _s_backup(self):
        self._title("Back up now", "The first backup copies everything, so it takes a while. Keep your iPhone "
                                   "unlocked and nearby, and keep PhoneKeep open until it's done.")
        right = tk.Frame(self.inner, bg=CARD)
        right.pack(fill="both", expand=True)
        self.status = tk.Label(right, text="", bg=CARD, fg=MUTED, font=font(13), anchor="w", justify="left", wraplength=520)
        self.status.pack(fill="x", pady=(20, 6))
        self.bar = ttk.Progressbar(right, mode="determinate", maximum=100)
        self.bar.pack(fill="x")
        self.eta = tk.Label(right, text="", bg=CARD, fg=MUTED, font=font(12), anchor="w")
        self.eta.pack(fill="x", pady=(4, 0))
        self.cancel_btn = ui.RoundButton(self.buttons, "Cancel", self.cancel_backup, "secondary", 110, 42, bg=CARD)
        self.backup_btn = self._button("Back up now", self.do_backup)
        self.bar.pack_forget()
        self.eta.pack_forget()

    def _s_done(self):
        self._title("Your iPhone is safely backed up", "Two last questions; you can change both later in Settings.")
        right = tk.Frame(self.inner, bg=CARD)
        right.pack(fill="both", expand=True, pady=(8, 0))
        self.choices = {}
        # Only questions whose feature exists in this build are shown (agreed 11 Nov): the daily-backup
        # question appears with B2 (the scheduler), the app-lock question with S2. Wi-Fi was asked at Trust.
        q = []
        if self.app.has_feature("scheduler"):
            q.append(("auto_daily", "Back up automatically every day?"))
        if self.app.has_feature("app_lock") and getattr(self.app, "lock_kind", lambda: None)() == "password":   # S2: a Mac without Touch ID
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
        self._button("Open iPhone  ›", self.do_open, width=180)

    # behaviour -------------------------------------------------------------------------------
    def _watch(self):
        """Every second: let steps 1 and 2 detect their own completion."""
        if self.finished or not self.winfo_exists():
            return
        app = self.app
        if self.step == 0:
            if app.device is not None:
                self.show_step(1)
                self._watch_id = self.after(100, self._watch)
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
                if not self.trusted:
                    self._show_trusted(True)
            else:
                if self.trusted:
                    self._show_trusted(False)
                    self.status.configure(text="Waiting for you to tap Trust…", fg=MUTED)
                    self.wifi_box.pack_forget()
                err = getattr(app, "detect_error", "") or ""
                if hasattr(self, "fixes") and err and "trust" not in err.lower():
                    self.fixes.configure(text=err)
        self._watch_id = self.after(1000, self._watch)

    def destroy(self):
        try:
            self.after_cancel(self._watch_id)
        except Exception:
            pass
        super().destroy()

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
        if self.pw_var is None:
            return
        score, word = keychain.strength(self.pw_var.get())
        self.hint.configure(text=word, fg=theme.STRENGTH[score])
        m = self.meter
        m.delete("all")
        w, gap = max(40, m.winfo_width()), 6
        seg = (w - 3 * gap) / 4
        for i in range(4):
            x = i * (seg + gap)
            m.create_rectangle(x, 0, x + seg, 5, outline="",
                               fill=theme.STRENGTH[score] if i < score and self.pw_var.get() else theme.TILE_BG)

    def do_password(self):
        pw = self.pw_var.get()
        if not pw:
            self.hint.configure(text="Please type a password.", fg=RED)
            return
        if not self.phone_encrypts and keychain.strength(pw)[0] < 1:
            self.hint.configure(text="Use at least 8 characters.", fg=RED)
            return
        if not self.phone_encrypts and self.pw2_var.get() != pw:
            self.hint.configure(text="The two passwords aren't the same. Type it again.", fg=RED)
            return
        self.pw_btn.set_enabled(False)
        self.back_btn.set_enabled(False)          # no second write while this one runs (reviewer, #75)
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
        self.back_btn.set_enabled(True)

    def do_backup(self):
        self.backup_btn.set_enabled(False)
        self.bar.pack(fill="x")
        self.eta.pack(fill="x", pady=(4, 0))
        self.status.configure(text="Your iPhone is getting the backup ready, keep it unlocked.")
        self.cancel_btn.configure_text("Cancel")
        self.cancel_btn.set_enabled(True)
        self.cancel_btn.pack(side="left", padx=(10, 0), before=self.backup_btn)
        self._watch_cancel()
        t0 = [None]
        app = self.app

        def progress(pct):
            self.app.call(lambda: self.bar.configure(value=pct))
            app._progress_backup(pct, t0)

        def status(text):
            self.app.call(lambda: self.status.configure(text=text))

        def work():
            from pathlib import Path
            return wv.make_backup(Path(app.s["backup_dir"]), app.udid, log=app.log, progress=progress, status=status,
                                  keep=app.s["snapshots_keep"], until_disk_full=app.s["snapshots_until_full"],
                                  attention=lambda text: app.call(lambda: app.passcode_notice(text)))

        def done(result):
            self.cancel_btn.pack_forget()
            if result is not None:
                self.backup_done = True
                self.app.s["first_run_done"] = True
                self.show_step(4)
                self.app.detect(silent=True)
            else:                                   # refused or failed: the banner says why; reset this step
                self.bar.pack_forget()
                self.eta.pack_forget()
                self.status.configure(text="")
                self.backup_btn.set_enabled(True)
        app._run(work, done)

    def _watch_cancel(self):
        """Cancel is offered only while the phone helper runs; saving the snapshot afterwards can't be cancelled."""
        if not self.winfo_exists() or not self.app.busy:
            return
        if not wv.backup_running() and self.cancel_btn.winfo_manager() and self.cancel_btn.text != "Cancelling…" \
                and self.status.cget("text").startswith("Saving"):
            self.cancel_btn.pack_forget()
            return
        self.after(500, self._watch_cancel)

    def cancel_backup(self):
        if wv.cancel_backup():
            self.cancel_btn.configure_text("Cancelling…")
            self.cancel_btn.set_enabled(False)

    def answer(self, key, yes, label):
        label.configure(text="Yes" if yes else "Not now")
        if key == "auto_daily":
            self.app.s["auto_backup"] = "daily" if yes else "off"
            if yes:
                self.app.set_start_at_login(True)                   # E2: the helper starts at login, and runs the schedule (B2)
                if self.app.udid:                                   # B8: "yes" ticks this phone for automatic backups
                    cur = [u for u in (self.app.s.data.get("auto_backup_phones") or []) if u != self.app.udid]
                    self.app.s["auto_backup_phones"] = cur + [self.app.udid]
        elif key == "app_lock":
            self.app.s["app_lock"] = bool(yes)

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
    import snapshots as _snaps
    root = Path(app.s["backup_dir"])
    try:
        return not any(_snaps.has_backup(root, p.name) for p in root.iterdir() if p.is_dir())
    except OSError:
        return True
