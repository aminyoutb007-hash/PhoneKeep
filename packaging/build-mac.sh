#!/bin/bash
# Build PhoneKeep.app and PhoneKeep.dmg on your own Mac (alternative to GitHub).
# Needs Python 3 from python.org. Run:  bash packaging/build-mac.sh
set -e
cd "$(dirname "$0")/.."
python3 -m venv .build-venv
.build-venv/bin/python -m pip install -q --upgrade pip
.build-venv/bin/python -m pip install -q -r requirements.txt pyinstaller
.build-venv/bin/python packaging/make_icons.py
.build-venv/bin/pyinstaller packaging/PhoneKeep.spec --noconfirm
codesign --force --deep --sign - dist/PhoneKeep.app
rm -rf dmg && mkdir dmg && cp -R dist/PhoneKeep.app dmg/ && ln -s /Applications dmg/Applications
hdiutil create -volname "PhoneKeep" -srcfolder dmg -ov -format UDZO PhoneKeep.dmg
rm -rf dmg
echo; echo "Done: $(pwd)/PhoneKeep.dmg"
