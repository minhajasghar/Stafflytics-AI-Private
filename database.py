import sqlite3
import threading
import os
import json
import re
from datetime import datetime, timedelta

# Use RLock to prevent deadlocks when functions call each other
db_lock = threading.RLock()

DB_PATH = "data/stafflytics.db"

# Load database configuration from config.json
DB_CONFIG = {
    "DB_TYPE": "sqlite",
    "MYSQL_HOST": "localhost",
    "MYSQL_PORT": 3306,
    "MYSQL_USER": "root",
    "MYSQL_PASSWORD": "",
    "MYSQL_DATABASE": "stafflytics"
}

if os.path.exists("config.json"):
    try:
        with open("config.json", "r") as f:
            DB_CONFIG.update(json.load(f))
    except Exception as e:
        print(f"[DB] Error reading config.json, using defaults: {e}")

# MySQL compatibility layer to emulate sqlite3.Row
class MySQLRow:
    def __init__(self, tuple_data, column_names):
        self.tuple_data = tuple_data
        self.column_names = {name.lower(): idx for idx, name in enumerate(column_names)}
        
    def __getitem__(self, key):
        if isinstance(key, int):
            return self.tuple_data[key]
        elif isinstance(key, str):
            idx = self.column_names.get(key.lower())
            if idx is not None:
                return self.tuple_data[idx]
            raise KeyError(f"Column '{key}' not found in row")
        elif isinstance(key, slice):
            return self.tuple_data[key]
        raise TypeError("Index must be int, str or slice")
        
    def keys(self):
        return list(self.column_names.keys())
        
    def __iter__(self):
        return iter(self.tuple_data)
        
    def __len__(self):
        return len(self.tuple_data)

