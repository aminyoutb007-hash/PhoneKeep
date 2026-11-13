#!/bin/bash
# Build PhoneKeep.app on your own Mac (alternative to GitHub) and install it in /Applications.
#
#   bash packaging/build-mac.sh            # build + install, label "<next>-dev+<branch>-local"
#   bash packaging/build-mac.sh --dmg      # also make PhoneKeep.dmg
#
# Needs Homebrew Python 3.12 with Tk:  brew install python@3.12 python-tk@3.12
# (the Python that ships with macOS is too old for the wheels we need; rumps has no wheel, so it is
# installed without dependencies after everything else came in as binary wheels).
set -e
cd "$(dirname "$0")/.."

PY=$(command -v python3.12 || true)
if [ -z "$PY" ]; then
  echo "Python 3.12 not found. Run:  brew install python@3.12 python-tk@3.12" >&2; exit 1
fi
"$PY" -c "import tkinter" 2>/dev/null || { echo "Tk missing. Run:  brew install python-tk@3.12" >&2; exit 1; }

[ -d .build-venv ] || "$PY" -m venv .build-venv
V=.build-venv/bin/python
"$V" -m pip install -q --upgrade pip
grep -v -i '^rumps' requirements.txt > .build-venv/req.txt
"$V" -m pip install -q --only-binary=:all: -r .build-venv/req.txt pyinstaller
"$V" -m pip install -q --no-deps rumps
"$V" -c "import Foundation, AppKit, Quartz, rumps" || { echo "rumps/pyobjc not importable in the build venv" >&2; exit 1; }

# label: "<next release>-dev+<ID>-local", like GitHub's pull-request builds, from the branch name
NEXT=$(cat packaging/next-release.txt 2>/dev/null || echo 0)
BR=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo local)
ID=$(echo "$BR" | cut -d- -f1 | tr '[:lower:]' '[:upper:]')
LABEL="${NEXT}-dev+${ID}-local"
printf 'BUILD_LABEL = "%s"\n' "$LABEL" > build_label.py

"$V" packaging/make_icons.py
"$V" -m PyInstaller packaging/PhoneKeep.spec --noconfirm
codesign --force --deep --sign - dist/PhoneKeep.app
printf 'BUILD_LABEL = ""\n' > build_label.py          # keep the committed file empty

# the launch check opens the real window; PHONEKEEP_NO_HELPER keeps it from starting the menu bar helper
PHONEKEEP_NO_HELPER=1 dist/PhoneKeep.app/Contents/MacOS/phonekeep-cli --pk-launch-check | grep -q "PKLAUNCH ok"
echo "Launch check: ok ($LABEL)"

if pgrep -x PhoneKeep >/dev/null || pgrep -f "phonekeep-cli" >/dev/null; then
  echo "PhoneKeep is still running (the window, the menu bar helper or a backup helper)." >&2
  echo "Quit it, then:  pkill -f phonekeep-cli   and run this again." >&2; exit 1
fi
rm -rf /Applications/PhoneKeep.app
cp -R dist/PhoneKeep.app /Applications/
echo "Installed /Applications/PhoneKeep.app ($LABEL)"

if [ "$1" = "--dmg" ]; then
  rm -rf dmg && mkdir dmg && cp -R dist/PhoneKeep.app dmg/ && ln -s /Applications dmg/Applications
  hdiutil create -volname "PhoneKeep" -srcfolder dmg -ov -format UDZO PhoneKeep.dmg
  rm -rf dmg
  echo "Done: $(pwd)/PhoneKeep.dmg"
fi
