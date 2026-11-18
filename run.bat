@echo off
rem Start Clawd without a console window
if exist "%LOCALAPPDATA%\Python\bin\pythonw.exe" (
  start "" "%LOCALAPPDATA%\Python\bin\pythonw.exe" "%~dp0clawd.py"
) else (
  start "" pythonw "%~dp0clawd.py"
)
