@echo off
title Stafflytics Streaming & PTZ Relay Services
cd /d "%~dp0"
echo =========================================================
echo   Stafflytics AI - Unified Streaming & PTZ Relay Runner
echo =========================================================
echo Starting MediaMTX, FFmpeg HD Transcoder & PTZ Relay concurrently...
echo Keep this window minimized while running.
echo.
cd mediamtx_v1.19.2_windows_amd64
mediamtx.exe
pause
