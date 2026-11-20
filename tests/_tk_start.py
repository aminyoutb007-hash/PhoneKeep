"""Starts one test script for run_all on a Mac (tests/run_all.py: `python tests/_tk_start.py <script>`).

When a Python process that has a Tk window is killed (run_all stops a hung test that way), macOS counts it as a
crash. The next Python to start Tk then waits in tk.Tk() on the "reopen its windows?" prompt
(NSPersistentUIRestorer), so every test after a hang hung too. This sets ApplePersistenceIgnoreState in memory for
this process only (registered defaults: nothing is written to the Mac's settings) and then runs the script
as __main__, with the same sys.argv and sys.path[0] as `python <script>`."""
import os, runpy, sys

if sys.platform == "darwin":
    try:
        from Foundation import NSUserDefaults
        NSUserDefaults.standardUserDefaults().registerDefaults_({"ApplePersistenceIgnoreState": True})
    except ImportError:          # no PyObjC: the test runs as before
        pass

sys.argv = sys.argv[1:]                    # the script as it was given, then its own arguments
script = os.path.abspath(sys.argv[0])      # __file__ and sys.path[0] as Python gives them
# (resolved on Mac and Linux; on Windows as given, e.g. a short C:\Users\RUNNER~1 path stays short)
sys.path[0] = os.path.dirname(script if sys.platform == "win32" else os.path.realpath(script))
runpy.run_path(script, run_name="__main__")
