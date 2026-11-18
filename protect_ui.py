"""S6: the password for one protected save. Asked twice, shown only while "Show" is on, used for that save and
never kept (not in the keychain, the settings, the activity log or any file)."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Optional

import keychain
import protect
import ui
from ui import AMBER, CARD, GREEN, INK, MUTED, RED, RoundButton, font


class SavePasswordDialog(tk.Toplevel):
    """Result: self.result = the password (str), or None if cancelled."""

    def __init__(self, parent, what: str):
        super().__init__(parent, bg=CARD)
        ui._attach_app_menu(self)
        self.result: Optional[str] = None
        self.title(f"Protect with a password — {what}")
        self.resizable(False, False)
        self.transient(parent)
        body = tk.Frame(self, bg=CARD)
        body.pack(fill="both", expand=True, padx=28, pady=22)
        tk.Label(body, text="🔒", bg=CARD, font=font(28)).pack()
        tk.Label(body, text="Protect with a password", bg=CARD, fg=INK, font=font(17, "bold")).pack(pady=(2, 4))
        tk.Label(body, text=f"Saving {what}. Documents are saved as PDFs that ask for this password; anything else "
                            "goes into one encrypted ZIP.", bg=CARD, fg=MUTED, font=font(12), wraplength=420,
                 justify="center").pack()
        self.vars, self.entries = [], []
        for lab in ("Password", "Type it again"):
            tk.Label(body, text=lab, bg=CARD, fg=INK, font=font(12), anchor="w").pack(fill="x", pady=(12, 2))
            row = tk.Frame(body, bg=CARD)
            row.pack(fill="x")
            var = tk.StringVar()
            ent = ttk.Entry(row, textvariable=var, show="•", font=font(14), width=30)
            ent.pack(side="left", fill="x", expand=True, ipady=4)
            eye = tk.Label(row, text="Show", bg=CARD, fg=GREEN, font=font(11), cursor="hand2")
            eye.pack(side="left", padx=(8, 0))
            eye.bind("<Button-1>", lambda e, en=ent, ey=eye: self._toggle(en, ey))
            self.vars.append(var)
            self.entries.append(ent)
        self.hint = tk.Label(body, text="", bg=CARD, fg=MUTED, font=font(11), anchor="w", wraplength=420,
                             justify="left")
        self.hint.pack(fill="x", pady=(4, 0))
        self.vars[0].trace_add("write", lambda *_: self._strength())
        tk.Label(body, text="PhoneKeep doesn't keep this password. If you forget it, the saved files can't be "
                            "opened.\nAn encrypted ZIP opens with Keka or The Unarchiver on a Mac, 7-Zip on Windows. "
                            "The names of the files inside it can be seen without the password.",
                 bg=CARD, fg=MUTED, font=font(11), justify="left", anchor="w", wraplength=420).pack(fill="x",
                                                                                                 pady=(10, 0))
        btns = tk.Frame(body, bg=CARD)
        btns.pack(fill="x", pady=(18, 0))
        self.ok_btn = RoundButton(btns, "Choose where to save…", self._ok, "primary", 250, 40, bg=CARD)
        self.ok_btn.pack(side="right")
        RoundButton(btns, "Cancel", self._cancel, "secondary", 100, 40, bg=CARD).pack(side="right", padx=8)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._cancel())
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.entries[0].focus_set()

    def _toggle(self, ent, eye):
        showing = ent.cget("show") == ""
        ent.configure(show="•" if showing else "")
        eye.configure(text="Show" if showing else "Hide")

    def _strength(self):
        score, word = keychain.strength(self.vars[0].get())
        self.hint.configure(text=f"Strength: {word}" if word else "",
                            fg={0: MUTED, 1: RED, 2: AMBER, 3: GREEN, 4: GREEN}[score])

    def _ok(self):
        problem = protect.password_problem(self.vars[0].get(), self.vars[1].get())
        if problem:
            self.hint.configure(text=problem, fg=RED)
            return
        self.result = self.vars[0].get()
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


def ask_save_password(parent, what: str) -> Optional[str]:
    """The dialog, modal; the password or None (one place, so tests can stand in for it)."""
    dlg = SavePasswordDialog(parent, what)
    dlg.grab_set()
    parent.wait_window(dlg)
    return dlg.result
