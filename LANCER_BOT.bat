@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title eBay Ops Bot v0.14.0

set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%"

echo ==========================================================
echo   eBay Ops Bot v0.14.0
echo ==========================================================
echo.

if not exist .venv\Scripts\python.exe (
  echo Premiere utilisation : installation automatique...
  call INSTALL_WINDOWS.bat
  if errorlevel 1 exit /b 1
)

.venv\Scripts\python.exe -c "import uvicorn,fastapi,pydantic" >nul 2>nul
if errorlevel 1 (
  echo Dependances manquantes : reparation automatique...
  call INSTALL_WINDOWS.bat
  if errorlevel 1 exit /b 1
)

rem Si la meme version tourne deja, on ouvre simplement le dashboard.
set "RUNNING_VERSION="
for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "try { (Invoke-RestMethod -Uri '%URL%/health' -TimeoutSec 1).version } catch { '' }"`) do set "RUNNING_VERSION=%%V"
if "%RUNNING_VERSION%"=="0.14.0" (
  echo Le bot est deja lance. Ouverture du dashboard...
  start "" "%URL%"
  exit /b 0
)

rem Une ancienne version du bot sur le meme port est arretee automatiquement.
if defined RUNNING_VERSION (
  echo Ancienne version detectee : v%RUNNING_VERSION%. Arret en cours...
  powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %PORT% -State Listen -ErrorAction SilentlyContinue; if($c){Stop-Process -Id $c.OwningProcess -Force}" >nul 2>nul
  timeout /t 2 /nobreak >nul
)

rem Le navigateur attend maintenant que le serveur reponde vraiment.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$u='%URL%/health'; for($i=0;$i -lt 60;$i++){try{$r=Invoke-RestMethod -Uri $u -TimeoutSec 1;if($r.version -eq '0.14.0'){Start-Process '%URL%';exit}}catch{};Start-Sleep -Milliseconds 500}"

echo Demarrage du serveur local...
echo Adresse : %URL%
echo.
echo IMPORTANT : garde cette fenetre ouverte pendant l'utilisation.
echo Pour arreter le bot : ferme cette fenetre ou appuie sur CTRL+C.
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%

if errorlevel 1 (
  echo.
  echo [ERREUR] Le serveur s'est arrete.
  echo Lance DIAGNOSTIC_WINDOWS.bat pour generer un rapport simple.
  pause
)
