@echo off
rem Run from source without a console window (needs Python + pip install -r requirements.txt)
if exist "%LOCALAPPDATA%\Python\bin\pythonw.exe" (
  start "" "%LOCALAPPDATA%\Python\bin\pythonw.exe" "%~dp0clawd.py"
) else (
  start "" pythonw "%~dp0clawd.py"
)
