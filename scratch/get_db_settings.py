import sys
sys.path.append('.')
import database

try:
    conf = database.get_system_settings()
    print("Database Settings:")
    for k, v in conf.items():
        print(f"  {k}: {v}")
except Exception as e:
    print(f"ERROR: {e}")
