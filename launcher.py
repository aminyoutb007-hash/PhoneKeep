"""
Single entry point for the packaged PhoneKeep app (.app / .exe).

  PhoneKeep                       -> opens the window
  PhoneKeep <command> ...         -> command line (devices, backup, export, ...)
  PhoneKeep -m pymobiledevice3 …  -> internal: the iPhone helper the app runs for backups
"""
import multiprocessing
import sys


def _pk_backup(args: list) -> None:
    """Internal: back up the iPhone and print machine-readable progress, one line each:
         PKPCT 37.5            percent done, as reported by the iPhone
         PKERR <message>       what went wrong
    Exit code 3 = this pymobiledevice3 lacks the API (the caller falls back to its CLI)."""
    import asyncio
    import traceback
    directory = args[0]
    full = "--full" in args
    udid = args[args.index("--udid") + 1] if "--udid" in args else None
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
    except ImportError as e:
        print(f"PKAPI {e}", flush=True)
        sys.exit(3)

    async def run():
        async with await create_using_usbmux(serial=udid) as lockdown:
            async with Mobilebackup2Service(lockdown) as svc:
                last = [-1.0]

                def cb(p):
                    try:
                        p = float(p)
                    except (TypeError, ValueError):
                        return
                    if p >= 100 or abs(p - last[0]) >= 0.1:
                        last[0] = p
                        print(f"PKPCT {p:.1f}", flush=True)

                print("PKSTAGE started", flush=True)
                await svc.backup(full=full, backup_directory=directory, progress_callback=cb)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        traceback.print_exc(file=sys.stdout)
        print(f"PKERR {type(e).__name__}: {e}", flush=True)
        sys.exit(1)


def main() -> None:
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--pk-backup":
        _pk_backup(args[1:])
        return
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
    if args == ["--pk-launch-check"]:
        # Internal, used by the installer build: open the real window, prove it drew, then quit.
        # Prints "PKLAUNCH ok <version>" so the build can check the packaged app actually starts.
        import app
        import phonekeep
        win = app.App()
        win.after(2500, lambda: (print(f"PKLAUNCH ok {phonekeep.full_version()}", flush=True), win.destroy()))
        win.mainloop()
        return
    if args:
        import phonekeep
        sys.exit(phonekeep.main(args))
    import app
    app.App().mainloop()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