# Translates SQLite syntax to MySQL syntax dynamically
def translate_sqlite_to_mysql(query):
    # MySQL uses %s parameter placeholders
    query = query.replace('?', '%s')
    
    # Insert OR keywords
    query = query.replace('INSERT OR IGNORE', 'INSERT IGNORE')
    query = query.replace('INSERT OR REPLACE', 'REPLACE')
    
    # Escape reserved 'key' and 'value' columns in system_settings
    query = query.replace('(key, value)', '(`key`, `value`)')
    query = query.replace('key TEXT PRIMARY KEY', '`key` VARCHAR(255) PRIMARY KEY')
    query = query.replace('value TEXT', '`value` VARCHAR(1000)')
    query = query.replace('key, value FROM system_settings', '`key`, `value` FROM system_settings')
    query = query.replace('key = %s', '`key` = %s')
    query = query.replace('value = %s', '`value` = %s')
    
    # Date/Time functions
    query = query.replace("date('now', 'localtime')", "CURDATE()")
    query = query.replace("time('now', 'localtime')", "CURTIME()")
    query = query.replace("datetime('now', 'localtime')", "NOW()")
    
    # Translate relative offsets like date('now', '-7 days') or date('now', '-30 days')
    query = re.sub(r"date\('now',\s*'-(\d+)\s+days'\)", r"DATE_SUB(CURDATE(), INTERVAL \1 DAY)", query)
    
    # Handle localized dates
    query = query.replace("date(entry_time, 'localtime')", "DATE(entry_time)")
    query = query.replace("date(a.entry_time, 'localtime')", "DATE(a.entry_time)")
    query = query.replace("date(exit_time, 'localtime')", "DATE(exit_time)")
    query = query.replace("date(timestamp, 'localtime')", "DATE(timestamp)")
    query = query.replace("date(entry_time)", "DATE(entry_time)")
    query = query.replace("date(a.entry_time)", "DATE(a.entry_time)")
    query = query.replace("date(exit_time)", "DATE(exit_time)")
    
    # Local timestamps
    query = query.replace("strftime('%s', exit_time, 'localtime')", "UNIX_TIMESTAMP(exit_time)")
    query = query.replace("strftime('%s', entry_time, 'localtime')", "UNIX_TIMESTAMP(entry_time)")
    query = query.replace("strftime('%s', a.exit_time, 'localtime')", "UNIX_TIMESTAMP(a.exit_time)")
    query = query.replace("strftime('%s', a.entry_time, 'localtime')", "UNIX_TIMESTAMP(a.entry_time)")
    query = query.replace("strftime('%s', 'now', 'localtime')", "UNIX_TIMESTAMP(NOW())")
    
    # Local months and years
    query = query.replace("strftime('%m', entry_time, 'localtime')", "DATE_FORMAT(entry_time, '%m')")
    query = query.replace("strftime('%m', a.entry_time, 'localtime')", "DATE_FORMAT(a.entry_time, '%m')")
    query = query.replace("strftime('%m', 'now', 'localtime')", "DATE_FORMAT(NOW(), '%m')")
    query = query.replace("strftime('%m', last_seen, 'localtime')", "DATE_FORMAT(last_seen, '%m')")
    query = query.replace("strftime('%Y', entry_time, 'localtime')", "DATE_FORMAT(entry_time, '%Y')")
    query = query.replace("strftime('%Y', a.entry_time, 'localtime')", "DATE_FORMAT(a.entry_time, '%Y')")
    query = query.replace("strftime('%Y', 'now', 'localtime')", "DATE_FORMAT(NOW(), '%Y')")
    query = query.replace("strftime('%w', entry_time, 'localtime')", "(DAYOFWEEK(entry_time) - 1)")
    query = query.replace("strftime('%H', a.entry_time, 'localtime')", "HOUR(a.entry_time)")
    
    # Scalar MAX/MIN functions (MySQL uses GREATEST/LEAST for scalar operations)
    query = query.replace('MAX(1,', 'GREATEST(1,')
    query = query.replace('MAX(0,', 'GREATEST(0,')
    query = query.replace('MIN(20,', 'LEAST(20,')
    
    # Table type compatibility mappings
    query = query.replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'INTEGER PRIMARY KEY AUTO_INCREMENT')
    query = query.replace('TEXT PRIMARY KEY', 'VARCHAR(255) PRIMARY KEY')
    query = query.replace('staff_id TEXT', 'staff_id VARCHAR(255)')
    query = query.replace('table_id TEXT', 'table_id VARCHAR(255)')
    query = query.replace('role TEXT', 'role VARCHAR(255)')
    query = query.replace('name TEXT', 'name VARCHAR(255)')
    query = query.replace('username TEXT PRIMARY KEY', 'username VARCHAR(255) PRIMARY KEY')
    query = query.replace('password TEXT', 'password VARCHAR(255)')
    query = query.replace('email TEXT', 'email VARCHAR(255)')
    query = query.replace('shift_start TEXT', 'shift_start VARCHAR(255)')
    query = query.replace('shift TEXT', 'shift VARCHAR(255)')
    query = query.replace('salary_type TEXT', 'salary_type VARCHAR(255)')
    query = query.replace('zone TEXT', 'zone VARCHAR(255)')
    query = query.replace('action TEXT', 'action VARCHAR(255)')
    query = query.replace('details TEXT', 'details VARCHAR(1000)')
    query = query.replace('event_type TEXT', 'event_type VARCHAR(255)')
    query = query.replace('intensity TEXT', 'intensity VARCHAR(255)')
    query = query.replace('points_json TEXT', 'points_json VARCHAR(2000)')
    query = query.replace('unauthorized_roles TEXT', 'unauthorized_roles VARCHAR(1000)')
    query = query.replace('duration_minutes REAL', 'duration_minutes FLOAT')
    query = query.replace('hourly_rate REAL', 'hourly_rate DECIMAL(10,2)')
    query = query.replace('active_seconds REAL', 'active_seconds DECIMAL(10,4)')
    query = query.replace('amount REAL NOT NULL', 'amount DECIMAL(10,2) NOT NULL')
    query = re.sub(r'\bCAST\(([^()]+)\s+AS\s+REAL\)', r'CAST(\1 AS DECIMAL(10,4))', query)
    query = query.replace('CAST(COALESCE(active_seconds, 0) AS REAL)', 'CAST(COALESCE(active_seconds, 0) AS DECIMAL(10,4))')
    query = query.replace('CAST(SUM(a.is_late) AS REAL)', 'CAST(SUM(a.is_late) AS DECIMAL(10,4))')
    query = query.replace('CAST(sessions AS REAL)', 'CAST(sessions AS DECIMAL(10,4))')
    query = query.replace('CAST(total_active AS REAL)', 'CAST(total_active AS DECIMAL(10,4))')
    
    return query

class MySQLCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor
        self.is_pragma_table_info = False
        
    def execute(self, query, params=None):
        if "pragma table_info" in query.lower():
            self.is_pragma_table_info = True
            m = re.search(r"pragma table_info\((.+?)\)", query, re.IGNORECASE)
            table_name = m.group(1).strip() if m else "staff"
            query = f"DESCRIBE {table_name}"
        else:
            self.is_pragma_table_info = False
            
        translated_query = translate_sqlite_to_mysql(query)
        if params is not None:
            self.cursor.execute(translated_query, params)
        else:
            self.cursor.execute(translated_query)
            
    def fetchone(self):
        row = self.cursor.fetchone()
        if row is not None:
            if self.is_pragma_table_info:
                # DESCRIBE fields: (Field, Type, Null, Key, Default, Extra) -> c[1] is name
                return MySQLRow((0, row[0], 2, 3, 4, 5), ["cid", "name", "type", "notnull", "dflt_value", "pk"])
            return MySQLRow(row, self.cursor.column_names)
        return None
        
    def fetchall(self):
        rows = self.cursor.fetchall()
        if self.is_pragma_table_info:
            return [MySQLRow((0, r[0], 2, 3, 4, 5), ["cid", "name", "type", "notnull", "dflt_value", "pk"]) for r in rows]
        column_names = self.cursor.column_names
        return [MySQLRow(r, column_names) for r in rows]
        
    @property
    def lastrowid(self):
        return self.cursor.lastrowid
        
    def close(self):
        self.cursor.close()

class MySQLConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn
        
    def cursor(self, **kwargs):
        return MySQLCursorWrapper(self.conn.cursor(**kwargs))
        
    def commit(self):
        self.conn.commit()
        
    def rollback(self):
        self.conn.rollback()
        
    def close(self):
        self.conn.close()

def get_db_connection():
    if DB_CONFIG["DB_TYPE"] == "mysql":
        import mysql.connector
        conn = mysql.connector.connect(
            host=DB_CONFIG["MYSQL_HOST"],
            port=DB_CONFIG["MYSQL_PORT"],
            user=DB_CONFIG["MYSQL_USER"],
            password=DB_CONFIG["MYSQL_PASSWORD"],
            database=DB_CONFIG["MYSQL_DATABASE"]
        )
        return MySQLConnectionWrapper(conn)
    else:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 10000;")
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

