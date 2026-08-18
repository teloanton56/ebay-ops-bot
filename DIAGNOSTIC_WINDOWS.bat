@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "OUT=diagnostic.txt"
(
 echo eBay Ops Bot v0.14.3 - Diagnostic
 echo =================================
 echo Date: %date% %time%
 echo Dossier: %cd%
 echo.
 echo --- Python Windows ---
 where python 2^>nul
 python --version 2^>^&1
 echo.
 echo --- Environnement du bot ---
 if exist .venv\Scripts\python.exe (
   .venv\Scripts\python.exe --version 2^>^&1
   .venv\Scripts\python.exe -c "import fastapi,uvicorn,pydantic,httpx; print('Imports OK',fastapi.__version__,uvicorn.__version__,pydantic.__version__)" 2^>^&1
 ) else (
   echo .venv absent
 )
 echo.
 echo --- Port 8765 ---
 netstat -ano ^| findstr ":8765"
 echo.
 echo --- Health ---
 powershell -NoProfile -Command "try { Invoke-RestMethod -Uri 'http://127.0.0.1:8765/health' -TimeoutSec 2 | ConvertTo-Json } catch { $_.Exception.Message }"
 echo.
 echo --- Fichiers importants ---
 if exist .env echo .env OK
 if exist ebay_bot.db echo ebay_bot.db OK
 if exist app\main.py echo app\main.py OK
) > "%OUT%" 2>&1

echo Rapport cree : %cd%\%OUT%
echo Tu peux l'ouvrir et l'envoyer si le bot ne demarre pas.
pause
