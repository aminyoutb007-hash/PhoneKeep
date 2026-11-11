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


def _crash_log() -> None:
    """Any uncaught error in the packaged app goes to ~/PhoneKeep/crash.log (plain text, no personal data),
    so a crash can be diagnosed without a terminal."""
    import traceback
    from pathlib import Path

    def hook(exc_type, exc, tb):
        try:
            p = Path.home() / "PhoneKeep" / "crash.log"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                import datetime as dt
                f.write(f"--- {dt.datetime.now().isoformat(timespec='seconds')} {sys.argv[1:2]}\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook


def _lockdown_run(udid, coro_fn) -> None:
    """Internal: connect to the phone's backup service and run `coro_fn(service)`.
    Prints PKERR <message> and exits 1 on failure; exit 3 if this pymobiledevice3 lacks the API."""
    import asyncio
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.mobilebackup2 import Mobilebackup2Service
    except ImportError as e:
        print(f"PKAPI {e}", flush=True)
        sys.exit(3)

    async def run():
        async with await create_using_usbmux(serial=udid) as lockdown:
            async with Mobilebackup2Service(lockdown) as svc:
                await coro_fn(svc)
    try:
        asyncio.run(run())
    except Exception as e:
        print(f"PKERR {type(e).__name__}: {e}", flush=True)
        sys.exit(1)


def _pk_will_encrypt(args: list) -> None:
    """Internal: print whether the phone's backups are encrypted: PKWILLENCRYPT 1 or 0."""
    udid = args[args.index("--udid") + 1] if "--udid" in args else None

    async def go(svc):
        print(f"PKWILLENCRYPT {1 if await svc.get_will_encrypt() else 0}", flush=True)
    _lockdown_run(udid, go)


def _pk_wifi(args: list) -> None:
    """Internal: turn the phone's Wi-Fi sync (wireless lockdown) on or off."""
    import asyncio
    on = args[0] == "on"
    udid = args[args.index("--udid") + 1] if "--udid" in args else None
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
    except ImportError as e:
        print(f"PKAPI {e}", flush=True)
        sys.exit(3)

    async def run():
        async with await create_using_usbmux(serial=udid) as lockdown:
            await lockdown.set_value(on, key="EnableWifiConnections", domain="com.apple.mobile.wireless_lockdown")
            print("PKDONE", flush=True)
    try:
        asyncio.run(run())
    except Exception as e:
        print(f"PKERR {type(e).__name__}: {e}", flush=True)
        sys.exit(1)


def _pk_battery(args: list) -> None:
    """Internal: print PKBATTERY charging=<0|1> level=<0-100> from the phone's battery domain."""
    import asyncio
    udid = args[args.index("--udid") + 1] if "--udid" in args else None
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
    except ImportError as e:
        print(f"PKAPI {e}", flush=True)
        sys.exit(3)

    async def run():
        async with await create_using_usbmux(serial=udid) as lockdown:
            v = await lockdown.get_value(domain="com.apple.mobile.battery")
            v = v or {}
            print(f"PKBATTERY charging={1 if v.get('BatteryIsCharging') else 0} level={int(v.get('BatteryCurrentCapacity', -1))}", flush=True)
    try:
        asyncio.run(run())
    except Exception as e:
        print(f"PKERR {type(e).__name__}: {e}", flush=True)
        sys.exit(1)


def _pk_storage(args: list) -> None:
    """Internal: print PKSTORAGE total=<bytes> used=<bytes> free=<bytes> from the phone's disk-usage domain."""
    import asyncio
    udid = args[args.index("--udid") + 1] if "--udid" in args else None
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
    except ImportError as e:
        print(f"PKAPI {e}", flush=True)
        sys.exit(3)

    async def run():
        async with await create_using_usbmux(serial=udid) as lockdown:
            v = (await lockdown.get_value(domain="com.apple.disk_usage")) or {}
            total = int(v.get("TotalDiskCapacity") or v.get("TotalDataCapacity") or 0)
            free = int(v.get("TotalDataAvailable") or 0)
            cap = int(v.get("TotalDataCapacity") or total)
            print(f"PKSTORAGE total={total} used={max(0, cap - free)} free={free}", flush=True)
    try:
        asyncio.run(run())
    except Exception as e:
        print(f"PKERR {type(e).__name__}: {e}", flush=True)
        sys.exit(1)


def _pk_change_password(args: list) -> None:
    """Internal: change the backup password. The old and new passwords arrive on stdin, one per
    line, never on the command line."""
    udid = args[args.index("--udid") + 1] if "--udid" in args else None
    old = sys.stdin.readline().rstrip("\r\n")
    new = sys.stdin.readline().rstrip("\r\n")

    async def go(svc):
        await svc.change_password(".", old, new)
        print("PKDONE", flush=True)
    _lockdown_run(udid, go)


def main() -> None:
    _crash_log()
    # No network (S3): refuse every internet connection from this process, app or helper.
    import netguard
    netguard.install()
    args = sys.argv[1:]
    if len(args) >= 2 and args[0] == "--pk-backup":
        _pk_backup(args[1:])
        return
    if args and args[0] == "--pk-will-encrypt":
        _pk_will_encrypt(args[1:])
        return
    if args and args[0] == "--pk-change-password":
        _pk_change_password(args[1:])
        return
    if args and args[0] == "--pk-storage":
        _pk_storage(args[1:])
        return
    if args and args[0] == "--pk-battery":
        _pk_battery(args[1:])
        return
    if len(args) >= 2 and args[0] == "--pk-wifi":
        _pk_wifi(args[1:])
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
    if args and args[0] == "--pk-helper":
        import helper_ui
        sys.exit(helper_ui.main())
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
    if args == ["--open-phone"]:
        import app
        win = app.App()
        win.open_phone_when_ready()
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
