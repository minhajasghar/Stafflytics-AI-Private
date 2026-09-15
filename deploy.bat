@echo off
echo =========================================
echo   Stafflytics AI - Automated Deployment
echo =========================================

echo.
echo [1/3] Pulling latest code from Git...
git pull origin main

echo.
echo [2/3] Stopping existing backend processes...
taskkill /F /IM python.exe /T >nul 2>&1
taskkill /F /IM wscript.exe /T >nul 2>&1

echo.
echo [3/3] Restarting services...
start "" "start_services_silent.vbs"

echo.
echo Deployment Complete! The backend is now running with the latest code.
echo Please wait about 15 seconds for the AI models to load into memory.
