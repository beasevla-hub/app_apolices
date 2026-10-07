@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (echo Python 3.12+ nao encontrado. Instale em https://www.python.org/downloads/ & pause & exit /b 1)
py -3.12 --version >nul 2>nul
if errorlevel 1 (echo Necessario Python 3.12+. & pause & exit /b 1)
if not exist .venv py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if not exist .env copy .env.example .env
mkdir logs 2>nul
mkdir backups 2>nul
mkdir data\temp 2>nul
echo Instalacao concluida. Edite o arquivo .env e preencha as credenciais.
pause
