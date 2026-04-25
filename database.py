import sqlite3
import threading
import os
from datetime import datetime, timedelta

# Use RLock to prevent deadlocks when functions call each other
db_lock = threading.RLock()

DB_PATH = "data/stafflytics.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 10000;")
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    if not os.path.exists("data"):
        os.makedirs("data")
        
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Staff table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT NOT NULL,
            shift_start TEXT DEFAULT '10:00',
            shift TEXT DEFAULT 'Morning',
            hourly_rate REAL DEFAULT 500.0,
            salary_type TEXT DEFAULT 'Monthly',
            face_encoding BLOB NOT NULL
        )
        ''')
        
        # Migration: Add salary_type if not exists
        cursor.execute("PRAGMA table_info(staff)")
        cols = [c[1] for c in cursor.fetchall()]
        if 'salary_type' not in cols:
            cursor.execute("ALTER TABLE staff ADD COLUMN salary_type TEXT DEFAULT 'Monthly'")

        # Attendance table
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id TEXT,
            entry_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            exit_time DATETIME,
            status TEXT DEFAULT 'Present',
            is_late BOOLEAN DEFAULT 0,
            active_seconds REAL DEFAULT 0,
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        )
        ''')
        
        # Migration: Ensure active_seconds is REAL
        cursor.execute("PRAGMA table_info(attendance)")
        info = cursor.fetchall()
        for col in info:
            if col[1] == 'active_seconds' and col[2] == 'INTEGER':
                # SQLite doesn't support changing type easily, but it handles REAL in INTEGER columns loosely.
                # However, for clarity, we'll keep it as is or just rely on dynamic typing.
                # Actually, let's just make sure we are adding floats. 
                pass

        # Activity logs
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            staff_id TEXT,
            zone TEXT,
            action TEXT,
            details TEXT,
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        )
        ''')

        # Admins
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            email TEXT
        )
        ''')
        cursor.execute("SELECT COUNT(*) FROM admins")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO admins (username, password, email) VALUES (?, ?, ?)", 
                           ("minhajasghar", "minhajsahito66", "admin@stafflytics.ai"))

        # Customers (Anonymous Sessions)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            exit_time DATETIME,
            table_id TEXT,
            duration_minutes INTEGER,
            customer_id INTEGER
        )
        ''')
        
        # Migration: Add customer_id if not exists
        cursor.execute("PRAGMA table_info(customers)")
        if 'customer_id' not in [c[1] for c in cursor.fetchall()]:
            cursor.execute("ALTER TABLE customers ADD COLUMN customer_id INTEGER")

        # Customer Profiles (Recognized Individuals)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS customer_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT DEFAULT 'New Guest',
            face_encoding BLOB NOT NULL,
            first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
            visit_count INTEGER DEFAULT 1
        )
        ''')

        # Special Events & Peak Traffic
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS special_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE UNIQUE,
            event_type TEXT DEFAULT 'General Peak',
            intensity TEXT DEFAULT 'High'
        )
        ''')

        # Zones Config
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS zones_config (
            name TEXT PRIMARY KEY,
            points_json TEXT NOT NULL,
            unauthorized_roles TEXT
        )
        ''')
        
        # Sales Tracking
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id TEXT,
            amount REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (staff_id) REFERENCES staff(id)
        )
        ''')

        # System Settings
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        ''')
        
        # Initialize default settings if not exists
        defaults = [
            ('owner_email', 'admin@stafflytics.ai'),
            ('sender_email', ''),
            ('sender_password', ''),
            ('telegram_bot_token', ''),
            ('telegram_chat_id', '')
        ]
        for key, val in defaults:
            cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (key, val))

        conn.commit()
        conn.close()

# --- OWNER MANAGEMENT (CRUD) ---

def add_staff(staff_id, name, role, encoding, shift_start='10:00', shift='Morning', hourly_rate=500, salary_type='Monthly'):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO staff (id, name, role, shift_start, shift, hourly_rate, salary_type, face_encoding) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                       (staff_id, name, role, shift_start, shift, hourly_rate, salary_type, encoding))
        conn.commit()
        conn.close()

