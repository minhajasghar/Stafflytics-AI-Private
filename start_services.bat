@echo off
title Stafflytics AI - Streaming, Recording & PTZ Services
cd /d "%~dp0"
echo =========================================================
echo   Stafflytics AI - Unified Streaming, Recording & PTZ
echo =========================================================
echo [1/2] Starting 24/7 Hourly Video Recorder (E:\Stafflytics Recording, Max 850GB)...
start /b python recorder_service.py

echo [2/2] Starting MediaMTX, FFmpeg & PTZ Relay Services...
echo Keep this window open / minimized while streaming.
echo.
cd mediamtx_v1.19.2_windows_amd64
mediamtx.exe
pause
