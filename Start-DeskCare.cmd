@echo off
setlocal
if not exist "%~dp0dist\DeskCare-UI20\DeskCare-UI20.exe" (
    echo DeskCare UI20 is not built in this checkout.
    pause
    exit /b 1
)
start "" "%~dp0dist\DeskCare-UI20\DeskCare-UI20.exe"
