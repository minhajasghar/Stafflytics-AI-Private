import sys
sys.path.append('.')
import database

new_url = "rtsp://admin:L2DD2594@192.168.1.108:554/cam/realmonitor?channel=1&subtype=1"
print(f"Updating database rtsp_url to: {new_url}")

try:
    database.update_system_settings({"rtsp_url": new_url})
    print("SUCCESS: Database updated successfully!")
except Exception as e:
    print(f"ERROR updating database: {e}")