def delete_staff(staff_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM staff WHERE id = ?", (staff_id,))
        conn.commit()
        conn.close()

def update_staff(staff_id, name, role, shift_time, shift_name, rate, salary_type='Monthly'):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE staff SET name=?, role=?, shift_start=?, shift=?, hourly_rate=?, salary_type=? WHERE id=?", 
                       (name, role, shift_time, shift_name, rate, salary_type, staff_id))
        conn.commit()
        conn.close()

def get_all_staff():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, role, shift_start, hourly_rate, face_encoding, shift, salary_type FROM staff")
        rows = cursor.fetchall()
        conn.close()
        return rows

# --- EVENT & PEAK TRAFFIC MANAGEMENT ---

def add_event(date_str, event_type="Peak Day", intensity="High"):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO special_events (date, event_type, intensity) VALUES (?, ?, ?)", (date_str, event_type, intensity))
        conn.commit()
        conn.close()

def get_events():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT date, event_type, intensity FROM special_events ORDER BY date ASC")
        rows = cursor.fetchall()
        conn.close()
        return rows

def delete_event(date_str):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM special_events WHERE date = ?", (date_str,))
        conn.commit()
        conn.close()

# --- INTELLIGENCE AGGREGATORS ---

def get_staff_reliability_ranking():
    """Finds most reliable staff (lowest late arrival percentage)"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.name, 
                   COUNT(a.id) as total_days,
                   SUM(a.is_late) as late_days,
                   (1.0 - (CAST(SUM(a.is_late) AS REAL) / COUNT(a.id))) * 100 as reliability_pct
            FROM staff s 
            JOIN attendance a ON s.id = a.staff_id
            GROUP BY s.id
            HAVING total_days > 0
            ORDER BY reliability_pct DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows

def get_comprehensive_summary(date_str=None):
    """Generates a full business report for a specific date"""
    if not date_str: date_str = "date('now', 'localtime')"
    else: date_str = f"'{date_str}'"
    
    with db_lock:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # 1. Staff Stats
        cursor.execute(f"""
            SELECT COUNT(DISTINCT staff_id), SUM(is_late) 
            FROM attendance WHERE date(entry_time, 'localtime') = {date_str}
        """)
        s_stats = cursor.fetchone()
        
        # 2. Customer Stats
        cursor.execute(f"SELECT COUNT(*), AVG(duration_minutes) FROM customers WHERE date(entry_time, 'localtime') = {date_str}")
        c_stats = cursor.fetchone()
        
        conn.close()
        return {
            "staff_present": s_stats[0] or 0,
            "late_count": s_stats[1] or 0,
            "customers": c_stats[0] or 0,
            "avg_stay": round(c_stats[1] or 0, 1)
        }

# --- CORE LOGIC ---

def log_activity(staff_id, zone, action, details=""):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO activity_logs (staff_id, zone, action, details) VALUES (?, ?, ?, ?)", 
                       (staff_id, zone, action, details))
        conn.commit()
        conn.close()

def get_recent_logs():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.timestamp, s.name, l.zone, l.action, l.details 
            FROM activity_logs l 
            JOIN staff s ON l.staff_id = s.id 
            ORDER BY l.timestamp DESC LIMIT 10
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows

def get_latest_security_logs():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT l.id, l.timestamp, l.staff_id, l.zone, l.action, l.details, s.name, s.role 
            FROM activity_logs l 
            JOIN staff s ON l.staff_id = s.id 
            WHERE l.action LIKE '%Alert%'
            ORDER BY l.timestamp DESC LIMIT 10
        """)
        rows = cursor.fetchall()
        conn.close()
        return rows

