@echo off
call "%~dp0scripts\windows.cmd" build
exit /b %errorlevel%
