@echo off
title Stafflytics AI - All Services
cd /d "%~dp0"
echo =========================================================
echo   Stafflytics AI - Starting All Services
echo =========================================================

echo [1/4] Starting MediaMTX RTSP Server...
start /b /d "%~dp0mediamtx_v1.19.2_windows_amd64" mediamtx.exe
timeout /t 2 /nobreak >nul

echo [2/4] Starting PTZ Relay Service...
start /b py -3.12 ptz_relay.py

echo [3/4] Starting 24/7 Video Recorder (E:\Stafflytics Recording, 850GB limit)...
start /b py -3.12 recorder_service.py

echo [4/4] Starting Stafflytics AI Main App...
start /b py -3.12 app.py

echo.
echo =========================================================
echo   All services started! Keep this window open.
echo   Main App:  http://localhost:5050
echo   Recording: E:\Stafflytics Recording
echo =========================================================
echo.
pause
