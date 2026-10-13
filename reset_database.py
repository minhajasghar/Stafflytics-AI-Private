import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "stafflytics_db.sqlite")

conn = sqlite3.connect(db_path)
c = conn.cursor()

tables_to_clear = [
    'staff', 'attendance', 'activity_logs', 'customers', 
    'customer_profiles', 'special_events', 'sales', 
    'visitor_log', 'passage_log', 'identities', 
    'identity_embeddings', 'sightings'
]

for t in tables_to_clear:
    try:
        c.execute(f"DELETE FROM {t}")
        print(f"Cleared table: {t}")
    except Exception as e:
        print(f"Error clearing {t}: {e}")

try:
    c.execute("DELETE FROM identity_counters")
    c.execute("INSERT OR REPLACE INTO identity_counters (type, next_index) VALUES ('staff', 1)")
    c.execute("INSERT OR REPLACE INTO identity_counters (type, next_index) VALUES ('customer', 1)")
    print("Reset identity_counters to staff=1, customer=1")
except Exception as e:
    print(f"Error resetting identity_counters: {e}")

try:
    c.execute("DELETE FROM sqlite_sequence WHERE name IN (" + ",".join([f"'{t}'" for t in tables_to_clear]) + ")")
except Exception as e:
    print(f"Error clearing sqlite_sequence: {e}")

conn.commit()

print("\n--- Current Table Counts ---")
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
for row in c.fetchall():
    tname = row[0]
    count = c.execute(f"SELECT count(*) FROM {tname}").fetchone()[0]
    print(f"{tname}: {count}")

conn.close()
print("\nDatabase reset complete! You can now enroll staff and test from scratch.")
