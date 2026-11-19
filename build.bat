@echo off
rem Builds dist\Clawd.exe (single file, no console). Needs: pip install -r requirements.txt pyinstaller pillow
python make_icon.py || goto :eof
python -m PyInstaller --noconfirm --onefile --windowed --name Clawd --icon assets\clawd.ico ^
  --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick ^
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtSvg --exclude-module tkinter ^
  clawd.py
echo.
echo Done: dist\Clawd.exe
