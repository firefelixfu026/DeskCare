@echo off
setlocal
if not exist "%~dp0dist\DeskCare-UI19\DeskCare-UI19.exe" (
    echo DeskCare UI19 is not built in this checkout.
    pause
    exit /b 1
)
start "" "%~dp0dist\DeskCare-UI19\DeskCare-UI19.exe"
