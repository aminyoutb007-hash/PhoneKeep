"""Two ways the machines the window tests run on differ (nothing here changes PhoneKeep itself)."""
import sys
import tkinter as tk


def hide(w) -> None:
    """Keep a test's phone window out of sight. Tk 8.6 on a Mac (the Tk the installers bundle, and GitHub's Mac
    machines' Python) redraws a withdrawn phone window without end, so update() never returns and the test hangs
    until its time limit; there it is made see-through instead. PhoneKeep itself never withdraws a phone window
    (only the main window, in B9, which doesn't do this)."""
    if sys.platform == "darwin" and tk.TkVersion < 8.7:
        w.attributes("-alpha", 0.0)
    else:
        w.withdraw()


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
