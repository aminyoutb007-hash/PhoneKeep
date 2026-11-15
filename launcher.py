"""
Single entry point for the packaged PhoneKeep app (.app / .exe).

  PhoneKeep                       -> opens the window
  PhoneKeep <command> ...         -> command line (devices, backup, export, ...)
  PhoneKeep -m pymobiledevice3 …  -> internal: the iPhone helper the app runs for backups
"""
import multiprocessing
import os
import sys


def _passcode_handler():
    """pymobiledevice3 logs the iPhone's passcode-screen notifications ("Please enter the device passcode…",
    "Device passcode prompt dismissed"); print them as PKPASSCODE lines, so the window can ask for the passcode
    and take the notice down as soon as it's entered (owner, 13 Nov)."""
    import logging

    class Passcode(logging.Handler):
        def emit(self, record):
            msg = record.getMessage().lower()
            if "passcode" in msg and "dismissed" in msg:
                print("PKPASSCODE done", flush=True)
            elif "passcode" in msg and "enter" in msg:
                print("PKPASSCODE shown", flush=True)
    return Passcode(logging.INFO)


def _pk_backup(args: list) -> None:
    """Internal: back up the iPhone and print machine-readable progress, one line each:
         PKPCT 37.5            percent done, as reported by the iPhone
         PKPASSCODE shown      the iPhone shows its passcode screen for this backup
         PKPASSCODE done       ... and it was dismissed (passcode entered)
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

    import logging
    mb2_log = logging.getLogger("pymobiledevice3.services.mobilebackup2")
    mb2_log.addHandler(_passcode_handler())
    mb2_log.setLevel(min(mb2_log.level or logging.INFO, logging.INFO))

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
        if issubclass(exc_type, BrokenPipeError):      # the window closed while a helper was still printing
            return
        try:
            import os
            p = Path(os.environ.get("PHONEKEEP_HOME") or Path.home() / "PhoneKeep") / "crash.log"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                import datetime as dt
                f.write(f"--- {dt.datetime.now().isoformat(timespec='seconds')} {sys.argv[1:2]}\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = hook
    import threading

    def thread_hook(args):                      # crashes on worker threads (the helper's backup thread, say)
        hook(args.exc_type, args.exc_value, args.exc_traceback)
    threading.excepthook = thread_hook


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


def _pk_crashes(args: list) -> None:
    """Internal (H4): copy the phone's crash reports of the last N days into a folder on this computer, read-only:
    the reports stay on the phone (nothing is removed, moved or flushed). Prints PKCRASH <path> for each report
    copied this time, then PKDONE <reports on the phone in the period>.
        --pk-crashes <folder> [--udid UDID] [--days 30]"""
    import asyncio
    import datetime as dt
    import inspect
    import re
    from pathlib import Path
    dest = Path(args[0])
    udid = args[args.index("--udid") + 1] if "--udid" in args else None
    days = int(args[args.index("--days") + 1]) if "--days" in args else 30
    since = dt.datetime.now() - dt.timedelta(days=days)
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.afc import AfcService
    except ImportError as e:
        print(f"PKAPI {e}", flush=True)
        sys.exit(3)

    async def aw(x):
        return await x if inspect.isawaitable(x) else x

    def stamp(name: str):
        m = re.search(r"(\d{4}-\d{2}-\d{2})-(\d{6})", name)       # "Instagram-2026-11-12-101010.ips"
        try:
            return dt.datetime.strptime(m.group(1) + m.group(2), "%Y-%m-%d%H%M%S") if m else None
        except ValueError:
            return None

    async def run():
        async with await create_using_usbmux(serial=udid) as lockdown:
            afc = AfcService(lockdown, service_name="com.apple.crashreportcopymobile")
            await aw(afc.__aenter__())
            try:
                found = 0
                async for root, _dirs, files in afc.walk("/"):
                    for f in files:
                        if not f.endswith((".ips", ".crash", ".panic")):
                            continue
                        rel = "/".join(x for x in (root.strip("/") + "/" + f).split("/") if x)
                        when = stamp(f)
                        if when is None:
                            st = await aw(afc.stat(rel))
                            when = st.get("st_mtime")
                            when = when.replace(tzinfo=None) if isinstance(when, dt.datetime) else None
                        if when is None or when < since:
                            continue
                        found += 1
                        out = dest / rel
                        if out.exists() and out.stat().st_size > 0:
                            continue
                        data = await aw(afc.get_file_contents(rel))
                        out.parent.mkdir(parents=True, exist_ok=True)
                        tmp = out.with_name(out.name + ".part")
                        tmp.write_bytes(data)
                        tmp.replace(out)
                        print(f"PKCRASH {rel}", flush=True)
                print(f"PKDONE {found}", flush=True)
            finally:
                await aw(afc.__aexit__(None, None, None))
    try:
        asyncio.run(run())
    except Exception as e:
        print(f"PKERR {type(e).__name__}: {e}", flush=True)
        sys.exit(1)


JAILBREAK_APPS = ("com.saurik.Cydia", "org.coolstar.SileoStore", "xyz.willy.Zebra", "com.opa334.Dopamine",
                  "com.opa334.TrollStore", "com.tigisoftware.Filza", "me.apptapp.installer", "com.electrateam.chimera",
                  "org.coolstar.electra1131", "science.xnu.undecimus", "com.checkra1n.checkra1n", "in.palera.loader",
                  "com.serena.Antoine", "com.sukisu.loader")


def _pk_security(args: list) -> None:
    """Internal (H5): what the security checks need, read-only, printed as PKSECURITY <json>.
    Only reads: lockdown values, the profile list and cloud configuration (com.apple.mobile.MCInstall's
    GetProfileList / GetCloudConfiguration), the app list, and whether the jailbreak-only file service answers.
        --pk-security [--udid UDID]"""
    import asyncio
    import json
    udid = args[args.index("--udid") + 1] if "--udid" in args else None
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.installation_proxy import InstallationProxyService
        from pymobiledevice3.services.mobile_config import MobileConfigService
    except ImportError as e:
        print(f"PKAPI {e}", flush=True)
        sys.exit(3)

    async def run():
        out = {"problems": {}}
        async with await create_using_usbmux(serial=udid) as lockdown:
            for k, key in (("password_protected", "PasswordProtected"), ("ios", "ProductVersion"),
                           ("product_type", "ProductType"), ("build", "BuildVersion")):
                try:
                    out[k] = await lockdown.get_value(key=key)
                except Exception as e:
                    out["problems"][k] = f"{type(e).__name__}: {e}"
            try:
                async with MobileConfigService(lockdown) as mc:
                    reply = await mc.get_profile_list()
                    meta = reply.get("ProfileMetadata") or {}
                    out["profiles"] = [{"id": pid, "name": m.get("PayloadDisplayName") or pid,
                                        "org": m.get("PayloadOrganization") or "",
                                        "removable": not m.get("PayloadRemovalDisallowed", False)}
                                       for pid, m in meta.items()]
                    manifest = reply.get("ProfileManifest") or {}
                    for prof in out["profiles"]:
                        man = manifest.get(prof["id"]) or {}
                        prof["active"] = bool(man.get("IsActive", True))
                    cc = await mc.get_cloud_configuration() or {}
                    out["management"] = {"supervised": bool(cc.get("IsSupervised")),
                                         "org": cc.get("OrganizationName") or "",
                                         "server": cc.get("ConfigurationURL") or "",
                                         "mdm_unremovable": bool(cc.get("IsMDMUnremovable"))}
            except Exception as e:
                out["problems"]["profiles"] = f"{type(e).__name__}: {e}"
            try:
                async with InstallationProxyService(lockdown) as ip:
                    apps = await ip.get_apps(application_type="Any")
                outside, jb = [], []
                for b, a in (apps or {}).items():
                    name = a.get("CFBundleDisplayName") or a.get("CFBundleName") or b
                    if b in JAILBREAK_APPS:
                        jb.append(f"the jailbreak app {name}")
                    if a.get("ApplicationType") != "User":
                        continue
                    signer = str(a.get("SignerIdentity") or "")
                    market = a.get("MarketplaceID") or a.get("DistributorID") or ""
                    if market or (signer and not signer.startswith("Apple iPhone OS Application Signing")):
                        outside.append({"bundle": b, "name": name, "signer": signer, "marketplace": str(market)})
                out["outside"] = outside
                out["user_apps"] = sum(1 for a in (apps or {}).values() if a.get("ApplicationType") == "User")
                out["jailbreak"] = jb
            except Exception as e:
                out["problems"]["apps"] = f"{type(e).__name__}: {e}"
            try:
                svc = await lockdown.start_lockdown_service("com.apple.afc2")
                out.setdefault("jailbreak", []).append("the full-disk file service (afc2), which only jailbreaks add")
                try:
                    await svc.aclose()
                except Exception:
                    pass
            except Exception:
                pass
        print("PKSECURITY " + json.dumps(out, default=str), flush=True)
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

    import time as _t
    import timing

    async def run():
        t = _t.perf_counter()
        lockdown = await create_using_usbmux(serial=udid)
        timing.log("battery: lockdown connect", _t.perf_counter() - t)
        async with lockdown:
            with timing.step("battery: battery domain"):
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


def _pk_overview(args: list) -> None:
    """Internal (V1-V3): print PKOVERVIEW <json> with what the phone says about itself: lockdown values,
    disk usage, the battery's IORegistry entry and the installed apps with their sizes. Read-only: it asks
    the phone questions and changes nothing on it. A section that can't be read is listed under "problems"."""
    import asyncio
    import json
    udid = args[args.index("--udid") + 1] if "--udid" in args else None
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
    except ImportError as e:
        print(f"PKAPI {e}", flush=True)
        sys.exit(3)
    keep_info = ("DeviceName", "ProductType", "ProductVersion", "SerialNumber", "DeviceColor",
                 "DeviceEnclosureColor", "TotalDiskCapacity", "ModelNumber", "RegionInfo")
    keep_io = ("CycleCount", "DesignCapacity", "NominalChargeCapacity", "AppleRawMaxCapacity", "MaximumCapacityPercent",
               "Temperature", "CurrentCapacity", "IsCharging")

    import time as _t
    import timing
    wifi = "--wifi" in args
    each = 6 if wifi else None                       # Wi-Fi: one slow answer can't hold up the rest (5.1.3)

    def q(coro):
        return asyncio.wait_for(coro, each) if each else coro

    async def run():
        out = {"problems": {}}
        t = _t.perf_counter()
        lockdown = await (asyncio.wait_for(create_using_usbmux(serial=udid), 3 * each) if each
                          else create_using_usbmux(serial=udid))
        timing.log("overview: lockdown connect", _t.perf_counter() - t)
        async with lockdown:
            with timing.step("overview: all lockdown values"):
                allv = (await q(lockdown.get_value())) or {}
            out["info"] = {k: allv.get(k) for k in keep_info if allv.get(k) is not None}
            for k in ("DeviceEnclosureColor", "ModelNumber"):       # not always in the full list: ask by name
                if k not in out["info"]:
                    try:
                        with timing.step(f"overview: lockdown value {k}"):
                            v = await q(lockdown.get_value(key=k))
                        if v is not None:
                            out["info"][k] = v
                    except Exception:
                        pass
            for key, domain in (("disk", "com.apple.disk_usage"), ("battery", "com.apple.mobile.battery")):
                try:
                    with timing.step(f"overview: {key} domain"):
                        out[key] = (await q(lockdown.get_value(domain=domain))) or {}
                except Exception as e:
                    out["problems"][key] = f"{type(e).__name__}: {e}"
            try:
                if wifi:                             # only over a cable; the saved copy is used instead
                    raise RuntimeError("over Wi-Fi: connect by cable for the battery's details")
                from pymobiledevice3.services.diagnostics import DiagnosticsService
                with timing.step("overview: battery ioregistry (diagnostics)"):
                    async with DiagnosticsService(lockdown) as diag:
                        io = (await diag.ioregistry(ioclass="AppleSmartBattery")) or {}
                bd = io.get("BatteryData") if isinstance(io.get("BatteryData"), dict) else {}
                out["battery_io"] = {k: io[k] for k in keep_io if k in io}
                out["battery_io"]["BatteryData"] = {k: bd[k] for k in keep_io if k in bd}
            except Exception as e:
                out["problems"]["battery_io"] = f"{type(e).__name__}: {e}"
            if "--no-apps" not in args:
                try:
                    from pymobiledevice3.services.installation_proxy import InstallationProxyService
                    with timing.step("overview: app list with sizes"):
                        async with InstallationProxyService(lockdown) as ip:
                            apps = await ip.get_apps(application_type="User", calculate_sizes=True)
                    out["apps"] = {b: {k: a.get(k) for k in ("CFBundleDisplayName", "CFBundleName", "StaticDiskUsage",
                                                             "DynamicDiskUsage")} for b, a in (apps or {}).items()}
                except Exception as e:
                    out["problems"]["apps"] = f"{type(e).__name__}: {e}"
        print("PKOVERVIEW " + json.dumps(out, default=str), flush=True)
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
    if args and args[0] == "--pk-overview":
        _pk_overview(args[1:])
        return
    if args and args[0] == "--pk-storage":
        _pk_storage(args[1:])
        return
    if args and args[0] == "--pk-battery":
        _pk_battery(args[1:])
        return
    if args and args[0] == "--pk-security":
        _pk_security(args[1:])
        return
    if len(args) >= 2 and args[0] == "--pk-crashes":
        _pk_crashes(args[1:])
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
    if args == ["--pk-lock-check"]:
        # Internal, used by the installer build: the app lock's system check loads in the packaged app.
        # Prints "PKLOCK <kind or none> <problem>"; a missing module is a build failure (13 Nov: Touch ID
        # never asked in the packaged app).
        import applock
        kind = applock.available()
        print(f"PKLOCK {kind or 'none'} {applock.last_problem}", flush=True)
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
    try:
        app.App().mainloop()
    finally:
        os._exit(0)          # never leave a windowless process behind (see App.quit_app)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
