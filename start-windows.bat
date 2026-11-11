@echo off
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv (
  echo First run: setting up PhoneKeep...
  %PY% -m venv .venv || (echo Python 3 is required: https://www.python.org/downloads/ & pause & exit /b 1)
  .venv\Scripts\python -m pip install --upgrade pip
)
.venv\Scripts\python -m pip install -q -r requirements.txt
.venv\Scripts\python app.py
if errorlevel 1 pause
