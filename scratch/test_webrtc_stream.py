import time
import os
import sys
# Make sure we can import from parent directory
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import stream_manager

def main():
    print("=== Testing MediaMTX and FFmpeg downloader & runner ===")
    print(f"Destination BIN_DIR: {stream_manager.BIN_DIR}")
    print(f"MediaMTX Exe Path: {stream_manager.MEDIAMTX_EXE} (Exists: {os.path.exists(stream_manager.MEDIAMTX_EXE)})")
    print(f"FFmpeg Exe Path: {stream_manager.FFMPEG_EXE} (Exists: {os.path.exists(stream_manager.FFMPEG_EXE)})")
    
    print("\nStarting asynchronous binary check/download...")
    stream_manager.ensure_binaries_async()
    
    # Poll status
    for i in range(30):
        print(f"[{i}s] Status: {stream_manager.download_status} (Complete: {stream_manager.download_complete})")
        if stream_manager.download_complete or stream_manager.download_status == "Error":
            break
        time.sleep(2)
        
    if stream_manager.download_status == "Error":
        print(f"\nError occurred: {stream_manager.download_error}")
        return
        
    print("\nVerification complete! Checking if processes can start...")
    stream_manager.start_mediamtx()
    
    time.sleep(3)
    
    # Check if MediaMTX port 8554 is open
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect(('127.0.0.1', 8554))
        print("Success: Connected to MediaMTX RTSP listener on port 8554!")
        s.close()
    except Exception as e:
        print(f"Error: Failed to connect to MediaMTX: {e}")
        
    print("\nStopping MediaMTX...")
    stream_manager.stop_mediamtx()
    print("Done.")

if __name__ == "__main__":
    main()
