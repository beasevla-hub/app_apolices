@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (echo Python 3.12+ nao encontrado. Instale em https://www.python.org/downloads/ & pause & exit /b 1)
py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)" >nul 2>nul
if errorlevel 1 (echo Necessario Python 3.12 ou superior. & pause & exit /b 1)
if not exist .venv py -3 -m venv .venv
if errorlevel 1 (echo Falha ao criar ambiente virtual.& pause & exit /b 1)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 (echo Falha ao atualizar pip.& pause & exit /b 1)
pip install -r requirements.txt
if errorlevel 1 (echo Falha ao instalar dependencias.& pause & exit /b 1)
if not exist .env copy .env.example .env
mkdir logs 2>nul
mkdir backups 2>nul
mkdir data\temp 2>nul
mkdir data\historico 2>nul
echo Instalacao concluida. Edite o arquivo .env e preencha as credenciais.
pause
