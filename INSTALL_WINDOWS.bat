@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title eBay Ops Bot v0.14.2 - Installation

echo ==========================================================
echo   eBay Ops Bot v0.14.2 - Installation / reparation
echo ==========================================================
echo.

set "PYTHON_CMD="
where python >nul 2>nul && set "PYTHON_CMD=python"
if not defined PYTHON_CMD (where py >nul 2>nul && set "PYTHON_CMD=py")
if not defined PYTHON_CMD goto :python_missing

%PYTHON_CMD% --version
if errorlevel 1 goto :python_missing

echo.
echo [1/5] Preparation de l'environnement Python...
if not exist .venv\Scripts\python.exe (
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :fail
) else (
  echo       Environnement existant detecte.
)

echo [2/5] Mise a jour de l'outil d'installation...
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel --disable-pip-version-check
if errorlevel 1 goto :fail

echo [3/5] Installation / verification des dependances...
.venv\Scripts\python.exe -m pip install -r requirements.txt --disable-pip-version-check
if errorlevel 1 goto :fail

echo [4/5] Verification technique...
.venv\Scripts\python.exe -c "import fastapi,uvicorn,pydantic,httpx,jinja2,cryptography; print('OK - dependances chargees')"
if errorlevel 1 goto :fail

echo [5/5] Preparation de la configuration locale...
.venv\Scripts\python.exe -m app.services.local_migration
if not exist .env copy .env.example .env >nul
.venv\Scripts\python.exe -c "from pathlib import Path; from cryptography.fernet import Fernet; p=Path('.env'); s=p.read_text(encoding='utf-8'); s='\n'.join(x for x in s.splitlines() if not x.startswith('BIGBUY_'))+'\n'; key=Fernet.generate_key().decode(); s=s.replace('APP_ENCRYPTION_KEY=\n','APP_ENCRYPTION_KEY='+key+'\n',1) if 'APP_ENCRYPTION_KEY=\n' in s else s; p.write_text(s,encoding='utf-8')" >nul 2>nul

echo.
echo ==========================================================
echo   INSTALLATION OK
echo   Tu peux lancer LANCER_BOT.bat
echo ==========================================================
exit /b 0

:python_missing
echo.
echo [ERREUR] Python n'est pas accessible depuis Windows.
echo Ouvre CMD puis tape : python --version
echo Python 3.11 ou plus recent est recommande.
echo.
pause
exit /b 1

:fail
echo.
echo ==========================================================
echo   INSTALLATION INCOMPLETE
echo   Lance DIAGNOSTIC_WINDOWS.bat puis envoie diagnostic.txt.
echo ==========================================================
pause
exit /b 1
