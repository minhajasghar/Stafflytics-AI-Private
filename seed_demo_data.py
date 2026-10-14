"""
Stafflytics AI - Demo Data Seeder
=================================
Populates the database (MySQL, or the SQLite fallback) with realistic fake data
so every dashboard / report / chart has something to show.

Usage:
    python seed_demo_data.py            # add demo data (keeps existing rows)
    python seed_demo_data.py --reset    # wipe operational tables first, then seed
    python seed_demo_data.py --days 45  # history length (default 30)
"""
import argparse
import pickle
import random
from datetime import datetime, timedelta

import numpy as np

import database

random.seed(42)
np.random.seed(42)

STAFF = [
    # id,      name,              role,                                   shift_start, shift,     rate, salary_type
    ("EMP001", "Minhaj Asghar",   "Co-Founder / AI Solutions Architect",  "09:00", "Morning", 2500, "Monthly"),
    ("EMP002", "Asad Younas",     "Co-Founder / Web Solutions Architect", "09:00", "Morning", 2400, "Monthly"),
    ("EMP003", "Azhar Iqbal",     "Head of Business Development",        "10:00", "Morning", 1800, "Monthly"),
    ("EMP004", "Sultan Mahmood",  "Head of Quality Assurance",           "10:00", "Morning", 1700, "Monthly"),
    ("EMP005", "Zia Younas",      "Electronics Engineer",                "11:00", "Evening", 1200, "Hourly"),
    ("EMP006", "Huzaifa Munir",   "AI Intern",                           "10:00", "Morning",  600, "Hourly"),
    ("EMP007", "Muhammad Hussain", "Manager",                            "09:30", "Morning", 2000, "Monthly"),
]

ZONES = ["Main Entrance", "Office", "Lab", "Workstation", "Main Hall", "Dining Area", "Kitchen"]
TABLES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
GUEST_NAMES = [
    "Ali Raza", "Bilal Ahmed", "Fatima Khan", "Hamza Tariq", "Ayesha Noor", "Usman Ghani",
    "Sana Javed", "Omer Farooq", "Hira Shah", "Kamran Akmal", "Zainab Ali", "Danish Malik",
    "Mehwish Hayat", "Saad Qureshi", "Iqra Aziz", "Fahad Mustafa", "Noor Fatima", "Talha Anjum",
]
EVENTS = [("Eid Celebration", "High"), ("Client Demo Day", "Medium"),
          ("Product Launch", "High"), ("Weekend Rush", "Medium"), ("Investor Visit", "High")]


def fake_encoding():
    """Random unit-length 512-d vector (same pickled format the app stores)."""
    v = np.random.randn(512)
    return pickle.dumps([v / np.linalg.norm(v)])


