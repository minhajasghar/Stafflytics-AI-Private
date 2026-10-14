@echo off
title Stafflytics AI - Continuous Edge YOLO Worker
cd /d "%~dp0"

echo =========================================================
echo   Stafflytics AI - Continuous Edge YOLO Worker
echo =========================================================
echo Starting continuous YOLO vision worker with auto-restart.
echo Press Ctrl+C in this window to stop.
echo.

:loop
echo [%date% %time%] Starting YOLO Vision Worker...
py -3.12 edge_ai_worker.py --source rtsp://100.93.176.107:8554/cam --server http://localhost:5050 --fps 20
echo [%date% %time%] Worker stopped or disconnected. Auto-restarting in 5 seconds...
timeout /t 5 /nobreak >nul
goto loop
