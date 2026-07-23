-- Stafflytics MySQL Database Schema Setup
-- Database Name: stafflytics

CREATE DATABASE IF NOT EXISTS stafflytics;
USE stafflytics;

-- 1. Staff Table
CREATE TABLE IF NOT EXISTS staff (
    id VARCHAR(255) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(255) NOT NULL,
    shift_start VARCHAR(255) DEFAULT '10:00',
    shift VARCHAR(255) DEFAULT 'Morning',
    hourly_rate DOUBLE DEFAULT 500.0,
    salary_type VARCHAR(255) DEFAULT 'Monthly',
    face_encoding LONGBLOB NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. Attendance Table
CREATE TABLE IF NOT EXISTS attendance (
    id INT PRIMARY KEY AUTO_INCREMENT,
    staff_id VARCHAR(255),
    entry_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    exit_time DATETIME,
    status VARCHAR(255) DEFAULT 'Present',
    is_late BOOLEAN DEFAULT 0,
    active_seconds DOUBLE DEFAULT 0,
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. Activity Logs Table
CREATE TABLE IF NOT EXISTS activity_logs (
    id INT PRIMARY KEY AUTO_INCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    staff_id VARCHAR(255),
    zone VARCHAR(255),
    action VARCHAR(255),
    details VARCHAR(1000),
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. Admins Table
CREATE TABLE IF NOT EXISTS admins (
    username VARCHAR(255) PRIMARY KEY,
    password VARCHAR(255) NOT NULL,
    email VARCHAR(255)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Default Admin Insertion
INSERT IGNORE INTO admins (username, password, email) VALUES 
('minhajasghar', 'minhajsahito66', 'admin@stafflytics.ai');

-- 5. Customers Table (Anonymous Sessions)
CREATE TABLE IF NOT EXISTS customers (
    id INT PRIMARY KEY AUTO_INCREMENT,
    entry_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    exit_time DATETIME,
    table_id VARCHAR(255),
    duration_minutes FLOAT,
    customer_id INT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. Customer Profiles Table (Recognized Guests)
CREATE TABLE IF NOT EXISTS customer_profiles (
    id INT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(255) DEFAULT 'New Guest',
    face_encoding LONGBLOB NOT NULL,
    first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
    visit_count INT DEFAULT 1
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 7. Special Events Table
CREATE TABLE IF NOT EXISTS special_events (
    id INT PRIMARY KEY AUTO_INCREMENT,
    date DATE UNIQUE,
    event_type VARCHAR(255) DEFAULT 'General Peak',
    intensity VARCHAR(255) DEFAULT 'High'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 8. Zones Config Table
CREATE TABLE IF NOT EXISTS zones_config (
    name VARCHAR(255) PRIMARY KEY,
    points_json VARCHAR(2000) NOT NULL,
    unauthorized_roles VARCHAR(1000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 9. Sales Table
CREATE TABLE IF NOT EXISTS sales (
    id INT PRIMARY KEY AUTO_INCREMENT,
    staff_id VARCHAR(255),
    amount DOUBLE NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (staff_id) REFERENCES staff(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 10. System Settings Table
CREATE TABLE IF NOT EXISTS system_settings (
    `key` VARCHAR(255) PRIMARY KEY,
    `value` VARCHAR(1000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Default System Settings Insertion
INSERT IGNORE INTO system_settings (`key`, `value`) VALUES
('owner_email', 'admin@stafflytics.ai'),
('sender_email', ''),
('sender_password', ''),
('rtsp_url', '');