def record_attendance(staff_id):
    """Records attendance: Entry on first sighting, keeps updating Exit on subsequent sightings"""
    with db_lock:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Look for ANY record for this staff member TODAY
            cursor.execute("""
                SELECT id FROM attendance 
                WHERE staff_id = ? AND date(entry_time, 'localtime') = date('now', 'localtime') 
                ORDER BY entry_time ASC LIMIT 1
            """, (staff_id,))
            record = cursor.fetchone()
            
            if not record:
                # First time seeing them today
                cursor.execute("SELECT shift_start FROM staff WHERE id = ?", (staff_id,))
                res = cursor.fetchone()
                shift_start = res[0] if res else "10:00"
                
                # Compare time safely
                cursor.execute("SELECT time('now', 'localtime') > time(?)", (shift_start,))
                is_late = cursor.fetchone()[0] # No holiday exemption anymore

                # Entry and Exit both initialized to now
                cursor.execute("INSERT INTO attendance (staff_id, entry_time, exit_time, is_late) VALUES (?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, ?)", (staff_id, is_late))
                log_details = "LATE Arrival" if is_late else "On-Time"
                cursor.execute("INSERT INTO activity_logs (staff_id, zone, action, details) VALUES (?, ?, ?, ?)", 
                               (staff_id, "Main Entrance", "Clock-In", log_details))
                print(f"[AI TRACKER] Clocked-In: {staff_id} ({log_details})")
            else:
                # Still here today, update Last Seen (exit_time)
                cursor.execute("UPDATE attendance SET exit_time = CURRENT_TIMESTAMP WHERE id = ?", (record[0],))
            
            conn.commit()
            conn.close()
        except Exception as e: 
            print(f"[DB ERROR] record_attendance for {staff_id}: {e}")
            pass

def update_active_time(staff_id, seconds):
    with db_lock:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE attendance SET active_seconds = active_seconds + ? 
                WHERE staff_id = ? AND date(entry_time, 'localtime') = date('now', 'localtime')
                ORDER BY entry_time DESC LIMIT 1
            """, (seconds, staff_id))
            conn.commit()
            conn.close()
        except: pass

def get_staff_stats(staff_id):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(CASE WHEN exit_time IS NOT NULL 
                            THEN (strftime('%s', exit_time, 'localtime') - strftime('%s', entry_time, 'localtime'))
                            ELSE (strftime('%s', 'now', 'localtime') - strftime('%s', entry_time, 'localtime')) END) / 3600.0,
                   COUNT(DISTINCT date(entry_time, 'localtime'))
            FROM attendance 
            WHERE staff_id = ? 
              AND strftime('%m', entry_time, 'localtime') = strftime('%m', 'now', 'localtime')
        """, (staff_id,))
        res = cursor.fetchone()
        conn.close()
        return {"hours": round(res[0] or 0, 1), "days": res[1] or 0}

def get_dashboard_summary():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Average Team Efficiency Today
        cursor.execute("""
            SELECT AVG(CAST(active_seconds AS REAL) / 
                       CASE WHEN exit_time IS NOT NULL 
                            THEN MAX(1, (strftime('%s', exit_time, 'localtime') - strftime('%s', entry_time, 'localtime'))) 
                            ELSE MAX(1, (strftime('%s', 'now', 'localtime') - strftime('%s', entry_time, 'localtime'))) END) * 100
            FROM attendance 
            WHERE date(entry_time, 'localtime') = date('now', 'localtime')
        """)
        avg_efficiency = cursor.fetchone()[0] or 0
        
        # Today's Stats
        cursor.execute("""
            SELECT SUM(a.is_late), COUNT(*)
            FROM attendance a WHERE date(a.entry_time, 'localtime') = date('now', 'localtime')
        """)
        res = cursor.fetchone()
        lates = res[0] or 0
        present = res[1] or 0
        
        cursor.execute("SELECT COUNT(*) FROM activity_logs WHERE action LIKE '%Alert%' AND date(timestamp, 'localtime') = date('now', 'localtime')")
        incidents = cursor.fetchone()[0] or 0
        conn.close()
        return {"avg_efficiency": round(avg_efficiency, 1), "present_today": present, "late_today": lates, "incidents_today": incidents}

