from flask import Flask, render_template, Response, jsonify, request, session, redirect, url_for
import cv2
import database
# Heavy imports moved to background thread
# from vision_engine import VisionEngine
# import face_recognition
import threading
import time
import pickle
import numpy as np
import base64
import io
from PIL import Image
from functools import wraps
from datetime import datetime, timedelta
import mailer
from chatbot_engine import chatbot
import requests
from export_engine import export_engine
from flask import send_file

# Stafflytics AI Configuration
app = Flask(__name__)
app.secret_key = 'signature_secret_key_stafflytics_2026'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)

# Initialize database & Mailer
# database.init_db() # Moved to background
engine = None        # Initialized asynchronously
camera_stream = None # Initialized asynchronously
system_initializing = True
init_status = "System Awakening..."

def sync_mailer_config():
    conf = database.get_system_settings()
    mailer.SENDER_EMAIL = conf.get('sender_email', '')
    mailer.SENDER_PASSWORD = conf.get('sender_password', '')
    mailer.OWNER_EMAIL = conf.get('owner_email', 'admin@stafflytics.ai')
    app.config['TELEGRAM_TOKEN'] = conf.get('telegram_bot_token', '')
    app.config['TELEGRAM_CHAT_ID'] = conf.get('telegram_chat_id', '')

def send_telegram_alert(message):
    token = app.config.get('TELEGRAM_TOKEN')
    chat_id = app.config.get('TELEGRAM_CHAT_ID')
    if token and chat_id:
        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}, timeout=5)
        except Exception as e: print(f"[Telegram Error] {e}")

# sync_mailer_config() # Moved to background
camera_online = False # Global status for dashboard

class CameraStream:
    def __init__(self):
        self.stream = None
        self.frame = None
        self.stopped = False
        self.online = False
        self.lock = threading.Lock()
        self.indices = [0, 1, 2] # Try multiple camera indices
        self.backeneds = [cv2.CAP_DSHOW, cv2.CAP_MSMF, cv2.CAP_ANY]
        
    def start(self):
        # Start the background update thread immediately
        if not any(t.name == "CameraUpdateThread" for t in threading.enumerate()):
            threading.Thread(target=self.update, daemon=True, name="CameraUpdateThread").start()
        return self

    def _attempt_connection(self):
        print("[SYSTEM] Starting Camera Synchronization Loop...")
        for idx in self.indices:
            for be in self.backeneds:
                if self.stopped: return False
                try:
                    print(f"[SYSTEM] Probing Index {idx} with Backend {be}...")
                    cap = cv2.VideoCapture(idx, be)
                    if cap and cap.isOpened():
                        # Quick validation read
                        ret, f = cap.read()
                        if ret and f is not None:
                            print(f"[SYSTEM] Camera successfully synchronized at Index {idx}.")
                            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                            self.stream = cap
                            self.online = True
                            global camera_online
                            camera_online = True
                            return True
                    if cap: cap.release()
                except Exception as e:
                    print(f"[CAMERA PROBE ERROR] {e}")
        return False

    def update(self):
        global camera_online
        while not self.stopped:
            if not self.online:
                if self._attempt_connection():
                    print("[SYSTEM] Camera Signal Established.")
                else:
                    print("[SYSTEM] Camera hardware not found. Retrying in 5s...")
                    time.sleep(5)
                    continue

            try:
                grabbed, frame = self.stream.read()
                if not grabbed or frame is None:
                    print("[SYSTEM] Camera Signal Lost. Attempting Reconnection...")
                    self.online = False
                    camera_online = False
                    if self.stream: self.stream.release()
                    continue
                
                with self.lock:
                    self.frame = frame
            except Exception as e:
                print(f"[CAMERA STREAM ERROR] {e}")
                self.online = False
                camera_online = False
                time.sleep(2)

    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.stopped = True
        if self.stream: self.stream.release()

# --- ASYNCHRONOUS INITIALIZATION ---
def background_system_init():
    global engine, camera_stream, system_initializing, init_status
    start_time = time.time()
    print("[SYSTEM] Instant Launch Sequence Started...")
    
    # 1. Init Database First (Essential)
    try:
        init_status = "Synchronizing Database..."
        database.init_db()
        sync_mailer_config()
        print("[SYSTEM] Database Ready.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Database init failed: {e}")

    # Release the UI early
    system_initializing = False
    init_status = "Dashboard Ready. AI & Camera loading in background..."
    
    # 2. Init Vision Engine (Lazy Loading starts inside)
    try:
        init_status = "Warmup Vision Engine..."
        from vision_engine import VisionEngine
        engine = VisionEngine()
        print("[SYSTEM] Vision Engine Placeholder Loaded.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Vision Engine failed: {e}")
        
    # 3. Init Camera Stream
    try:
        init_status = "Connecting Camera..."
        camera_stream = CameraStream().start()
        print("[SYSTEM] Camera Background Sync Done.")
    except Exception as e:
        print(f"[SYSTEM ERROR] Camera initialization failed: {e}")
        
    init_status = "Ready"
    elapsed = time.time() - start_time
    print(f"[SYSTEM] Background Initialization Finished in {elapsed:.2f} seconds.")

