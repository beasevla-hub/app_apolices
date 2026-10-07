@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (echo Execute instalar.bat primeiro.& exit /b 1)
.venv\Scripts\python.exe -m app.main --dry-run