def get_comprehensive_summary():
    """Returns a full summary for PDF/Excel reporting"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Staff Present Today
        cursor.execute("SELECT COUNT(DISTINCT staff_id) FROM attendance WHERE date(entry_time, 'localtime') = date('now', 'localtime')")
        present = cursor.fetchone()[0] or 0
        
        # Average Efficiency Today
        cursor.execute("""
            SELECT AVG(CAST(active_seconds AS REAL) / 
                       CASE WHEN exit_time IS NOT NULL 
                            THEN MAX(1, (strftime('%s', exit_time, 'localtime') - strftime('%s', entry_time, 'localtime'))) 
                            ELSE MAX(1, (strftime('%s', 'now', 'localtime') - strftime('%s', entry_time, 'localtime'))) END) * 100
            FROM attendance WHERE date(entry_time, 'localtime') = date('now', 'localtime')
        """)
        efficiency = cursor.fetchone()[0] or 0
        
        # Customer Stats Today
        cursor.execute("SELECT COUNT(*), AVG(duration_minutes) FROM customers WHERE date(exit_time, 'localtime') = date('now', 'localtime')")
        c_stats = cursor.fetchone()
        
        conn.close()
        return {
            "staff_present": present,
            "avg_efficiency": round(efficiency, 1),
            "customers": c_stats[0] or 0,
            "avg_stay": round(c_stats[1] or 0, 1)
        }

def get_performance_rankings():
    """Calculates efficiency score: (Active Seconds / Total Worked Seconds) * 100"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.name, s.role,
                   SUM(CASE WHEN a.exit_time IS NOT NULL 
                            THEN (strftime('%s', a.exit_time, 'localtime') - strftime('%s', a.entry_time, 'localtime'))
                            ELSE (strftime('%s', 'now', 'localtime') - strftime('%s', a.entry_time, 'localtime')) END) as total_sec,
                   SUM(a.active_seconds) as active_sec
            FROM staff s
            JOIN attendance a ON s.id = a.staff_id
            WHERE strftime('%m', a.entry_time, 'localtime') = strftime('%m', 'now', 'localtime')
            GROUP BY s.id
            HAVING total_sec > 0
            ORDER BY (CAST(active_sec AS REAL) / total_sec) DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"name":r[0], "role":r[1], "score": round(((r[3] or 0)/(r[2] or 1)*100), 1) if (r[2] or 0)>0 else 0} for r in rows]

