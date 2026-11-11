#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting up PhoneKeep..."
  python3 -m venv .venv || { echo "Python 3 is required: https://www.python.org/downloads/"; read; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
fi
.venv/bin/python -m pip install -q -r requirements.txt
.venv/bin/python app.py