# Start initialization in background
threading.Thread(target=background_system_init, daemon=True, name="SystemInitThread").start()

def generate_frames():
    global camera_stream, engine, system_initializing
    last_process_time = 0
    processed_frame = None
    
    while True:
        try:
            if system_initializing or camera_stream is None:
                # Show loading screen instead of black frame
                loading = np.zeros((480, 640, 3), np.uint8)
                cv2.putText(loading, "INITIALIZING AI...", (150, 220), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
                cv2.putText(loading, "Please wait...", (240, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 1)
                ret, buf = cv2.imencode('.jpg', loading)
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(0.5); continue

            frame = camera_stream.read()
            if frame is None:
                err = np.zeros((480,640,3), np.uint8)
                cv2.putText(err, "CAMERA OFFLINE", (140,240), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (50,50,255), 3)
                ret, buf = cv2.imencode('.jpg', err)
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
                time.sleep(1); continue

            # Only process AI every 100ms to keep stream smooth at 30 FPS
            current_time = time.time()
            if engine and current_time - last_process_time > 0.1:
                start_ai = time.time()
                processed_frame = engine.process_frame(cv2.flip(frame, 1))
                last_process_time = current_time
                # print(f"[DEBUG] AI Latency: {int((time.time() - start_ai)*1000)}ms")
            
            # If AI is still thinking, show the raw frame (flipped) or the last processed one
            display_frame = processed_frame if processed_frame is not None else cv2.flip(frame, 1)
            
            ret, buf = cv2.imencode('.jpg', display_frame)
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
            time.sleep(0.01) # Small sleep to prevent CPU pegging
        except Exception as e:
            print(f"[STREAM ERROR] {e}")
            time.sleep(0.5)

# Auth
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session: return jsonify({"status": "error", "message": "Auth required"}), 401
        return f(*args, **kwargs)
    return decorated_function

# --- SCHEDULER: Nightly Business Report (11 PM) ---
def nightly_scheduler():
    sent_today = False
    while True:
        now = datetime.now()
        if now.hour == 23 and now.minute == 0 and not sent_today:
            summary = database.get_comprehensive_summary()
            html = mailer.get_daily_report_template(summary)
            # Fetch admin email
            with database.db_lock:
                conn = sqlite3.connect(database.DB_PATH)
                c = conn.cursor()
                c.execute("SELECT email FROM admins LIMIT 1")
                row = c.fetchone()
                email = row[0] if row else None
            if email:
                mailer.send_email_async(email, f"Stafflytics Daily Report - {now.strftime('%d %b')}", html)
            sent_today = True
        if now.hour == 0: sent_today = False
        time.sleep(30)

threading.Thread(target=nightly_scheduler, daemon=True).start()

# --- ROUTES ---

@app.route('/')
def index():
    # Force fresh login check
    if 'logged_in' not in session or not session.get('logged_in'):
        return render_template('login.html')
    return render_template('index.html')

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.json
    if database.validate_admin(data.get('username'), data.get('password')):
        session.permanent = False; session['logged_in'] = True; session['username'] = data.get('username')
        return jsonify({"status": "success"})
    return jsonify({"status": "error"}), 401

@app.route('/api/auth/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/api/chat', methods=['POST'])
@login_required
def chat():
    resp = chatbot.process_query(request.json.get('query', ''))
    return jsonify({"response": resp})

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/analytics/engagement')
@login_required
def get_engagement_analytics():
    return jsonify(database.get_service_engagement_analytics())

@app.route('/api/analytics/wellbeing')
@login_required
def get_wellbeing_analytics():
    return jsonify(database.get_wellbeing_data())

@app.route('/api/analytics/loyalty')
@login_required
def get_loyalty_analytics():
    return jsonify(database.get_loyalty_analytics())

@app.route('/api/analytics/performance')
@login_required
def get_performance_analytics():
    return jsonify(database.get_performance_rankings())

@app.route('/api/analytics/optimization')
@login_required
def get_optimization_analytics():
    return jsonify(database.get_shift_optimization_data())

@app.route('/api/sales/add', methods=['POST'])
@login_required
def record_sale_transaction():
    data = request.json
    database.record_sale(data.get('staff_id'), data.get('amount'))
    return jsonify({"status": "success"})

@app.route('/api/status')
@login_required
def get_status():
    global camera_online, system_initializing
    
    # Always fetch DB stats even if AI/Camera is still starting
    try:
        summ = database.get_dashboard_summary()
        cst = database.get_monthly_customer_stats()
        roster = database.get_todays_shift_roster()
    except Exception as e:
        print(f"[DB STATUS ERROR] {e}")
        summ = {"payroll_monthly": 0, "late_today": 0, "incidents_today": 0}
        cst = {"avg_visit": 0, "monthly_total": 0}
        roster = []

    # If AI is still loading or failed, return partial data
    if engine is None or system_initializing:
        return jsonify({
            "initializing": system_initializing,
            "init_status": init_status,
            "count": 0, "camera_online": camera_online,
            "avg_efficiency": summ["avg_efficiency"], "late_today": summ["late_today"],
            "incidents_today": summ["incidents_today"], "customer_avg": cst["avg_visit"],
            "repeat_customers": cst.get("repeat_customers", 0),
            "roster": roster, "active_list": [], "monthly_customers": cst.get("monthly_total", 0)
        })

    stf = engine.get_active_staff() if engine else []
    
    # Process pending security emails and telegrams
    new_alert = False
    alert_name = ""
    alert_zone = ""
    for tid, state in engine.person_states.items():
        if "needs_security_email" in state:
            zone_name = state.pop("needs_security_email")
            new_alert = True
            alert_name = state.get('name', 'Unknown')
            alert_zone = zone_name
            
            # 1. Email
            html = mailer.get_security_alert_template(alert_name, alert_zone)
            mailer.send_email_async(mailer.OWNER_EMAIL, f"SECURITY ALERT: Unauthorized Entry in {alert_zone}", html)
            
            # 2. Telegram
            msg = f"⚠️ *SECURITY ALERT*\nName: {alert_name}\nZone: {alert_zone}\nTime: {datetime.now().strftime('%H:%M:%S')}"
            threading.Thread(target=send_telegram_alert, args=(msg,), daemon=True).start()

    return jsonify({
        "initializing": False,
        "count": len(stf), "camera_online": camera_online,
        "avg_efficiency": summ["avg_efficiency"], "late_today": summ["late_today"],
        "incidents_today": summ["incidents_today"], "customer_avg": cst["avg_visit"],
        "repeat_customers": cst.get("repeat_customers", 0),
        "new_alert": new_alert,
        "roster": database.get_todays_shift_roster(),
        "active_list": stf,
        "alert_details": {"name": alert_name, "zone": alert_zone} if new_alert else None,
        "monthly_customers": cst.get("monthly_total", 0)
    })

@app.route('/api/camera/refresh')
@login_required
def refresh_camera():
    global camera_stream
    if camera_stream:
        camera_stream.online = False # Forces update loop to re-probe
        return jsonify({"status": "success", "message": "Camera re-synchronization triggered."})
    return jsonify({"status": "error", "message": "Camera stream not initialized."}), 500

@app.route('/api/export/attendance/<format>')
@login_required
def export_attendance(format):
    month = request.args.get('month')
    year = request.args.get('year')
    data = database.get_monthly_attendance(month, year)
    summary = database.get_comprehensive_summary()
    
    if format == 'excel':
        buf = export_engine.generate_attendance_excel(data)
        return send_file(buf, as_attachment=True, download_name=f"Stafflytics_Report_{datetime.now().strftime('%Y%m%d')}.xlsx")
    elif format == 'pdf':
        pdf_content = export_engine.generate_classy_pdf(summary, data)
        buf = io.BytesIO(pdf_content)
        return send_file(buf, as_attachment=True, download_name=f"Stafflytics_Executive_Report.pdf", mimetype='application/pdf')
    return "Invalid format", 400

@app.route('/api/reports/attendance')
@login_required
def get_attendance_report():
    data = database.get_monthly_attendance(request.args.get('month'), request.args.get('year'))
    report = []
    for row in data:
        entry, exit_t, name, role, hours, sal_type, is_late, active_sec = row
        eff = round((active_sec / (hours * 3600) * 100), 1) if hours > 0 else 0
        report.append({"date":str(entry)[:10], "in":str(entry)[11:16], "out":str(exit_t)[11:16] if exit_t else "--:--", 
                       "name":name, "role":role, "hours":round(hours,1), "efficiency": f"{eff}%", "status": "Late" if is_late else ("Completed" if exit_t else "Active")})
    return jsonify(report)

@app.route('/api/staff/stats/<staff_id>')
@login_required
def get_staff_stats(staff_id):
    return jsonify(database.get_staff_stats(staff_id))

@app.route('/api/analytics/customers')
@login_required
def get_customer_analytics():
    return jsonify(database.get_monthly_customer_stats())

@app.route('/api/export/custom')
@login_required
def export_custom_report():
    period = request.args.get('period', 'daily') # daily, weekly
    fmt = request.args.get('format', 'pdf') # pdf, excel
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    if period == 'weekly':
        start_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        title = "Weekly Business Intelligence"
    else:
        start_date = end_date
        title = "Daily Operations"
        
    data = database.get_period_report_data(start_date, end_date)
    alerts = database.get_period_alerts(start_date, end_date)
    
    if fmt == 'excel':
        output = export_engine.generate_comprehensive_excel(data)
        return send_file(output, as_attachment=True, download_name=f"Stafflytics_{period}_Report.xlsx")
    else:
        output = export_engine.generate_comprehensive_pdf(title, data['summary'], data['details'], alerts)
        buf = io.BytesIO(output)
        return send_file(buf, as_attachment=True, download_name=f"Stafflytics_{period}_Report.pdf", mimetype='application/pdf')

@app.route('/api/staff/all')
@login_required
def get_all_registered_staff():
    # id, name, role, shift_start, hourly_rate, face_encoding, shift, salary_type
    return jsonify([{"id":r[0], "name":r[1], "role":r[2], "shift_time":r[3], "rate":r[4], "shift":r[6], "salary_type": r[7]} for r in database.get_all_staff()])

@app.route('/api/staff/update/<staff_id>', methods=['POST'])
@login_required
def update_staff_detail(staff_id):
    data = request.json
    database.update_staff(staff_id, data['name'], data['role'], data['shift_time'], data['shift'], data['rate'], data.get('salary_type', 'Monthly'))
    engine.load_known_faces()
    return jsonify({"status": "success"})

@app.route('/api/staff/delete/<staff_id>', methods=['DELETE'])
@login_required
def delete_staff(staff_id):
    database.delete_staff(staff_id)
    engine.load_known_faces()
    return jsonify({"status": "success"})

@app.route('/api/register', methods=['POST'])
@login_required
def register_staff():
    data = request.json
    try:
        import face_recognition # Local import
        header, encoded = data['image'].split(",", 1)
        img = Image.open(io.BytesIO(base64.b64decode(encoded)))
        enc = face_recognition.face_encodings(np.array(img.convert('RGB')))
        if not enc: return jsonify({"status": "error", "message": "No face detected"}), 400
        database.add_staff(data['id'], data['name'], data['role'], pickle.dumps(enc[0]), 
                          data.get('shift_time', '10:00'), data.get('shift', 'Morning'), data.get('rate', 500), data.get('salary_type', 'Monthly'))
        engine.load_known_faces()
        return jsonify({"status": "success"})
    except Exception as e: return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/events/all')
@login_required
def get_events():
    return jsonify([{"date":r[0], "type":r[1], "intensity":r[2]} for r in database.get_events()])

@app.route('/api/events/add', methods=['POST'])
@login_required
def add_event():
    data = request.json
    database.add_event(data['date'], data.get('type', 'Peak Day'), data.get('intensity', 'High'))
    return jsonify({"status": "success"})

@app.route('/api/events/delete/<date>', methods=['DELETE'])
@login_required
def delete_event(date):
    database.delete_event(date)
    return jsonify({"status": "success"})

@app.route('/api/zones/update', methods=['POST'])
@login_required
def update_zones():
    data = request.json
    database.save_zone_config(data['name'], str(data['points']), ",".join(data.get('unauthorized', [])))
    engine.reload_zones()
    return jsonify({"status": "success"})

@app.route('/api/settings/emails', methods=['GET', 'POST'])
@login_required
def email_settings():
    if request.method == 'POST':
        database.update_system_settings(request.json)
        sync_mailer_config()
        return jsonify({"status": "success"})
    return jsonify(database.get_system_settings())

import sqlite3
if __name__ == '__main__':
    app.run(debug=True, port=5000, threaded=True, use_reloader=False)
