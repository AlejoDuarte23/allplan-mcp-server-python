@echo off
rem Double-click installer: runs install.ps1 from this folder.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
pause