def ts(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def reset(cur):
    for t in ["sightings", "identity_embeddings", "identities", "visitor_log", "passage_log",
              "sales", "activity_logs", "attendance", "customers", "customer_profiles",
              "special_events", "staff"]:
        try:
            cur.execute(f"DELETE FROM {t}")
        except Exception as e:
            print(f"  skip {t}: {e}")
    cur.execute("UPDATE identity_counters SET next_index = 1")
    print("[RESET] Operational tables cleared.")


def seed(days):
    database.init_db()
    conn = database.get_db_connection()
    cur = conn.cursor()

    if ARGS.reset:
        reset(cur)

    now = datetime.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # ---- Staff -------------------------------------------------------------
    for sid, name, role, start, shift, rate, stype in STAFF:
        cur.execute(
            "INSERT OR REPLACE INTO staff (id, name, role, shift_start, shift, hourly_rate, salary_type, face_encoding, photo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, name, role, start, shift, rate, stype, fake_encoding(), None))
    print(f"[SEED] {len(STAFF)} staff")

    # Per-person personality: punctuality & productivity
    profile = {s[0]: (random.uniform(0.75, 0.97), random.uniform(0.62, 0.92)) for s in STAFF}

    n_att = n_log = n_sales = 0
    for d in range(days, -1, -1):
        day = today - timedelta(days=d)
        if day.weekday() == 6 and d != 0:   # Sundays off (but always seed today)
            continue
        for sid, name, role, start, *_ in STAFF:
            punctual, productive = profile[sid]
            if random.random() < 0.07 and d != 0:   # occasional absence
                continue
            h, m = map(int, start.split(":"))
            shift_dt = day.replace(hour=h, minute=m)
            late = random.random() > punctual
            entry = shift_dt + timedelta(minutes=random.randint(11, 55) if late else random.randint(-20, 8))
            exit_ = entry + timedelta(hours=random.uniform(7.5, 9.5))
            if d == 0:
                if entry > now:
                    continue
                exit_ = min(exit_, now)
            worked = (exit_ - entry).total_seconds()
            active = worked * min(0.97, max(0.4, random.gauss(productive, 0.06)))
            cur.execute(
                "INSERT INTO attendance (staff_id, entry_time, exit_time, status, is_late, active_seconds) VALUES (?, ?, ?, ?, ?, ?)",
                (sid, ts(entry), ts(exit_), "Present", 1 if late else 0, round(active, 2)))
            n_att += 1

            cur.execute("INSERT INTO activity_logs (timestamp, staff_id, zone, action, details) VALUES (?, ?, ?, ?, ?)",
                        (ts(entry), sid, "Main Entrance", "Clock-In", "LATE Arrival" if late else "On-Time"))
            n_log += 1
            for _ in range(random.randint(3, 7)):
                t = entry + timedelta(seconds=random.uniform(0, worked))
                z = random.choice(ZONES[1:])
                action, details = random.choice([
                    ("Zone Entry", f"Entered {z}"),
                    ("Active Work", "Productive activity detected"),
                    ("Break", "Idle > 10 min"),
                    ("Phone Usage", "Mobile phone detected"),
                ])
                cur.execute("INSERT INTO activity_logs (timestamp, staff_id, zone, action, details) VALUES (?, ?, ?, ?, ?)",
                            (ts(t), sid, z, action, details))
                n_log += 1
            if random.random() < 0.08:
                t = entry + timedelta(seconds=random.uniform(0, worked))
                cur.execute("INSERT INTO activity_logs (timestamp, staff_id, zone, action, details) VALUES (?, ?, ?, ?, ?)",
                            (ts(t), sid, "Kitchen", "Security Alert", f"Unauthorized zone access by {name}"))
                n_log += 1
            if exit_ < now:
                cur.execute("INSERT INTO activity_logs (timestamp, staff_id, zone, action, details) VALUES (?, ?, ?, ?, ?)",
                            (ts(exit_), sid, "Main Entrance", "Clock-Out", f"Worked {worked/3600:.1f} h"))
                n_log += 1

            for _ in range(random.randint(2, 9)):
                t = entry + timedelta(seconds=random.uniform(0, worked))
                cur.execute("INSERT INTO sales (staff_id, amount, timestamp) VALUES (?, ?, ?)",
                            (sid, round(random.uniform(450, 6500), 2), ts(t)))
                n_sales += 1
    print(f"[SEED] {n_att} attendance, {n_log} activity logs, {n_sales} sales")

    # ---- Customer profiles -------------------------------------------------
    profile_ids = []
    for gname in GUEST_NAMES:
        first = today - timedelta(days=random.randint(5, days), hours=-random.randint(11, 21))
        last = today - timedelta(days=random.randint(0, 4), hours=-random.randint(11, 21))
        last = min(last, now)
        cur.execute("INSERT INTO customer_profiles (name, face_encoding, first_seen, last_seen, visit_count, photo) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (gname, fake_encoding(), ts(first), ts(last), random.randint(2, 18), None))
        profile_ids.append(cur.lastrowid)
    print(f"[SEED] {len(profile_ids)} customer profiles")

    # ---- Customer sessions, visitor log, passage log -----------------------
    n_cust = n_vis = n_pass = 0
    for d in range(days, -1, -1):
        day = today - timedelta(days=d)
        busy = 1.6 if day.weekday() in (4, 5) else 1.0
        for _ in range(int(random.randint(18, 40) * busy)):
            peak = random.choice([13, 14, 19, 20, 21, random.randint(11, 22)])
            entry = day.replace(hour=peak, minute=random.randint(0, 59), second=random.randint(0, 59))
            if entry > now:
                continue
            dur = max(8.0, random.gauss(42, 15))
            exit_ = min(entry + timedelta(minutes=dur), now)
            dur = (exit_ - entry).total_seconds() / 60
            known = random.random() < 0.35
            cid = random.choice(profile_ids) if known else None
            cur.execute("INSERT INTO customers (entry_time, exit_time, table_id, duration_minutes, customer_id) VALUES (?, ?, ?, ?, ?)",
                        (ts(entry), ts(exit_), random.choice(TABLES), round(dur, 1), cid))
            n_cust += 1
            cur.execute("INSERT INTO visitor_log (timestamp, customer_id, is_new_face, staff_id, zone) VALUES (?, ?, ?, ?, ?)",
                        (ts(entry), cid, 0 if known else 1, random.choice(STAFF)[0], "Dining Area"))
            n_vis += 1
        for _ in range(random.randint(40, 90)):
            t = day.replace(hour=random.randint(9, 22), minute=random.randint(0, 59), second=random.randint(0, 59))
            if t > now:
                continue
            cur.execute("INSERT INTO passage_log (timestamp, direction, track_id) VALUES (?, ?, ?)",
                        (ts(t), random.choice(["l_to_r", "r_to_l"]), random.randint(1, 5000)))
            n_pass += 1
    print(f"[SEED] {n_cust} customer sessions, {n_vis} visitor logs, {n_pass} passages")

    # ---- Special events (past + upcoming) ----------------------------------
    for off in (-21, -10, -3, 4, 12):
        ev, inten = random.choice(EVENTS)
        cur.execute("INSERT OR IGNORE INTO special_events (date, event_type, intensity) VALUES (?, ?, ?)",
                    ((today + timedelta(days=off)).strftime("%Y-%m-%d"), ev, inten))
    print("[SEED] 5 special events")

    conn.commit()
    conn.close()
    print("\nDone! Restart the app so the AI engine reloads staff identities.")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="Clear operational tables before seeding")
    p.add_argument("--days", type=int, default=30, help="Days of history to generate")
    ARGS = p.parse_args()
    seed(ARGS.days)
