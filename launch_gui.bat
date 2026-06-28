@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" launcher.py
) else (
    echo No existe .venv\Scripts\python.exe
    echo Ejecuta primero:
    echo python -m venv .venv
    echo .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)
if errorlevel 1 (
    echo.
    echo El launcher fallo. Revisa el mensaje anterior.
    pause
)
