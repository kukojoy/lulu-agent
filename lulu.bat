@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lulu.ps1"
exit /b %ERRORLEVEL%
