@echo off
setlocal
if not exist "%~dp0dist\DeskCare-UI17\DeskCare-UI17.exe" (
    echo DeskCare UI17 is not built in this checkout.
    pause
    exit /b 1
)
start "" "%~dp0dist\DeskCare-UI17\DeskCare-UI17.exe"
