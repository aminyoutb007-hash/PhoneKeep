"""The menu bar (Mac) / system tray (Windows) icon for the helper (E2).

Mac: rumps (a thin wrapper over AppKit's NSStatusItem). Windows and Linux: pystray.
Both show the same menu: status line(s), Back up now, Open iPhone, Open PhoneKeep,
Pause automatic backups, Quit. The icon carries a thin progress ring during a backup.
Notifications: the system's own (Notification Center / Windows toast), local only.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import helper_core as hc

TMP = Path(tempfile.gettempdir()) / "phonekeep-helper"


def notify_system(title: str, text: str) -> None:
    """A local system notification (no network, no identifiers)."""
    try:
        if sys.platform == "darwin":
            # Notification Center through AppleScript: works unsigned, no bundle needed
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.Popen(["osascript", "-e", f'display notification "{esc(text)}" with title "PhoneKeep" subtitle "{esc(title)}"'])
        elif sys.platform == "win32":
            _ICON and _ICON.notify(text, f"PhoneKeep · {title}")
        else:
            subprocess.Popen(["notify-send", f"PhoneKeep · {title}", text])
    except Exception:
        pass


_ICON = None


def _icon_file(progress=None, template=False) -> Path:
    TMP.mkdir(parents=True, exist_ok=True)
    key = "ring" if progress is None else f"ring{int(progress) // 4}"   # 25 ring images at most
    p = TMP / f"{key}{'-t' if template else ''}.png"
    if not p.exists():
        hc.icon_image(progress, 44 if template else 64, template).save(p)
    return p


# -- Mac -----------------------------------------------------------------------------------------------

def run_mac(helper: hc.Helper):
    import rumps

    class App(rumps.App):
        def __init__(self):
            super().__init__("PhoneKeep", icon=str(_icon_file(template=True)), template=True, quit_button=None)
            self.status_items = [rumps.MenuItem(" ") for _ in range(3)]
            self.backup = rumps.MenuItem("Back up now", callback=self.on_backup)
            self.pause = rumps.MenuItem("Pause automatic backups", callback=self.on_pause)
            self.menu = [*self.status_items, None, self.backup,
                         rumps.MenuItem("Open iPhone", callback=lambda _: helper.open_app("phone")),
                         rumps.MenuItem("Open PhoneKeep", callback=lambda _: helper.open_app("window")),
                         None, self.pause, None, rumps.MenuItem("Quit", callback=self.on_quit)]
            self.refresh()

        def refresh(self):
            lines = helper.status_lines()
            for i, item in enumerate(self.status_items):
                item.title = lines[i] if i < len(lines) else " "
                item.set_callback(None)
            self.backup.title = "Backing up…" if helper.busy else "Back up now"
            self.pause.state = 1 if helper.paused else 0
            self.icon = str(_icon_file(helper.progress, template=True))

        def on_backup(self, _):
            if not helper.back_up_now():
                self.refresh()

        def on_pause(self, _):
            helper.set_paused(not helper.paused)

        def on_quit(self, _):
            hc.release_lock()
            rumps.quit_application()

        @rumps.timer(300)
        def every_five_minutes(self, _):
            helper.refresh_devices()

        @rumps.timer(60)
        def every_minute(self, _):
            threading.Thread(target=helper.tick, daemon=True).start()

    app = App()
    helper.on_change = lambda: threading.Thread(target=app.refresh, daemon=True).start()
    helper.refresh_devices(force=True)
    app.run()


# -- Windows and Linux --------------------------------------------------------------------------------------

def run_tray(helper: hc.Helper):
    import pystray
    from pystray import Menu, MenuItem as Item
    global _ICON

    def status_lines():
        return helper.status_lines()

    def menu():
        return Menu(
            *[Item(line, None, enabled=False) for line in status_lines()],
            Menu.SEPARATOR,
            Item("Backing up…" if helper.busy else "Back up now", lambda: helper.back_up_now(), enabled=not helper.busy),
            Item("Open iPhone", lambda: helper.open_app("phone")),
            Item("Open PhoneKeep", lambda: helper.open_app("window")),
            Menu.SEPARATOR,
            Item("Pause automatic backups", lambda: helper.set_paused(not helper.paused), checked=lambda _: helper.paused),
            Menu.SEPARATOR,
            Item("Quit", lambda: (hc.release_lock(), icon.stop())),
        )

    icon = pystray.Icon("PhoneKeep", hc.icon_image(), "PhoneKeep", menu=Menu(lambda: list(menu().items)))
    _ICON = icon

    def changed():
        try:
            icon.icon = hc.icon_image(helper.progress)
            icon.update_menu()
        except Exception:
            pass
    helper.on_change = changed

    def poll():
        import time
        n = 0
        while True:
            time.sleep(60)
            n += 1
            try:
                helper.tick()
                if n % 5 == 0:
                    helper.refresh_devices()
            except Exception:
                pass
    threading.Thread(target=poll, daemon=True).start()
    helper.refresh_devices(force=True)
    icon.run()


def main() -> int:
    """Entry point for `PhoneKeep --pk-helper`. One helper at a time."""
    if not hc.take_lock():
        return 0
    helper = hc.Helper(notify_system)
    try:
        if sys.platform == "darwin":
            run_mac(helper)
        else:
            run_tray(helper)
    finally:
        hc.release_lock()
    return 0