def get_monthly_attendance(month=None, year=None):
    if not month: month = "strftime('%m', 'now', 'localtime')"
    else: month = f"'{str(month).zfill(2)}'"
    if not year: year = "strftime('%Y', 'now', 'localtime')"
    else: year = f"'{str(year)}'"
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = f"""
            SELECT a.entry_time, a.exit_time, s.name, s.role,
                   (CASE WHEN a.exit_time IS NOT NULL 
                         THEN (strftime('%s', a.exit_time, 'localtime') - strftime('%s', a.entry_time, 'localtime')) 
                         ELSE (strftime('%s', 'now', 'localtime') - strftime('%s', a.entry_time, 'localtime')) END) / 3600.0,
                   s.salary_type, a.is_late, a.active_seconds
            FROM attendance a JOIN staff s ON a.staff_id = s.id
            WHERE strftime('%m', a.entry_time, 'localtime') = {month}
              AND strftime('%Y', a.entry_time, 'localtime') = {year}
            ORDER BY a.entry_time DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        return rows

def get_staff_latest_locations():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT s.id, s.name, s.role, l.zone, l.timestamp
            FROM staff s LEFT JOIN activity_logs l ON s.id = l.staff_id
            WHERE l.id = (SELECT MAX(id) FROM activity_logs WHERE staff_id = s.id)
            OR l.id IS NULL
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        return [{"id":r[0], "name":r[1], "role":r[2], "zone":r[3] or "Not Seen", "time":r[4] or ""} for r in rows]

def get_customer_stats():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT AVG(duration_minutes), COUNT(*) FROM customers WHERE date(entry_time, 'localtime') = date('now', 'localtime')")
        r = cursor.fetchone()
        
        # Total Repeating Customers this month
        cursor.execute("""
            SELECT COUNT(*) FROM customer_profiles 
            WHERE visit_count > 1 
              AND strftime('%m', last_seen, 'localtime') = strftime('%m', 'now', 'localtime')
        """)
        repeat_count = cursor.fetchone()[0] or 0
        
        conn.close()
        return {"avg_stay": round(r[0] or 0, 1), "total_customers": r[1] or 0, "repeat_customers": repeat_count}

def record_customer_session(table_id, duration, customer_id=None):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO customers (table_id, duration_minutes, exit_time, customer_id) VALUES (?, ?, CURRENT_TIMESTAMP, ?)", 
                       (table_id, int(duration/60), customer_id))
        
        if customer_id:
            cursor.execute("UPDATE customer_profiles SET last_seen = CURRENT_TIMESTAMP, visit_count = visit_count + 1 WHERE id = ?", (customer_id,))
            
        conn.commit()
        conn.close()

def get_known_customers():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, face_encoding FROM customer_profiles")
        rows = cursor.fetchall()
        conn.close()
        return rows

def register_customer(encoding):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO customer_profiles (face_encoding) VALUES (?)", (encoding,))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return new_id

def get_loyalty_analytics():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, visit_count, last_seen 
            FROM customer_profiles 
            ORDER BY visit_count DESC LIMIT 10
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"name": f"{r[0]} #{i+1}" if r[0] == 'New Guest' else r[0], "visits": r[1], "last_visit": r[2][:10]} for i, r in enumerate(rows)]

def record_sale(staff_id, amount):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sales (staff_id, amount) VALUES (?, ?)", (staff_id, float(amount)))
        conn.commit()
        conn.close()

def get_service_engagement_analytics():
    """Calculates how much time staff spend in 'Dining Area' with customers"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.name, s.role,
                   COUNT(DISTINCT l.id) as interactions,
                   SUM(CASE WHEN l.zone = 'Dining Area' THEN 1 ELSE 0 END) * 10 as engagement_seconds
            FROM staff s
            JOIN activity_logs l ON s.id = l.staff_id
            WHERE l.timestamp >= date('now', '-7 days')
            GROUP BY s.id
            ORDER BY engagement_seconds DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"name":r[0], "role":r[1], "interactions":r[2], "engagement_time":round(r[3]/60, 1)} for r in rows]

def get_wellbeing_data():
    """Checks for long consecutive work hours without breaks"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.name, s.role, 
                   (strftime('%s', 'now', 'localtime') - strftime('%s', a.entry_time, 'localtime')) / 3600.0 as hours_on_shift
            FROM attendance a JOIN staff s ON a.staff_id = s.id
            WHERE date(a.entry_time, 'localtime') = date('now', 'localtime')
              AND a.exit_time IS NULL
            ORDER BY hours_on_shift DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"name":r[0], "role":r[1], "hours":round(r[2], 1), "needs_break": r[2] > 4} for r in rows]

def save_zone_config(name, points_json, roles):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO zones_config VALUES (?, ?, ?)", (name, points_json, roles))
        conn.commit()
        conn.close()

def get_zones_config():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM zones_config")
        r = cursor.fetchall()
        conn.close()
        return r

def validate_admin(u, p):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT password FROM admins WHERE username=?", (u,))
        r = cursor.fetchone()
        conn.close()
        return r and r[0] == p

def update_admin_password(u, new_p):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE admins SET password = ? WHERE username = ?", (new_p, u))
        conn.commit()
        conn.close()

def get_system_settings():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM system_settings")
        res = cursor.fetchall()
        conn.close()
        return {r[0]: r[1] for r in res}

def update_system_settings(settings):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        for key, value in settings.items():
            cursor.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
        conn.close()

# --- REASONING ENGINE HELPER FUNCTIONS ---

def get_detailed_performance_metrics():
    """Generates deep insights for the Reasoning Chatbot"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.name, s.role, 
                   COUNT(DISTINCT date(a.entry_time)) as days_worked,
                   SUM(a.is_late) as late_count,
                   (SELECT zone FROM activity_logs WHERE staff_id = s.id GROUP BY zone ORDER BY COUNT(*) DESC LIMIT 1) as primary_zone,
                   s.hourly_rate
            FROM staff s
            LEFT JOIN attendance a ON s.id = a.staff_id
            GROUP BY s.id
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"id":r[0], "name":r[1], "role":r[2], "days":r[3], "late":r[4], "zone":r[5] or "N/A", "rate":r[6]} for r in rows]

