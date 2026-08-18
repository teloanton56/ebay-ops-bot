@echo off
setlocal
cd /d "%~dp0"
echo Reparation de l'environnement Python du bot.
echo Les produits, la base locale et les reglages .env ne seront pas supprimes.
echo.
if exist .venv rmdir /s /q .venv
call INSTALL_WINDOWS.bat
pause
