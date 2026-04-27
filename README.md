# HospitalQ — Digital Queue Management System

A web-based hospital queue management system built with Flask that allows patients to book slots remotely, track their queue position in real time, and receive printable tickets. Doctors and admins manage queues and departments through a dedicated panel.

---

## Problem Statement

Long waiting times in clinics and hospitals lead to patient frustration, overcrowded waiting rooms, and inefficient use of medical staff time. HospitalQ solves this by allowing patients to book their slot remotely and monitor their queue position from anywhere — arriving only when their turn is near.

---

## Features

### Patient
- Register and log in securely
- Book a queue slot for any department
- View live ticket status with queue position and estimated wait time
- Add appointment notes when booking
- Cancel active ticket
- Download or print ticket as a PDF
- View full visit history with wait time analytics

### Doctor
- View and manage the queue for all departments
- Call the next patient with one click
- See patient names and appointment notes in the queue
- Track patients served today

### Admin
- All doctor permissions
- Create and delete doctor/admin/patient accounts
- Add, rename and delete hospital departments
- View department-wise ticket volume chart
- Search patients in the waiting queue

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3, Flask |
| Database | SQLite via Flask-SQLAlchemy |
| Auth | Flask-Login, Werkzeug password hashing |
| Forms | Flask-WTF, WTForms |
| PDF Generation | ReportLab |
| Frontend | Bootstrap 5, custom CSS |
| Icons | Bootstrap Icons |
| Charts | Chart.js |

---

## Project Structure

```
queue_system/
├── app.py                  # Routes and application logic
├── models.py               # Database models (User, Department, QueueEntry)
├── forms.py                # WTForms form definitions
├── requirements.txt        # Python dependencies
├── static/
│   └── style.css           # Custom CSS with dark/light theme
├── templates/
│   ├── base.html           # Base layout with navbar and theme toggle
│   ├── index.html          # Landing page
│   ├── login.html          # Login page
│   ├── register.html       # Registration page
│   ├── dashboard.html      # Patient dashboard
│   ├── queue_status.html   # Live queue board
│   ├── admin.html          # Doctor/admin panel
│   ├── history.html        # Patient visit history
│   ├── manage_users.html   # Admin user management
│   └── manage_departments.html  # Admin department management
└── instance/
    └── queue.db            # SQLite database (auto-created)
```

---

## Installation & Setup

### Prerequisites
- Python 3.8 or higher
- pip

### Steps

**1. Clone or download the project:**
```bash
cd queue_system
```

**2. Create and activate a virtual environment:**
```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS/Linux
python -m venv .venv
source .venv/bin/activate
```

**3. Install dependencies:**
```bash
pip install -r requirements.txt
```

**4. Run the application:**
```bash
python app.py
```

**5. Open your browser and go to:**
```
http://127.0.0.1:5000
```

**6. Seed the database (first run only):**
```
http://127.0.0.1:5000/seed
```

This creates 5 default departments and the default admin and doctor accounts below.

---

## Default Accounts

| Role | Email | Password |
|---|---|---|
| Admin | admin@hospital.com | admin123 |
| Doctor | doctor@hospital.com | doctor123 |

> **Note:** These credentials are for development and demonstration only.

---

## Usage Guide

### As a Patient
1. Register a new account at `/register`
2. Log in and go to the Dashboard
3. Select a department and book a slot
4. Your ticket number, queue position, and estimated wait time will display
5. Click **Download** or **Print** to get a physical copy of your ticket
6. Monitor the Live Queue board to track your position
7. Cancel your ticket from the dashboard if needed

### As a Doctor
1. Log in with doctor credentials
2. You are redirected automatically to the Admin Panel
3. Select a department tab to view its queue
4. Click **Call Next** to serve the next patient
5. The system automatically marks the previous patient as done

### As an Admin
1. Log in with admin credentials
2. Access **Manage Users** to create doctor or admin accounts
3. Access **Departments** to add, rename, or delete departments
4. Use the search bar to find specific patients in the queue
5. Monitor the department volume chart for today's activity

---

## Security Features

- Passwords hashed with Werkzeug's PBKDF2-SHA256
- CSRF protection on all forms via Flask-WTF
- Role-based access control using custom decorators
- Authenticated routes protected with Flask-Login
- Double-booking prevention at the database query level

---

## Limitations & Future Improvements

| Limitation | Proposed Improvement |
|---|---|
| SQLite single-file DB | Migrate to PostgreSQL for production |
| Auto-refresh every 10s | Implement WebSockets for true real-time updates |
| No notifications | Add SMS/email alerts via Twilio or SendGrid |
| Manual queue reset | Scheduled midnight reset using APScheduler |
| Single hospital | Multi-tenant architecture for hospital networks |
| No audit logs | Track all admin actions with timestamps |

---

## Dependencies

```
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Flask-WTF==1.2.1
WTForms==3.1.1
email-validator==2.1.0
reportlab
```

---

## Screenshots

> Add screenshots of the following pages before submission:
> - Landing page (light and dark mode)
> - Patient dashboard with active ticket
> - Live queue board
> - Admin panel with chart
> - PDF ticket
> - Manage users page

---


Built as an academic project demonstrating full-stack web development with Python Flask, covering authentication, database design, role-based access control, real-time data display, and PDF generation.
