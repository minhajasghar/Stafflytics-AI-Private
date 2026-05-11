# Stafflytics AI | Business Intelligence Suite

Stafflytics AI is a professional-grade, AI-powered business intelligence system designed specifically for the restaurant industry. It leverages computer vision and machine learning to provide real-time staff tracking, automated attendance, security monitoring, and actionable labor analytics.

##  Key Features

- **Intelligence Monitor**: Real-time video stream with AI-driven bounding boxes and activity labeling.
- **Vision Engine**: Powered by YOLOv8-Pose for movement analysis and `face_recognition` for automated staff/customer identification.
- **Automated Attendance**: Seamless clock-in/out based on visual presence, with anti-fake protection and late arrival tracking.
- **Peak Traffic Planner**: Replaces traditional holiday calendars with a high-intensity event planner to manage busy periods like festivals and weddings.
- **Exact Efficiency Metrics**: Measures staff performance based on authorized zone presence, movement intensity, and customer proximity.
- **Security Alerts**: Instant notifications via Email and Telegram for unauthorized entry into restricted zones (e.g., kitchen, office).
- **Salary Administration**: Automated tracking of work hours, efficiency scores, and monthly payroll calculation.
- **Executive Reporting**: Generates professional Daily/Weekly BI reports in PDF and Excel formats.

##  Technology Stack

- **Backend**: Python (Flask)
- **AI/ML**: OpenCV, Ultralytics YOLOv8, Dlib (Face Recognition)
- **Database**: SQLite3 with WAL mode for concurrent access
- **Frontend**: Vanilla HTML5, CSS3 (Modern UI), JavaScript (Async/Fetch)
- **Communication**: SMTP (Email), Telegram Bot API

##  Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/minhajasghar/stafflytics-ai.git
   cd stafflytics-ai
   ```

2. **Install Dependencies**:
   It is recommended to use a virtual environment.
   ```bash
   pip install -r requirements.txt
   ```
   *Note: Ensure you have C++ Build Tools installed for `face_recognition` (dlib).*

3. **Initialize the System**:
   The system will automatically initialize the database and create a default admin account on first run.

4. **Run the Application**:
   ```bash
   python app.py
   ```
   Access the dashboard at `http://127.0.0.1:5000`.

##  Security & Privacy

Stafflytics AI is designed with a **local-first** approach. All video processing and biometric matching happen on your local hardware. No video data is sent to the cloud, ensuring maximum privacy for your staff and guests.

---
*Built for the future of restaurant management.*
