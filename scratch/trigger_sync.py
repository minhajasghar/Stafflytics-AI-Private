import sys
sys.path.append('.')
import database
import app
import os

print("Initializing DB...")
database.init_db()

print("Triggering sync_camera_config()...")
app.sync_camera_config()

config_path = os.path.join("bin", "mediamtx.yml")
print(f"\nChecking contents of {config_path}:")
if os.path.exists(config_path):
    with open(config_path, "r", encoding="utf-8") as f:
        print(f.read())
else:
    print("ERROR: Config file does not exist!")
