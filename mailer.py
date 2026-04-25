import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import threading

# Configuration (To be filled by the Owner in dashboard settings)
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "" 
SENDER_PASSWORD = "" 
OWNER_EMAIL = ""

def send_email_async(to_email, subject, body_html):
    """Sends email in a background thread to prevent blocking the UI"""
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        return
        
    thread = threading.Thread(target=_send_smtp, args=(to_email, subject, body_html))
    thread.daemon = True
    thread.start()

def _send_smtp(to_email, subject, body_html):
    try:
        msg = MIMEMultipart()
        msg['From'] = f"StaffVision AI <{SENDER_EMAIL}>"
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body_html, 'html'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[Mailer] Successfully sent '{subject}' to {to_email}")
    except Exception as e:
        print(f"[Mailer Error] {e}")

def get_daily_report_template(stats):
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; border: 1px solid #e2e8f0; padding: 20px; border-radius: 10px;">
        <h2 style="color: #1e1b4b;">Stafflytics AI: Daily Business Summary</h2>
        <p style="color: #64748b;">Here is the performance report for today's operations.</p>
        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 20px 0;">
        <div style="display: flex; justify-content: space-between; margin-bottom: 20px;">
            <div style="background: #f8fafc; padding: 15px; border-radius: 8px; flex: 1; margin-right: 10px;">
                <span style="font-size: 12px; color: #64748b;">STAFF PRESENT</span><br>
                <span style="font-size: 18px; font-weight: bold; color: #1e1b4b;">{stats['staff_present']} People ({stats['late_count']} late)</span>
            </div>
            <div style="background: #f8fafc; padding: 15px; border-radius: 8px; flex: 1;">
                <span style="font-size: 12px; color: #64748b;">TOTAL PAYROLL</span><br>
                <span style="font-size: 18px; font-weight: bold; color: #d97706;">Rs. {stats['total_payroll']:,}</span>
            </div>
        </div>
        <div style="background: #f1f5f9; padding: 15px; border-radius: 8px;">
            <h4 style="margin: 0; color: #1e1b4b;">Customer Sentiment</h4>
            <p style="font-size: 14px; margin: 5px 0;">Total Visitors: <strong>{stats['customers']}</strong></p>
            <p style="font-size: 14px; margin: 5px 0;">Avg. Stay Duration: <strong>{stats['avg_stay']} minutes</strong></p>
        </div>
        <p style="font-size: 12px; color: #94a3b8; margin-top: 30px; text-align: center;">Generated automatically by StaffVision AI Signature Edition.</p>
    </div>
    """

def get_late_alert_template(name, time):
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; border: 1px solid #fee2e2; padding: 20px; border-radius: 10px; background: #fff1f2;">
        <h3 style="color: #b91c1c; margin-top: 0;">⚠️ Lateness Alert</h3>
        <p style="color: #7f1d1d;"><strong>{name}</strong> has just clocked in late at <strong>{time}</strong>.</p>
        <p style="font-size: 13px; color: #991b1b;">This follows the shift start time registered in their profile.</p>
    </div>
    """
def get_security_alert_template(name, zone):
    return f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px; border: 2px solid #ef4444; padding: 25px; border-radius: 12px; background: #fef2f2;">
        <h2 style="color: #b91c1c; margin-top: 0; display: flex; align-items: center;">
            <span style="font-size: 24px; margin-right: 10px;">⚠️</span> SECURITY BREACH
        </h2>
        <p style="font-size: 16px; color: #1e1b4b;">StaffVision AI detected an unauthorized entry.</p>
        <div style="background: white; padding: 15px; border-radius: 8px; border: 1px solid #fee2e2;">
            <p style="margin: 5px 0;"><strong>Staff Member:</strong> {name}</p>
            <p style="margin: 5px 0;"><strong>Restricted Zone:</strong> {zone}</p>
            <p style="margin: 5px 0;"><strong>Time:</strong> {datetime.now().strftime('%H:%M:%S')}</p>
        </div>
        <p style="font-size: 13px; color: #991b1b; margin-top: 20px;">
            Immediate action recommended. Please check your Signature Monitor for live visuals.
        </p>
    </div>
    """
