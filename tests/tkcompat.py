"""Helpers for how the machines the window tests run on differ: Tk 8.6 on a Mac, and small screens (nothing here
changes PhoneKeep itself)."""
import sys
import tkinter as tk


def hide(w) -> None:
    """Keep a test's window out of sight. Tk 8.6 on a Mac (the Tk the installers bundle, and GitHub's Mac
    machines' Python) redraws a withdrawn phone or Settings window without end, and also one tied (transient) to a
    withdrawn window or a Toplevel of one, so update() never returns and the test hangs until its time limit.
    There the window is made see-through instead. In PhoneKeep itself only the main window is ever withdrawn
    (B9, while a backup carries on), and its event loop doesn't spin then (measured 18 Nov)."""
    if sys.platform == "darwin" and tk.TkVersion < 8.7:
        w.attributes("-alpha", 0.0)
    else:
        w.withdraw()



def show(w) -> None:
    """Undo hide(): the window shown again, for a test that needs a real window (keys, clicks)."""
    if sys.platform == "darwin" and tk.TkVersion < 8.7:
        w.attributes("-alpha", 1.0)
    w.deiconify()
    w.lift()


def too_small(win, width: int, height: int) -> str:
    """Why `win` can't have its normal size width x height on this computer (its screen is smaller), or ""."""
    win.update_idletasks()
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    if sw < width or sh < height:
        return f"the screen is {sw}x{sh}, smaller than the window's normal {width}x{height}"
    return ""


def screen(win) -> str:
    """The screen and the window's size, for a test's output."""
    win.update_idletasks()
    return (f"screen {win.winfo_screenwidth()}x{win.winfo_screenheight()}, "
            f"window {win.winfo_width()}x{win.winfo_height()}")
