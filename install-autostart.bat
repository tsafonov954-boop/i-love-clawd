@echo off
rem Put a Clawd shortcut into the Windows Startup folder
set "LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Clawd.lnk"
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%LNK%'); $s.TargetPath='%~dp0run.bat'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"
echo Autostart enabled: %LNK%
pause
