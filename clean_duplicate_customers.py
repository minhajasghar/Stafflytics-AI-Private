import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, "stafflytics_db.sqlite")

def clean_duplicate_customers():
    """
    Purges all duplicate and spurious Customer IDs minted during testing,
    while strictly preserving staff enrollments and system settings.
    Resets the customer sequence counter to 1.
    """
    print(f"[CLEANUP] Connecting to database: {db_path}")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    try:
        # 1. Count current customers
        c.execute("SELECT COUNT(*) FROM identities WHERE type = 'customer'")
        cust_identities_cnt = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM customers")
        customers_cnt = c.fetchone()[0]

        print(f"[CLEANUP] Found {cust_identities_cnt} customer identities and {customers_cnt} customer records.")

        # 2. Delete customer embeddings
        c.execute("""
            DELETE FROM identity_embeddings 
            WHERE identity_id IN (SELECT id FROM identities WHERE type = 'customer')
        """)
        del_embs = c.rowcount
        print(f"[CLEANUP] Deleted {del_embs} customer embeddings.")

        # 3. Delete customer identities
        c.execute("DELETE FROM identities WHERE type = 'customer'")
        print(f"[CLEANUP] Deleted {c.rowcount} customer identities.")

        # 4. Delete anonymous customer sessions
        c.execute("DELETE FROM customers")
        c.execute("DELETE FROM customer_profiles")
        c.execute("DELETE FROM visitor_log WHERE customer_id IS NOT NULL")
        print(f"[CLEANUP] Cleared anonymous customer sessions and visitor logs.")

        # 5. Reset customer counter back to 1
        c.execute("UPDATE identity_counters SET next_index = 1 WHERE type = 'customer'")
        print("[CLEANUP] Reset customer counter next_index = 1.")

        conn.commit()

        # 6. Verify preserved staff
        c.execute("SELECT id, name, role FROM staff")
        staff_rows = c.fetchall()
        print(f"\n[CLEANUP SUCCESS] Preserved {len(staff_rows)} staff members:")
        for s in staff_rows:
            print(f"  - Staff ID: {s[0]}, Name: {s[1]}, Role: {s[2]}")

        # Verify identities
        c.execute("SELECT id, type, label FROM identities")
        preserved_identities = c.fetchall()
        print(f"\n[CLEANUP SUCCESS] Preserved {len(preserved_identities)} identities:")
        for pi in preserved_identities:
            print(f"  - {pi[0]} ({pi[1]}): {pi[2]}")

        conn.close()
        return {
            "deleted_customers": cust_identities_cnt,
            "deleted_embeddings": del_embs,
            "preserved_staff": len(staff_rows),
            "status": "success"
        }

    except Exception as e:
        print(f"[CLEANUP ERROR] {e}")
        conn.rollback()
        conn.close()
        return {"status": "error", "message": str(e)}

clean_spurious_customers = clean_duplicate_customers

if __name__ == "__main__":
    clean_duplicate_customers()