def get_shift_optimization_data(days=7):
    """Aggregates staff count and activity ratio by hour of day over the last X days"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            WITH hourly_stats AS (
                SELECT 
                    strftime('%H', a.entry_time, 'localtime') as hour,
                    COUNT(DISTINCT a.id) as sessions,
                    SUM(COALESCE(a.active_seconds, 0)) as total_active,
                    SUM(CASE WHEN a.exit_time IS NOT NULL 
                             THEN (strftime('%s', a.exit_time, 'localtime') - strftime('%s', a.entry_time, 'localtime'))
                             ELSE (strftime('%s', 'now', 'localtime') - strftime('%s', a.entry_time, 'localtime')) END) as total_worked
                FROM attendance a
                WHERE a.entry_time >= date('now', '-{days} days')
                GROUP BY hour
            )
            SELECT 
                hour, 
                CAST(sessions AS REAL) / {days} as avg_staff,
                CASE WHEN total_worked > 0 THEN (CAST(total_active AS REAL) / total_worked) * 100 ELSE 0 END as activity_ratio
            FROM hourly_stats
            ORDER BY hour ASC
        """)
        rows = cursor.fetchall()
        conn.close()
        
        suggestions = []
        for hour, staff, ratio in rows:
            hour_int = int(hour)
            time_str = f"{hour_int:02d}:00 - {(hour_int+1)%24:02d}:00"
            if ratio < 30 and staff > 2:
                suggestions.append({"time": time_str, "type": "Low Activity", "reason": f"{round(ratio,1)}% active", "advice": f"Reduce {int(staff-1)} staff"})
            elif ratio > 75:
                suggestions.append({"time": time_str, "type": "PEAK TRAFFIC", "reason": f"{round(ratio,1)}% occupancy", "advice": "Critical! Add 1-2 waiters"})
            elif 50 <= ratio <= 75:
                 suggestions.append({"time": time_str, "type": "Busy", "reason": "Steady traffic", "advice": "Maintain current staff"})
        
        return {"data": [{"hour": r[0], "staff": round(r[1] or 0, 1), "activity": round(r[2] or 0, 1)} for r in rows], "suggestions": suggestions}

