Set WshShell = CreateObject("WScript.Shell")

' --- 1. Start MediaMTX (RTSP Server) ---
WshShell.CurrentDirectory = "C:\Users\admin\Desktop\TNT Innov Projects\stafflytics-ai\mediamtx_v1.19.2_windows_amd64"
WshShell.Run "mediamtx.exe", 0, False

' Give MediaMTX 2 seconds to start before other services
WScript.Sleep 2000

' --- 2. Start PTZ Relay Service (port 5001) ---
WshShell.CurrentDirectory = "C:\Users\admin\Desktop\TNT Innov Projects\stafflytics-ai"
WshShell.Run "py -3.12 ptz_relay.py", 0, False

' --- 3. Start 24/7 Camera Recorder (E:\Stafflytics Recording, max 850GB FIFO) ---
WshShell.CurrentDirectory = "C:\Users\admin\Desktop\TNT Innov Projects\stafflytics-ai"
WshShell.Run "py -3.12 recorder_service.py", 0, False

' --- 4. Start Main Stafflytics AI App (port 5001) ---
WshShell.CurrentDirectory = "C:\Users\admin\Desktop\TNT Innov Projects\stafflytics-ai"
WshShell.Run "py -3.12 app.py", 0, False

Set WshShell = Nothing
