Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\admin\Desktop\TNT Innov Projects\stafflytics-ai\mediamtx_v1.19.2_windows_amd64"
WshShell.Run "mediamtx.exe", 0, False
Set WshShell = Nothing
