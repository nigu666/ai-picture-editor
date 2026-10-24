@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0deployment\local\manage.ps1" -Action Build
set "taskInstallExit=%ERRORLEVEL%"
pause
exit /b %taskInstallExit%
