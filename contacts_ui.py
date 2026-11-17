"""D1: Contacts as on the phone (docs/spec/08-personal-data.md#d1-contacts).

A list with each contact's photo (or initials), the phone's Lists in a sidebar (every account, then every group, with
counts), and a contact card where a click on a number, email, address or link copies it. Save as vCard (with photos),
Excel or CSV: the selected contacts, or everything shown. A vCard saved where one of the same name already is asks
"Keep both / Replace / Skip".

Read-only, from the backup on the computer. A contact photo kept only as a link on the internet is never fetched:
nothing leaves the computer.
"""
from __future__ import annotations

import datetime as dt
import io
import re
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import sections as sx
import theme
from ui import BG, CARD, INK, MUTED, RoundButton, card, font

ROW_PX, CARD_PX = 24, 96


def initials(p: dict) -> str:
    words = [w for w in (p.get("first"), p.get("last")) if w] or (p.get("name") or "?").split()
    letters = "".join(w[0] for w in words[:2] if w and w[0].isalnum())
    return (letters or "#").upper()


def avatar(p: dict, size: int):
    """A round picture: the contact's photo, or their initials on the accent's pale colour."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    big = size * 4                                   # drawn large, then made small: smooth edges
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    im = None
    if p.get("photo"):
        try:
            im = ImageOps.fit(Image.open(io.BytesIO(p["photo"])).convert("RGB"), (big, big))
        except Exception:
            im = None
    if im is None:
        im = Image.new("RGB", (big, big), theme.ACCENT_PALE)
        text = initials(p)
        try:
            f = ImageFont.load_default(size=int(big * (0.42 if len(text) < 2 else 0.36)))
        except TypeError:                            # Pillow without FreeType: the small built-in font
            f = ImageFont.load_default()
        d = ImageDraw.Draw(im)
        x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
        d.text(((big - (x1 - x0)) / 2 - x0, (big - (y1 - y0)) / 2 - y0), text, fill=theme.ACCENT, font=f)
    im.putalpha(mask)
    return im.resize((size, size), Image.LANCZOS)


class ConflictDialog(tk.Toplevel):
    """'name' is already in the folder: Keep both, Replace or Skip."""

    def __init__(self, parent, name: str):
        super().__init__(parent, bg=BG)
        self.title("Save as vCard")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        tk.Label(self, text=f"“{name}” is already in this folder.", bg=BG, fg=INK, font=font(14, "bold"),
                 wraplength=420, justify="left").pack(anchor="w", padx=20, pady=(18, 4))
        tk.Label(self, text="Keep both saves this one with a number after its name.", bg=BG, fg=MUTED, font=font(12),
                 wraplength=420, justify="left").pack(anchor="w", padx=20)
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=20, pady=16)
        RoundButton(row, "Keep both", lambda: self.pick("both"), "primary", 120, 34, 12).pack(side="right")
        RoundButton(row, "Replace", lambda: self.pick("replace"), "secondary", 100, 34, 12).pack(side="right", padx=6)
        RoundButton(row, "Skip", lambda: self.pick("skip"), "secondary", 80, 34, 12).pack(side="right")
        self.bind("<Escape>", lambda e: self.destroy())

    def pick(self, v):
        self.result = v
        self.destroy()


def ask_conflict(parent, name: str):
    """"both" (keep both), "replace", "skip", or None (closed)."""
    dlg = ConflictDialog(parent, name)
    dlg.grab_set()
    parent.wait_window(dlg)
    return dlg.result


def file_name(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", name).strip(" .")[:80] or "Contacts"


class ContactsView:
    def __init__(self, win, key: str, people: list[dict]):
        self.win, self.key, self.people = win, key, people
        self.images: dict = {}                       # (contact id or initials, size) -> PhotoImage
        self.by_iid: dict[str, dict] = {}
        self.current = None                          # the contact on the card
        self.list_name = ""                          # "" = all contacts
        with_photo = sum(1 for p in people if p.get("photo"))
        win.view_sub.configure(text=f"{len(people):,} contacts · {with_photo:,} with a photo")
        parent = win.content

        top = tk.Frame(parent, bg=BG)
        top.pack(fill="x", pady=(0, 6))
        tk.Label(top, text="🔍", bg=BG, font=font(13)).pack(side="left")
        self.q = tk.StringVar()
        ttk.Entry(top, textvariable=self.q, width=32).pack(side="left", padx=(4, 10))
        self.count = tk.Label(top, text="", bg=BG, fg=MUTED, font=font(12))
        self.count.pack(side="left")

        foot = tk.Frame(parent, bg=BG)               # packed before the body so it always shows
        foot.pack(side="bottom", fill="x", pady=(10, 0))
        RoundButton(foot, "Save as vCard", self.save_vcard, "primary", 150, 38, 12).pack(side="right")
        RoundButton(foot, "Excel", lambda: self.save_table("excel"), "secondary", 80, 38, 12).pack(side="right", padx=6)
        RoundButton(foot, "CSV", lambda: self.save_table("csv"), "secondary", 70, 38, 12).pack(side="right")
        tk.Label(foot, text="Saves the selected contacts, or everything shown", bg=BG, fg=MUTED,
                 font=font(11)).pack(side="right", padx=8)

        body = tk.Frame(parent, bg=BG)
        body.pack(fill="both", expand=True)
        st = ttk.Style(parent)
        st.configure("Contacts.Treeview", background=CARD, fieldbackground=CARD, foreground=INK, rowheight=30,
                     font=font(13))
        st.map("Contacts.Treeview", background=[("selected", theme.ACCENT_PALE)], foreground=[("selected", INK)])

        side = card(body)
        side.pack(side="left", fill="y")
        tk.Label(side, text="Lists", bg=CARD, fg=MUTED, font=font(11, "bold"), anchor="w").pack(fill="x", padx=10,
                                                                                                pady=(8, 2))
        lists = [("All contacts", len(people))] + sx.contact_lists(people)
        self.lists = ttk.Treeview(side, columns=("n",), show="tree", selectmode="browse",
                                  height=max(4, min(len(lists), 16)), style="Contacts.Treeview")
        self.lists.column("#0", width=190)
        self.lists.column("n", width=56, anchor="e")
        self.list_of: dict[str, str] = {}
        for i, (name, n) in enumerate(lists):
            iid = f"l{i}"
            self.lists.insert("", "end", iid=iid, text=name, values=(f"{n:,}",))
            self.list_of[iid] = "" if i == 0 else name
        self.lists.pack(fill="y", expand=True, padx=4, pady=(0, 6))
        self.lists.selection_set("l0")
        self.lists.bind("<<TreeviewSelect>>", self._pick_list)

        self.card_box = card(body)
        self.card_box.pack(side="right", fill="y", padx=(10, 0))
        self.card_box.configure(width=340)
        self.card_box.pack_propagate(False)

        mid = card(body)
        mid.pack(side="left", fill="both", expand=True, padx=(10, 0))
        self.tree = ttk.Treeview(mid, columns=("detail",), show="tree", selectmode="extended",
                                 style="Contacts.Treeview")
        self.tree.column("#0", width=260, stretch=True)
        self.tree.column("detail", width=200, stretch=True)
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        sb.pack(side="right", fill="y", pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._pick_row)

        self.q.trace_add("write", lambda *_a: self.fill())
        self.fill()
        win.find_hook = (key, self.q, self.pick)
        win.contacts_view = self                     # the tests and real_check look at it
        self.show_card(None)

    # -- the list ---------------------------------------------------------------------------------------------------
    def image(self, p: dict, size: int):
        from PIL import ImageTk
        k = (p["id"] if p.get("photo") else initials(p), size)
        if k not in self.images:
            self.images[k] = ImageTk.PhotoImage(avatar(p, size), master=self.win)
        return self.images[k]

    def shown(self) -> list[dict]:
        import search
        t = search.fold(self.q.get()).strip()
        out = []
        for p in self.people:
            if not sx.in_list(p, self.list_name):
                continue
            if t and not any(t in search.fold(str(x)) for x in sx.contact_row(p)):
                continue
            out.append(p)
        return out

    def fill(self):
        self.tree.delete(*self.tree.get_children())
        self.by_iid.clear()
        vis = self.shown()
        for p in vis:
            iid = str(p["id"])
            first = (p["phones"] or p["emails"] or [("", p.get("org") or "")])[0][1]
            self.tree.insert("", "end", iid=iid, text="  " + p["name"], image=self.image(p, ROW_PX), values=(first,))
            self.by_iid[iid] = p
        total = len([p for p in self.people if sx.in_list(p, self.list_name)])
        self.count.configure(text=f"{len(vis):,} of {total:,}")

    def selected(self) -> list[dict]:
        return [self.by_iid[i] for i in self.tree.selection() if i in self.by_iid]

    def _pick_list(self, _e=None):
        sel = self.lists.selection()
        self.list_name = self.list_of.get(sel[0], "") if sel else ""
        self.fill()

    def _pick_row(self, _e=None):
        sel = self.selected()
        if sel:
            self.show_card(sel[0])

    def pick(self, ref):
        """E4: a search result chose this contact (its place in the list the search read)."""
        p = self.people[ref]
        if not sx.in_list(p, self.list_name):
            self.lists.selection_set("l0")
            self.list_name = ""
            self.fill()
        iid = str(p["id"])
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)
            self.show_card(p)

    # -- the contact card -------------------------------------------------------------------------------------------
    def show_card(self, p):
        self.current = p
        self.links = []                              # (kind, label widget, value): what a click copies
        for w in self.card_box.winfo_children():
            w.destroy()
        if p is None:
            tk.Label(self.card_box, text="Click a contact to see their card.", bg=CARD, fg=MUTED,
                     font=font(12)).pack(padx=16, pady=24)
            return
        head = tk.Frame(self.card_box, bg=CARD)
        head.pack(fill="x", padx=16, pady=(16, 8))
        self.card_photo = tk.Label(head, image=self.image(p, CARD_PX), bg=CARD)
        self.card_photo.pack()
        tk.Label(head, text=p["name"], bg=CARD, fg=INK, font=font(17, "bold"), wraplength=300).pack(pady=(8, 0))
        sub = " · ".join(x for x in (p.get("title"), p.get("org")) if x)
        if sub and sub != p["name"]:
            tk.Label(head, text=sub, bg=CARD, fg=MUTED, font=font(12), wraplength=300).pack()
        rows = tk.Frame(self.card_box, bg=CARD)
        rows.pack(fill="both", expand=True, padx=16)

        def field(label, value, kind=None):
            tk.Label(rows, text=label, bg=CARD, fg=MUTED, font=font(11), anchor="w").pack(fill="x", pady=(6, 0))
            w = tk.Label(rows, text=value, bg=CARD, fg=theme.LINK if kind else INK, font=font(13), anchor="w",
                         justify="left", wraplength=300, cursor="hand2" if kind else "")
            w.pack(fill="x")
            if kind:
                w.bind("<Button-1>", lambda e, v=value, k=kind: self.copy(v, k))
                self.links.append((kind, w, value))
        for lab, v in p.get("phones", ()):
            field(lab or "phone", v, "phone number")
        for lab, v in p.get("emails", ()):
            field(lab or "email", v, "email address")
        for lab, v in p.get("addresses", ()):
            field(f"{lab} address" if lab else "address", v, "address")
        for lab, v in p.get("urls", ()):
            field(lab if lab and lab != "homepage" else "website", v, "web address")
        if p.get("birthday"):
            try:
                d = dt.date.fromisoformat(p["birthday"])
                field("birthday", f"{d.day} {d:%B %Y}")
            except ValueError:
                field("birthday", p["birthday"])
        lists = list(p.get("accounts", ())) + list(p.get("groups", ()))
        if lists:
            field("lists", ", ".join(lists))
        if p.get("note"):
            field("note", p["note"][:600] + ("…" if len(p["note"]) > 600 else ""))
        if self.links:
            tk.Label(self.card_box, text="Click a number, email, address or link to copy it", bg=CARD, fg=MUTED,
                     font=font(11)).pack(side="bottom", pady=(4, 12))

    def copy(self, value: str, what: str):
        """Copies, nothing more: no call, no email, no map (a map would send the address to the internet)."""
        self.win.clipboard_clear()
        self.win.clipboard_append(value)
        self.win.banner(f"✓ Copied the {what}")

    # -- saving -----------------------------------------------------------------------------------------------------
    def chosen(self) -> list[dict]:
        return self.selected() or self.shown()

    def save_vcard(self):
        import phone
        people = self.chosen()
        if not people:
            return
        folder = self.win.out_dir(self.key)
        if folder is None:
            return
        name = people[0]["name"] if len(people) == 1 else (self.list_name or "Contacts")
        path = Path(folder) / f"{file_name(name)}.vcf"
        if path.exists():
            choice = ask_conflict(self.win, path.name)
            if choice in (None, "skip"):
                if choice == "skip":
                    self.win.banner(f"Not saved: “{path.name}” was already there")
                return
            if choice == "both":
                path = phone.unique_path(path)

        def go():
            tmp = path.with_name(path.name + ".part")
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                for p in people:
                    f.write(sx.vcard(p))
            tmp.replace(path)
            return [path]
        self.win.run_save(f"{len(people):,} contact{'s' if len(people) != 1 else ''}", go, folder, "file")

    def save_table(self, kind: str):
        import phone
        people = self.chosen()
        if not people:
            return
        folder = self.win.out_dir(self.key)
        if folder is None:
            return
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H%M")
        path = phone.unique_path(Path(folder) / f"{file_name(self.list_name or 'Contacts')} {stamp}."
                                                f"{'xlsx' if kind == 'excel' else 'csv'}")
        rows = [[str(x) for x in sx.contact_row(p)] for p in people]

        def go():
            import tables as tb
            if kind == "excel":
                tb.write_table_xlsx(path, "Contacts", sx.CONTACT_HEADERS, rows)
            else:
                tb.write_csv_rows(path, sx.CONTACT_HEADERS, rows)
            return [path]
        self.win.run_save(f"{len(people):,} contacts", go, folder, "file")
