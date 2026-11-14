"""H1 in the phone window: the Check-up screen (four cards, the summary line, "Why is my phone slow?") and each
card's details. The verdicts come from checkup.py; this only draws them."""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from typing import Optional

import checkup
import overview_ui
import ui
from overview_ui import BAD, GOOD, WARN
from ui import BG, CARD, INK, LINE, MUTED, RoundButton, font

COLOUR = {checkup.GREEN: GOOD, checkup.AMBER: WARN, checkup.RED: BAD, checkup.UNKNOWN: MUTED}
WORD = {checkup.GREEN: "Good", checkup.AMBER: "Needs attention", checkup.RED: "Act now", checkup.UNKNOWN: "Not checked"}


def phone_dir(win) -> Optional[Path]:
    """The phone's folder of backups, where its check-up record lives (None for a backup opened from elsewhere)."""
    udid = getattr(win, "udid", None)
    return Path(win.backup_dir) / udid if udid else None


def report(win) -> Optional[checkup.Report]:
    return checkup.check(phone_dir(win), getattr(win, "overview", None))


def tile_text(win) -> str:
    """The line under the Check-up icon on the home screen."""
    r = report(win)
    if r is None:
        return "needs a backup"
    n = sum(1 for c in r.cards if c.needs_attention)
    return "all good" if n == 0 else f"{n} to look at"


def view(win):
    t0 = time.perf_counter()
    win.current = "checkup"
    win._clear()
    r = report(win)
    win.view_header("checkup", r.as_of() if r else "")
    win.checkup_report = r
    if r is None:
        tk.Label(win.content, text="The check-up needs this iPhone connected, or one backup made by PhoneKeep.",
                 bg=BG, fg=MUTED, font=font(13), anchor="w").pack(fill="x", pady=(8, 0))
        win.checkup_ms = (time.perf_counter() - t0) * 1000
        return
    top = tk.Frame(win.content, bg=BG)
    top.pack(fill="x", pady=(0, 12))
    win.checkup_summary = tk.Label(top, text=r.summary(), bg=BG, fg=INK, font=font(17, "bold"), anchor="w")
    win.checkup_summary.pack(side="left")
    answer = tk.Label(win.content, text="", bg=BG, fg=INK, font=font(13), anchor="w", justify="left", wraplength=760)
    win.checkup_answer = answer

    def why():
        answer.configure(text=r.why_slow())
        answer.pack(fill="x", pady=(0, 12), before=row)
    RoundButton(top, "Why is my phone slow?", why, "secondary", 210, 34, 12).pack(side="right")

    row = tk.Frame(win.content, bg=BG)
    row.pack(fill="x")
    row.columnconfigure((0, 1, 2, 3), weight=1, uniform="checkup")
    win.checkup_cards = {}
    for i, c in enumerate(r.cards):
        f = tk.Frame(row, bg=CARD, highlightthickness=1, highlightbackground=LINE, cursor="hand2")
        f.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 4, 0 if i == 3 else 4))
        tk.Label(f, text=c.title.upper(), bg=CARD, fg=MUTED, font=font(11, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(10, 2))
        tk.Label(f, text=f"●  {WORD[c.level]}", bg=CARD, fg=COLOUR[c.level], font=font(14, "bold"),
                 anchor="w").pack(fill="x", padx=14)
        tk.Label(f, text=c.reason.split(": ", 1)[-1], bg=CARD, fg=INK, font=font(12), anchor="nw", justify="left",
                 wraplength=170).pack(fill="x", padx=14, pady=(4, 0))
        if not r.facts.live and c.level != checkup.UNKNOWN:
            tk.Label(f, text=r.as_of(), bg=CARD, fg=MUTED, font=font(11), anchor="w").pack(fill="x", padx=14, pady=(4, 0))
        tk.Label(f, text="See details ›", bg=CARD, fg=ui.SELECT_BLUE, font=font(11, "bold"), anchor="w").pack(
            fill="x", padx=14, pady=(6, 12), side="bottom")
        overview_ui._bind_all(f, lambda k=c.key: details(win, k))
        win.checkup_cards[c.key] = f
    tk.Label(win.content, text="Storage and Battery are what the iPhone reports. The Stability and Security checks "
                               "come in later versions of PhoneKeep. Nothing here changes anything on the iPhone.",
             bg=BG, fg=MUTED, font=font(11), anchor="w", justify="left", wraplength=760).pack(fill="x", pady=(12, 0))
    win.checkup_ms = (time.perf_counter() - t0) * 1000


def details(win, key: str):
    r = getattr(win, "checkup_report", None) or report(win)
    if r is None:
        return
    c = r.card(key)
    win.current = f"checkup:{key}"
    win._clear()
    top = tk.Frame(win.content, bg=BG)
    top.pack(fill="x", pady=(0, 10))
    RoundButton(top, "‹  Check-up", lambda: view(win), "secondary", 130, 32, 12).pack(side="left")
    tk.Label(top, text=c.title, bg=BG, fg=INK, font=font(19, "bold")).pack(side="left", padx=12)
    tk.Label(top, text=r.as_of(), bg=BG, fg=MUTED, font=font(12)).pack(side="left")
    box = tk.Frame(win.content, bg=CARD, highlightthickness=1, highlightbackground=LINE)
    box.pack(fill="x")
    tk.Label(box, text=f"●  {WORD[c.level]}", bg=CARD, fg=COLOUR[c.level], font=font(17, "bold"), anchor="w").pack(
        fill="x", padx=18, pady=(16, 6))
    for line in (c.details or [c.reason.split(": ", 1)[-1]]):
        tk.Label(box, text="•  " + line, bg=CARD, fg=INK, font=font(13), anchor="w", justify="left",
                 wraplength=700).pack(fill="x", padx=18, pady=2)
    ov = getattr(win, "overview", None)
    more = {"storage": ("What's using it ›", lambda: overview_ui.storage_view(win, ov)),
            "battery": ("Battery details ›", lambda: overview_ui.battery_view(win, ov))}.get(key)
    if more and ov is not None:
        RoundButton(box, more[0], more[1], "secondary", 190, 34, 12).pack(anchor="w", padx=18, pady=(10, 0))
    tk.Frame(box, bg=CARD, height=14).pack()
