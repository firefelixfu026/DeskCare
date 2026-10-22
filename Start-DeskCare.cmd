@echo off
setlocal
if not exist "%~dp0dist\DeskCare-UI18\DeskCare-UI18.exe" (
    echo DeskCare UI18 is not built in this checkout.
    pause
    exit /b 1
)
start "" "%~dp0dist\DeskCare-UI18\DeskCare-UI18.exe"
