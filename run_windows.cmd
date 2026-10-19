@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Windows Python environment is missing. Read WINDOWS_SETUP.md first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import sys; assert sys.version_info >= (3, 11); from PySide6 import QtWidgets, QtNetwork"
if errorlevel 1 (
  echo Python or Qt environment check failed. Read WINDOWS_SETUP.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" main.py
set "app_exit=%errorlevel%"
if not "%app_exit%"=="0" (
  echo Application exited with an error. Review the output and .logs folder.
  pause
)
exit /b %app_exit%
