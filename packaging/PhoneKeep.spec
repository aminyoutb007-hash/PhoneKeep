# PyInstaller recipe: builds PhoneKeep.app (macOS), PhoneKeep\ folder (Windows) or a Linux binary.
# Run from the project folder:  pyinstaller packaging/PhoneKeep.spec
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas, binaries, hiddenimports = [], [], []
for pkg in ("pymobiledevice3", "pillow_heif", "iphone_backup_decrypt", "openpyxl", "certifi", "keyring", "tkinterdnd2", "send2trash",
            "reportlab", "arabic_reshaper", "bidi",                       # M3: chats to PDF
            *(("rumps",) if sys.platform == "darwin" else ("pystray",)),
            *(("winrt",) if sys.platform == "win32" else ()),                 # S2: Windows Hello
            *(("LocalAuthentication",) if sys.platform == "darwin" else ())):  # S2: Touch ID (with its lazy _metadata)
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print(f"note: could not collect {pkg}: {e}")
# Package metadata (dist-info) for pymobiledevice3 and everything it depends on: some of those libraries read their
# own version at import (apple_compress, via pyimg4, on a Mac: without it every backup failed in 5.0.0)
for pkg in ("pymobiledevice3", "iphone_backup_decrypt", "reportlab"):
    try:
        datas += copy_metadata(pkg, recursive=True)
    except Exception as e:
        print(f"note: could not copy metadata for {pkg}: {e}")
# pymobiledevice3's CLI pulls in many lazily-imported libraries
for pkg in ("typer", "rich", "click", "construct", "asn1", "srptools", "pycrashreport",
            "developer_disk_image", "ipsw_parser", "pygnuutils", "hyperframe", "qh3", "opack2"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass
hiddenimports += ["quicklook", "overview_ui", "deviceinfo", "sections", "phonekeep", "app", "ui", "photos", "tables", "phone", "device", "build_label",
                  "keychain", "phone_write", "netguard", "certifi", "errors", "firstrun", "helper_core", "helper_ui", "login_item",
                  "scheduler", "snapshots", "location", "chat_pdf", "applock", "models",
                  *(["Foundation", "AppKit", "objc", "PyObjCTools", "Quartz", "LocalAuthentication"] if sys.platform == "darwin" else []),   # rumps; PDFKit; S2
                  *(["winrt.windows.security.credentials.ui", "winrt.windows.foundation"] if sys.platform == "win32" else []),       # S2: Windows Hello
                  "keyring", "keyring.backends.macOS", "keyring.backends.Windows",
                  "keyring.backends.fail", "keyring.backends.null", "tkinter",
                  "PIL.ImageOps", "PIL.ImageTk", "PIL._tkinter_finder"]

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # project folder
datas += [(os.path.join(ROOT, "assets", "fonts"), os.path.join("assets", "fonts"))]   # PDF fonts (M3)
datas += [(os.path.join(ROOT, "assets", "icons"), os.path.join("assets", "icons"))]   # app icons (tools/make_app_icons.py)
ICON = os.path.join(SPECPATH, "icon.ico" if sys.platform == "win32" else "icon.png")

a = Analysis([os.path.join(ROOT, "launcher.py")], pathex=[ROOT], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, excludes=["matplotlib", "numpy", "av", "cv2", "IPython", "pytest"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="PhoneKeep",
          console=False, icon=ICON, argv_emulation=False,
          target_arch=None, codesign_identity=None, entitlements_file=None)
# console twin: the command-line tool, and the helper the app uses to talk to the iPhone
exe_cli = EXE(pyz, a.scripts, [], exclude_binaries=True, name="phonekeep-cli", console=True,
              icon=ICON, target_arch=None, codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, exe_cli, a.binaries, a.datas, name="PhoneKeep")

if sys.platform == "darwin":
    app = BUNDLE(coll, name="PhoneKeep.app", icon=ICON, bundle_identifier="app.phonekeep.PhoneKeep",
                 info_plist={
                     "CFBundleShortVersionString": "5.0.1",
                     "CFBundleVersion": "5.0.1",
                     "NSHighResolutionCapable": True,
                     "LSMinimumSystemVersion": "11.0",
                     "NSHumanReadableCopyright": "Open source. Runs locally; nothing is uploaded.",
                 })
