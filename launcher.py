"""
Single entry point for the packaged PhoneKeep app (.app / .exe).

  PhoneKeep                       -> opens the window
  PhoneKeep <command> ...         -> command line (devices, backup, export, ...)
  PhoneKeep -m pymobiledevice3 …  -> internal: the iPhone helper the app runs for backups
"""
import multiprocessing
import sys


def main() -> None:
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--pk-encryption":
        # Internal: change backup encryption. The password arrives on stdin, never on the
        # command line, so other programs on this computer can't read it from the process list.
        import runpy
        password = sys.stdin.readline().rstrip("\r\n")
        sys.argv = ["pymobiledevice3", "backup2", "encryption", *args[2:], args[1], password]
        runpy.run_module("pymobiledevice3", run_name="__main__", alter_sys=True)
        return
    if len(args) >= 2 and args[0] == "-m" and args[1] == "pymobiledevice3":
        import runpy
        sys.argv = ["pymobiledevice3"] + args[2:]
        runpy.run_module("pymobiledevice3", run_name="__main__", alter_sys=True)
        return
    args = [a for a in args if not a.startswith("-psn_")]  # macOS Finder launch arg
    if args:
        import phonekeep
        sys.exit(phonekeep.main(args))
    import app
    app.App().mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
