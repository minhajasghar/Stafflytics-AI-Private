import pandas as pd
from fpdf import FPDF
import os
from datetime import datetime
import io

class ExportEngine:
    @staticmethod
    def generate_attendance_excel(data):
        """Generates a professional Excel file for attendance"""
        # data: entry, exit, name, role, hours, sal_type, is_late, active_sec
        df = pd.DataFrame(data, columns=["Timestamp", "Exit", "Name", "Role", "Hours", "Salary Type", "Is Late", "Active Sec"])
        df['Date'] = pd.to_datetime(df['Timestamp']).dt.date
        df['In Time'] = pd.to_datetime(df['Timestamp']).dt.time
        df['Efficiency %'] = (df['Active Sec'] / (df['Hours'] * 3600)) * 100
        df['Efficiency %'] = df['Efficiency %'].fillna(0).round(1)
        
        # Cleanup
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df[["Date", "Name", "Role", "In Time", "Hours", "Efficiency %", "Is Late"]].to_excel(writer, index=False, sheet_name="Attendance")
        
        output.seek(0)
        return output

    @staticmethod
    def generate_classy_pdf(summary, staff_data):
        """Generates a useful and elegant PDF report for restaurant owners"""
        pdf = FPDF()
        pdf.add_page()
        
        # Branding Header
        pdf.set_fill_color(30, 27, 75) # var(--primary)
        pdf.rect(0, 0, 210, 40, 'F')
        
        pdf.set_font("Arial", 'B', 24)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 20, "Stafflytics AI", ln=True, align='C')
        pdf.set_font("Arial", '', 12)
        pdf.cell(0, 5, f"Stafflytics Intelligence Report - {datetime.now().strftime('%d %b %Y')}", ln=True, align='C')
        
        pdf.ln(25)
        
        # Dashboard Overview Section
        pdf.set_text_color(31, 41, 55)
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "Daily Performance Overview", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)
        
        pdf.set_font("Arial", '', 12)
        pdf.cell(95, 10, f"Total Staff Present: {summary['staff_present']}", ln=0)
        pdf.cell(95, 10, f"Avg Team Efficiency: {summary['avg_efficiency']}%", ln=1)
        pdf.cell(95, 10, f"Customer Visitors: {summary['customers']}", ln=0)
        pdf.cell(95, 10, f"Avg Customer Duration: {summary['avg_stay']} mins", ln=1)
        
        pdf.ln(15)
        
        # Staff Details Table
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(0, 10, "Staff Attendance & Performance Record", ln=True)
        
        # Table Header
        pdf.set_fill_color(241, 245, 249)
        pdf.set_font("Arial", 'B', 10)
        pdf.cell(50, 10, "Name", 1, 0, 'C', True)
        pdf.cell(40, 10, "Role", 1, 0, 'C', True)
        pdf.cell(30, 10, "Work Hours", 1, 0, 'C', True)
        pdf.cell(30, 10, "Salary Type", 1, 0, 'C', True)
        pdf.cell(40, 10, "Efficiency %", 1, 1, 'C', True)
        
        # Table Rows
        pdf.set_font("Arial", '', 10)
        for row in staff_data:
            # row: entry, exit, name, role, hours, sal_type, is_late, active_sec
            eff = (row[7] / (row[4] * 3600)) * 100 if row[4] > 0 else 0
            pdf.cell(50, 8, str(row[2]), 1)
            pdf.cell(40, 8, str(row[3]), 1)
            pdf.cell(30, 8, f"{row[4]:.1f}h", 1, 0, 'C')
            pdf.cell(30, 8, str(row[5]), 1, 0, 'C')
            pdf.cell(40, 8, f"{eff:.1f}%", 1, 1, 'C')

        pdf.ln(20)
        
        # Footer
        pdf.set_y(-30)
        pdf.set_font("Arial", 'I', 8)
        pdf.set_text_color(156, 163, 175)
        pdf.cell(0, 10, "Produced by Stafflytics AI Intelligence Suite. Confidential & Proprietary.", align='C')
        
        return pdf.output()

    @staticmethod
    def generate_comprehensive_excel(data):
        """Generates a multi-column Excel report with all session details"""
        df = pd.DataFrame(data['details'])
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name="Full Report")
        output.seek(0)
        return output

    @staticmethod
    def generate_comprehensive_pdf(title, summary, details, alerts):
        """Generates a premium business intelligence report"""
        pdf = FPDF()
        pdf.add_page()
        
        # Header
        pdf.set_fill_color(30, 27, 75)
        pdf.rect(0, 0, 210, 45, 'F')
        pdf.set_font("Arial", 'B', 24)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 20, "Stafflytics AI", ln=True, align='C')
        pdf.set_font("Arial", '', 14)
        pdf.cell(0, 10, f"{title} Management Report", ln=True, align='C')
        pdf.ln(20)

        # Executive Summary
        pdf.set_text_color(31, 41, 55)
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "Executive Summary", ln=True)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)
        
        pdf.set_font("Arial", '', 12)
        pdf.cell(95, 10, f"Total Staff Active: {summary.get('staff_count', 0)}", ln=0)
        pdf.cell(95, 10, f"Avg Team Efficiency: {summary.get('avg_efficiency', 0)}%", ln=1)
        pdf.cell(95, 10, f"Total Working Hours: {summary.get('total_hours', 0)}h", ln=0)
        pdf.cell(95, 10, f"Security Incidents: {len(alerts)}", ln=1)
        pdf.cell(95, 10, f"Monthly Visitors: {summary.get('monthly_customers', 'N/A')}", ln=0)
        
        pdf.ln(10)

        # Detailed Attendance Table
        pdf.set_font("Arial", 'B', 16)
        pdf.cell(0, 10, "Attendance & Performance Details", ln=True)
        pdf.ln(2)
        
        # Table Header
        pdf.set_fill_color(241, 245, 249)
        pdf.set_font("Arial", 'B', 9)
        pdf.cell(20, 10, "Date", 1, 0, 'C', True)
        pdf.cell(40, 10, "Name", 1, 0, 'C', True)
        pdf.cell(40, 10, "Role", 1, 0, 'C', True)
        pdf.cell(30, 10, "Work Hours", 1, 0, 'C', True)
        pdf.cell(35, 10, "Efficiency %", 1, 1, 'C', True)

        # Table Rows
        pdf.set_font("Arial", '', 9)
        for d in details:
            pdf.cell(20, 8, str(d.get('date', 'N/A')), 1)
            pdf.cell(40, 8, str(d.get('name', 'N/A')), 1)
            pdf.cell(40, 8, str(d.get('role', 'N/A')), 1)
            pdf.cell(30, 8, f"{d.get('hours', 0)}h", 1, 0, 'C')
            pdf.cell(35, 8, f"{d.get('performance', 0)}%", 1, 1, 'C')

        # Security Alerts Section (if any)
        if alerts:
            pdf.ln(10)
            pdf.set_font("Arial", 'B', 16)
            pdf.set_text_color(239, 68, 68) # Red
            pdf.cell(0, 10, "Security Alerts Summary", ln=True)
            pdf.set_font("Arial", '', 9)
            pdf.set_text_color(31, 41, 55)
            for a in alerts:
                pdf.cell(0, 8, f"[{a['time']}] {a['name']} - {a['zone']}: {a['details']}", ln=True)

        # Footer
        pdf.set_y(-25)
        pdf.set_font("Arial", 'I', 8)
        pdf.set_text_color(156, 163, 175)
        pdf.cell(0, 10, "Confidential AI Report - Stafflytics Analytics Intelligence Suite", align='C')
        
        return pdf.output()

export_engine = ExportEngine()