def init_db():
    if DB_CONFIG["DB_TYPE"] == "mysql":
        import mysql.connector
        try:
            conn = mysql.connector.connect(
                host=DB_CONFIG["MYSQL_HOST"],
                port=DB_CONFIG["MYSQL_PORT"],
                user=DB_CONFIG["MYSQL_USER"],
                password=DB_CONFIG["MYSQL_PASSWORD"]
            )
            cursor = conn.cursor()
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {DB_CONFIG['MYSQL_DATABASE']}")
            conn.commit()
            cursor.close()
            conn.close()
            print(f"[DB] Verified/Created MySQL database '{DB_CONFIG['MYSQL_DATABASE']}'")
        except Exception as e:
            print(f"[DB ERROR] MySQL pre-init database creation failed: {e}")
    else:
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
        
        # Migration: Add columns if not exists
        cursor.execute("PRAGMA table_info(staff)")
        cols = [c[1] for c in cursor.fetchall()]
        if 'salary_type' not in cols:
            cursor.execute("ALTER TABLE staff ADD COLUMN salary_type TEXT DEFAULT 'Monthly'")
        if 'photo' not in cols:
            cursor.execute("ALTER TABLE staff ADD COLUMN photo TEXT")

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
            duration_minutes REAL,
            customer_id INTEGER
        )
        ''')
        
        # Migration: Add customer_id if not exists
        cursor.execute("PRAGMA table_info(customers)")
        if 'customer_id' not in [c[1] for c in cursor.fetchall()]:
            cursor.execute("ALTER TABLE customers ADD COLUMN customer_id INTEGER")

        # Migration: Ensure duration_minutes is REAL or FLOAT
        if DB_CONFIG["DB_TYPE"] == "mysql":
            try:
                cursor.execute("ALTER TABLE customers MODIFY COLUMN duration_minutes FLOAT")
                conn.commit()
            except Exception as e:
                print(f"[DB MIGRATION] ALTER TABLE customers failed (might already be FLOAT): {e}")

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

        # Migration: Ensure customer_profiles has a photo column
        try:
            cursor.execute("ALTER TABLE customer_profiles ADD COLUMN photo LONGTEXT NULL")
            conn.commit()
            print("[DB MIGRATION] Added photo column to customer_profiles table.")
        except Exception:
            pass # Column already exists


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

        # Visitor Analytics Log (every face detection event)
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS visitor_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            customer_id INTEGER,
            is_new_face BOOLEAN DEFAULT 1,
            staff_id TEXT,
            zone TEXT
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
            ('rtsp_url', ''),
            ('late_grace_minutes', '10'),
            ('wellness_threshold', '4')
        ]
        for key, val in defaults:
            cursor.execute("INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)", (key, val))

        conn.commit()
        conn.close()

# --- OWNER MANAGEMENT (CRUD) ---

def add_staff(staff_id, name, role, encoding, shift_start='10:00', shift='Morning', hourly_rate=500, salary_type='Monthly', photo=None):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO staff (id, name, role, shift_start, shift, hourly_rate, salary_type, face_encoding, photo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                       (staff_id, name, role, shift_start, shift, hourly_rate, salary_type, encoding, photo))
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
        cursor.execute("SELECT id, name, role, shift_start, hourly_rate, face_encoding, shift, salary_type, photo FROM staff")
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
                
                # Apply configurable grace period (default 10 minutes)
                cursor.execute("SELECT value FROM system_settings WHERE key = 'late_grace_minutes'")
                grace_row = cursor.fetchone()
                grace_minutes = int(grace_row[0]) if grace_row and grace_row[0] else 10
                
                # Compare with grace: time('now') > time(shift_start + grace_minutes)
                cursor.execute("SELECT time('now', 'localtime') > time(?, '+' || ? || ' minutes')", (shift_start, grace_minutes))
                is_late = cursor.fetchone()[0]

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

def get_synergy_metrics():
    """Cross-domain KPIs combining sales, staff, and customer data"""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()

        # Total sales today
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM sales WHERE date(timestamp, 'localtime') = date('now', 'localtime')")
        sales_today = cursor.fetchone()[0]

        # Staff hours worked today
        cursor.execute("""
            SELECT COALESCE(SUM(
                CAST(COALESCE(active_seconds, 0) AS REAL) / 3600.0
            ), 0) FROM attendance WHERE date(entry_time, 'localtime') = date('now', 'localtime')
        """)
        staff_hours = cursor.fetchone()[0]

        # Customers today
        cursor.execute("SELECT COUNT(*) FROM customers WHERE date(entry_time, 'localtime') = date('now', 'localtime')")
        customers_today = cursor.fetchone()[0]

        # Average efficiency today
        cursor.execute("""
            SELECT COALESCE(AVG(CAST(active_seconds AS REAL) /
                CASE WHEN exit_time IS NOT NULL
                     THEN MAX(1, (strftime('%s', exit_time, 'localtime') - strftime('%s', entry_time, 'localtime')))
                     ELSE MAX(1, (strftime('%s', 'now', 'localtime') - strftime('%s', entry_time, 'localtime'))) END) * 100, 0)
            FROM attendance WHERE date(entry_time, 'localtime') = date('now', 'localtime')
        """)
        avg_efficiency = cursor.fetchone()[0]
        
        # Late arrivals today
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE date(entry_time, 'localtime') = date('now', 'localtime') AND is_late = 1")
        late_count = cursor.fetchone()[0]

        conn.close()

        rev_per_hour = round(sales_today / staff_hours, 0) if staff_hours > 0 else 0
        cust_per_staff = round(customers_today / max(staff_hours / 8, 1), 1) if staff_hours > 0 else 0

        return {
            "metrics": [
                {"label": "Revenue per Hour", "value": f"Rs. {rev_per_hour:,.0f}"},
                {"label": "Team Efficiency", "value": f"{avg_efficiency:.0f}%"},
                {"label": "Customers Today", "value": str(customers_today)},
                {"label": "Late Arrivals", "value": str(late_count)}
            ]
        }

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
            GROUP BY s.id, s.name, s.role
            HAVING total_sec > 0
        """)
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for r in rows:
            total_sec = float(r[2] or 1)
            active_sec = float(r[3] or 0)
            score = round((active_sec / total_sec * 100.0), 1) if total_sec > 0 else 0
            results.append({"name": r[0], "role": r[1], "score": score})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

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

def get_daily_attendance(date_str):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            SELECT a.entry_time, a.exit_time, s.name, s.role,
                   (CASE WHEN a.exit_time IS NOT NULL 
                         THEN (strftime('%s', a.exit_time, 'localtime') - strftime('%s', a.entry_time, 'localtime')) 
                         ELSE (strftime('%s', 'now', 'localtime') - strftime('%s', a.entry_time, 'localtime')) END) / 3600.0,
                   s.salary_type, a.is_late, a.active_seconds
            FROM attendance a JOIN staff s ON a.staff_id = s.id
            WHERE date(a.entry_time, 'localtime') = date(?, 'localtime')
            ORDER BY a.entry_time DESC
        """
        cursor.execute(query, (date_str,))
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

def get_today_customer_stats():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*), COALESCE(SUM(duration_minutes), 0)
            FROM customers
            WHERE date(entry_time, 'localtime') = date('now', 'localtime')
        """)
        r = cursor.fetchone()
        conn.close()
        return {"today_count": r[0] or 0, "today_minutes": round(r[1] or 0, 1)}

def log_visitor_detection(customer_id, is_new_face, staff_id=None, zone=None):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO visitor_log (customer_id, is_new_face, staff_id, zone) VALUES (?, ?, ?, ?)",
            (customer_id, 1 if is_new_face else 0, staff_id, zone or "Main Hall")
        )
        conn.commit()
        conn.close()

def get_visitor_analytics(scope="day"):
    """Returns per-day or per-month visitor analytics.
    
    Scope: 'day' for today, 'month' for current month.
    """
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if scope == "month":
            date_filter = "strftime('%m', timestamp, 'localtime') = strftime('%m', 'now', 'localtime') AND strftime('%Y', timestamp, 'localtime') = strftime('%Y', 'now', 'localtime')"
        else:
            date_filter = "date(timestamp, 'localtime') = date('now', 'localtime')"
        
        # Total unique visitors (by customer_id for known, by raw id for anonymous)
        cursor.execute(f"""
            SELECT COUNT(DISTINCT CASE 
                WHEN customer_id IS NOT NULL THEN 'c:' || customer_id 
                ELSE 'a:' || id 
            END)
            FROM visitor_log WHERE {date_filter}
        """)
        total_unique = cursor.fetchone()[0] or 0
        
        # New faces count (is_new_face = 1)
        cursor.execute(f"""
            SELECT COUNT(DISTINCT id) 
            FROM visitor_log WHERE is_new_face = 1 AND {date_filter}
        """)
        new_faces = cursor.fetchone()[0] or 0
        
        # Regular customers — customer_id with visit on 2+ different days
        cursor.execute(f"""
            SELECT customer_id, COUNT(DISTINCT date(timestamp, 'localtime')) as visit_days
            FROM visitor_log 
            WHERE customer_id IS NOT NULL AND {date_filter}
            GROUP BY customer_id
        """)
        regular_rows = cursor.fetchall()
        regular_customers = sum(1 for r in regular_rows if r[1] >= 2)
        returning_customers = sum(1 for r in regular_rows if r[1] < 2)
        
        # Visit frequency distribution (how many customers by visit-day count)
        frequency = {}
        for r in regular_rows:
            days = r[1]
            bucket = str(int(days)) + "d"
            frequency[bucket] = frequency.get(bucket, 0) + 1
        
        # Daily breakdown for the month view
        daily_breakdown = []
        if scope == "month":
            cursor.execute(f"""
                SELECT date(timestamp, 'localtime') as day,
                       COUNT(DISTINCT CASE WHEN customer_id IS NOT NULL THEN 'c:' || customer_id ELSE 'a:' || id END) as uniques,
                       SUM(CASE WHEN is_new_face = 1 THEN 1 ELSE 0 END) as new_count,
                       COUNT(*) as total_events
                FROM visitor_log 
                WHERE {date_filter}
                GROUP BY day
                ORDER BY day ASC
            """)
            for row in cursor.fetchall():
                daily_breakdown.append({
                    "date": row[0],
                    "unique_visitors": row[1] or 0,
                    "new_faces": row[2] or 0,
                    "total_events": row[3] or 0
                })
        
        conn.close()
        
        return {
            "scope": scope,
            "total_unique_visitors": total_unique,
            "new_faces": new_faces,
            "returning_customers": returning_customers,
            "regular_customers": regular_customers,
            "total_known": returning_customers + regular_customers,
            "frequency_distribution": frequency,
            "daily_breakdown": daily_breakdown
        }

def record_customer_session(table_id, duration, customer_id=None):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Deduplication: check if there was a session in the last few minutes in the same area
        # 5 minutes for recognized customers, 3 minutes for anonymous ones
        limit_minutes = 5 if customer_id else 3
        limit_time = (datetime.now() - timedelta(minutes=limit_minutes)).strftime('%Y-%m-%d %H:%M:%S')
        
        if customer_id:
            cursor.execute("""
                SELECT id, duration_minutes FROM customers 
                WHERE customer_id = ? AND exit_time >= ? 
                ORDER BY exit_time DESC LIMIT 1
            """, (customer_id, limit_time))
        else:
            cursor.execute("""
                SELECT id, duration_minutes FROM customers 
                WHERE customer_id IS NULL AND table_id = ? AND exit_time >= ? 
                ORDER BY exit_time DESC LIMIT 1
            """, (table_id, limit_time))
            
        existing = cursor.fetchone()
        if existing:
            new_duration = existing[1] + round(duration / 60.0, 2)
            cursor.execute("UPDATE customers SET duration_minutes = ?, exit_time = CURRENT_TIMESTAMP WHERE id = ?", (new_duration, existing[0]))
        else:
            cursor.execute("INSERT INTO customers (table_id, duration_minutes, exit_time, customer_id) VALUES (?, ?, CURRENT_TIMESTAMP, ?)", 
                           (table_id, round(duration / 60.0, 2), customer_id))
        
        if customer_id:
            cursor.execute("UPDATE customer_profiles SET last_seen = CURRENT_TIMESTAMP, visit_count = visit_count + 1 WHERE id = ?", (customer_id,))
            
        conn.commit()
        conn.close()

def get_known_customers():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, face_encoding, visit_count, photo FROM customer_profiles")
        rows = cursor.fetchall()
        conn.close()
        return rows

def register_customer(encoding, photo=None):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO customer_profiles (face_encoding, photo) VALUES (?, ?)", (encoding, photo))
        new_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return new_id

def update_customer_encoding(customer_id, encoding_blob, photo=None):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        if photo:
            cursor.execute("UPDATE customer_profiles SET face_encoding = ?, last_seen = CURRENT_TIMESTAMP, photo = ? WHERE id = ?", (encoding_blob, photo, customer_id))
        else:
            cursor.execute("UPDATE customer_profiles SET face_encoding = ?, last_seen = CURRENT_TIMESTAMP WHERE id = ?", (encoding_blob, customer_id))
        conn.commit()
        conn.close()

def get_loyalty_analytics():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, visit_count, last_seen, photo, id 
            FROM customer_profiles 
            ORDER BY visit_count DESC LIMIT 10
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"name": f"{r[0]} #{i+1}" if r[0] == 'New Guest' else r[0], "visits": r[1], "last_visit": r[2][:10] if r[2] else "N/A", "photo": r[3], "id": r[4]} for i, r in enumerate(rows)]

def record_sale(staff_id, amount):
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sales (staff_id, amount) VALUES (?, ?)", (staff_id, float(amount)))
        conn.commit()
        conn.close()

def get_service_engagement_analytics():
    """Calculates service engagement: percentage of staff activity in 'Dining Area' vs total tracked zones.
    Higher percentage = more time serving customers (for waitstaff/servers, this is the primary work zone)."""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.name, s.role,
                   SUM(CASE WHEN l.zone = 'Dining Area' THEN 1 ELSE 0 END) as dining_events,
                   COUNT(l.id) as total_events,
                   ROUND(100.0 * SUM(CASE WHEN l.zone = 'Dining Area' THEN 1 ELSE 0 END) / NULLIF(COUNT(l.id), 0), 1) as engagement_pct
            FROM staff s
            JOIN activity_logs l ON s.id = l.staff_id
            WHERE l.timestamp >= date('now', '-7 days')
            GROUP BY s.id
            ORDER BY engagement_pct DESC
        """)
        rows = cursor.fetchall()
        conn.close()
        return [{"name":r[0], "role":r[1], "dining_events":r[2], "total_events":r[3], "engagement_pct":r[4]} for r in rows]

def get_wellbeing_data():
    """Checks for long consecutive work hours without breaks. Uses configurable threshold."""
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Get configurable threshold from system settings
        cursor.execute("SELECT value FROM system_settings WHERE key = 'wellness_threshold'")
        thr_row = cursor.fetchone()
        break_threshold = int(thr_row[0]) if thr_row and thr_row[0] else 4
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
        return [{"name":r[0], "role":r[1], "hours":round(r[2], 1), "needs_break": r[2] > break_threshold} for r in rows]

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
        
        # Total Repeating Customers this month
        cursor.execute("""
            SELECT COUNT(*) FROM customer_profiles 
            WHERE visit_count > 1 
              AND strftime('%m', last_seen, 'localtime') = strftime('%m', 'now', 'localtime')
        """)
        repeat_count = cursor.fetchone()[0] or 0
        
        conn.close()
        return {
            "monthly_total": monthly_total,
            "avg_visit": round(avg_stay, 1) if avg_stay else 0,
            "peak_day": busiest_day[0] if busiest_day else "Pending Data",
            "repeat_customers": repeat_count
        }

def get_admin_email():
    with db_lock:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM admins LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

if __name__ == "__main__":
    init_db()
