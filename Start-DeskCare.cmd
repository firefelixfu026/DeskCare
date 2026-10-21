@echo off
setlocal
if not exist "%~dp0dist\DeskCare-UI16\DeskCare-UI16.exe" (
    echo DeskCare UI16 is not built in this checkout.
    pause
    exit /b 1
)
start "" "%~dp0dist\DeskCare-UI16\DeskCare-UI16.exe"