def get_todays_shift_roster():
    """Returns today's shift distribution for Pakistani restaurant context"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, role, shift, shift_start 
            FROM staff 
            ORDER BY CASE WHEN shift='Morning' THEN 1 WHEN shift='Evening' THEN 2 ELSE 3 END
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"name":r[0], "role":r[1], "shift":r[2], "time":r[3]} for r in rows]

def get_period_report_data(start_date, end_date):
    """Gathers all report data for a specific period"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Period Summary
        cursor.execute(f"""
            SELECT 
                COUNT(DISTINCT a.staff_id), 
                SUM(CASE WHEN a.exit_time IS NOT NULL 
                         THEN (strftime('%s', a.exit_time, 'localtime') - strftime('%s', a.entry_time, 'localtime'))
                         ELSE (strftime('%s', 'now', 'localtime') - strftime('%s', a.entry_time, 'localtime')) END) / 3600.0,
                SUM(COALESCE(a.active_seconds, 0))
            FROM attendance a 
            WHERE date(a.entry_time, 'localtime') BETWEEN '{start_date}' AND '{end_date}'
        """)
        s_stats = cursor.fetchone()
        
        # Detailed Row data (Name, Role, Hours, Performance, Earnings)
        cursor.execute(f"""
            SELECT 
                date(a.entry_time, 'localtime'),
                s.name, s.role,
                (CASE WHEN a.exit_time IS NOT NULL 
                      THEN (strftime('%s', a.exit_time, 'localtime') - strftime('%s', a.entry_time, 'localtime'))
                      ELSE (strftime('%s', 'now', 'localtime') - strftime('%s', a.entry_time, 'localtime')) END) / 3600.0 as hours,
                s.hourly_rate,
                COALESCE(a.active_seconds, 0) as active_sec
            FROM attendance a JOIN staff s ON a.staff_id = s.id
            WHERE date(a.entry_time, 'localtime') BETWEEN '{start_date}' AND '{end_date}'
            ORDER BY a.entry_time DESC
        """)
        rows = cursor.fetchall()
        
        detail_rows = []
        for r in rows:
            hrs = r[3]
            rate = r[4]
            active_pct = (r[5] / (hrs * 3600) * 100) if hrs > 0 else 0
            detail_rows.append({
                "date": r[0], "name": r[1], "role": r[2], "hours": round(hrs, 1), 
                "rate": rate, "earnings": round(hrs * rate, 0), "performance": round(active_pct, 1)
            })
            
        conn.close()
        return {
            "summary": {
                "staff_count": s_stats[0] or 0,
                "total_hours": round(s_stats[1] or 0, 1),
                "total_cost": sum(d['earnings'] for d in detail_rows),
                "avg_efficiency": round(sum(d['performance'] for d in detail_rows) / len(detail_rows), 1) if detail_rows else 0,
                "monthly_customers": get_monthly_customer_stats().get("monthly_total", 0)
            },
            "details": detail_rows
        }

def get_period_alerts(start_date, end_date):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT l.timestamp, s.name, l.zone, l.details 
            FROM activity_logs l JOIN staff s ON l.staff_id = s.id
            WHERE action LIKE '%Alert%' AND date(timestamp, 'localtime') BETWEEN '{start_date}' AND '{end_date}'
            ORDER BY timestamp DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"time": r[0], "name": r[1], "zone": r[2], "details": r[3]} for r in rows]

def get_monthly_customer_stats():
    """Aggregates customer traffic for the current month"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Monthly Count
        cursor.execute("""
            SELECT COUNT(*) FROM customers 
            WHERE strftime('%m', entry_time, 'localtime') = strftime('%m', 'now', 'localtime')
              AND strftime('%Y', entry_time, 'localtime') = strftime('%Y', 'now', 'localtime')
        """)
        monthly_total = cursor.fetchone()[0] or 0
        
        # Avg Stay Duration
        cursor.execute("""
            SELECT AVG(duration_minutes) FROM customers 
            WHERE strftime('%m', entry_time, 'localtime') = strftime('%m', 'now', 'localtime')
        """)
        avg_stay = cursor.fetchone()[0] or 0
        
        # Busiest Day of Current Month
        cursor.execute("""
            SELECT CASE strftime('%w', entry_time, 'localtime')
                        WHEN '0' THEN 'Sunday' WHEN '1' THEN 'Monday' WHEN '2' THEN 'Tuesday'
                        WHEN '3' THEN 'Wednesday' WHEN '4' THEN 'Thursday' WHEN '5' THEN 'Friday'
                        WHEN '6' THEN 'Saturday' END as day_name, 
                   COUNT(*) as cnt
            FROM customers
            WHERE strftime('%m', entry_time, 'localtime') = strftime('%m', 'now', 'localtime')
            GROUP BY day_name ORDER BY cnt DESC LIMIT 1
        """)
        busiest_day = cursor.fetchone()
        
        conn.close()
        return {
            "monthly_total": monthly_total,
            "avg_visit": round(avg_stay, 1) if avg_stay else 0,
            "peak_day": busiest_day[0] if busiest_day else "Pending Data"
        }


if __name__ == "__main__":
    init_db()
