# PyInstaller recipe: builds PhoneKeep.app (macOS), PhoneKeep\ folder (Windows) or a Linux binary.
# Run from the project folder:  pyinstaller packaging/PhoneKeep.spec
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
for pkg in ("pymobiledevice3", "pillow_heif", "iphone_backup_decrypt", "openpyxl"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:
        print(f"note: could not collect {pkg}: {e}")
# pymobiledevice3's CLI pulls in many lazily-imported libraries
for pkg in ("typer", "rich", "click", "construct", "asn1", "srptools", "pycrashreport",
            "developer_disk_image", "ipsw_parser", "pygnuutils", "hyperframe", "qh3", "opack2"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass
hiddenimports += ["sections", "phonekeep", "app", "ui", "photos", "tables", "tkinter",
                  "PIL.ImageOps", "PIL.ImageTk", "PIL._tkinter_finder"]

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # project folder
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
                     "CFBundleShortVersionString": "3.0.0",
                     "CFBundleVersion": "3.0.0",
                     "NSHighResolutionCapable": True,
                     "LSMinimumSystemVersion": "11.0",
                     "NSHumanReadableCopyright": "Open source. Runs locally; nothing is uploaded.",
                 })
