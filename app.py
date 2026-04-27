from flask import Flask, render_template, redirect, url_for, flash, request, make_response
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from flask_socketio import SocketIO, emit, join_room, leave_room
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Department, QueueEntry, doctor_departments
from forms import RegistrationForm, LoginForm, BookSlotForm, CreateUserForm, DepartmentForm, AssignDepartmentsForm, \
    ResetPasswordForm, EditUserForm, ProfileForm
from datetime import datetime, timedelta, timezone
from functools import wraps
import csv
import io
from models import Department
import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
import qrcode
from io import BytesIO
from reportlab.lib.pagesizes import A6
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode.qr import QrCodeWidget

app = Flask(__name__)

# ----- Database Configuration (Railway compatible) -----
DATABASE_URL = os.environ.get('DATABASE_URL')
if DATABASE_URL and DATABASE_URL.startswith('postgres://'):
    # SQLAlchemy requires 'postgresql://' scheme
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

if not DATABASE_URL:
    # Fallback to SQLite for local development
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///queue.db'
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL

# ----- App Configuration -----
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'a-super-secret-dev-key')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialise extensions
db.init_app(app)
csrf = CSRFProtect(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# ----- Create tables automatically on startup -----
# This ensures the database schema exists on Railway without needing manual shell commands.
with app.app_context():
    db.create_all()
    print("✅ Database tables created/verified.")

# ----- Login Manager -----
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# ----- Role decorator -----
def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in roles:
                flash('Access denied.', 'danger')
                return redirect(url_for('index'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ----- SocketIO event: join room -----
@socketio.on('join')
def handle_join(data):
    dept_id = data.get('dept_id')
    if dept_id:
        join_room(f"dept_{dept_id}")

# ---------- Wait time helper functions ----------
def weighted_average_wait_time(dept_id):
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    completed = QueueEntry.query.filter(
        QueueEntry.department_id == dept_id,
        QueueEntry.status == 'done',
        QueueEntry.served_at >= today
    ).order_by(QueueEntry.served_at.asc()).all()
    if not completed:
        return None
    total_weight = 0
    weighted_sum = 0
    for idx, entry in enumerate(completed):
        wait_minutes = (entry.served_at - entry.booked_at).seconds // 60
        weight = 2 if idx >= len(completed) - 10 else 1
        weighted_sum += wait_minutes * weight
        total_weight += weight
    return round(weighted_sum / total_weight) if total_weight > 0 else None

def estimate_wait_time(dept_id, position):
    avg = weighted_average_wait_time(dept_id)
    dept = db.session.get(Department, dept_id)
    base = dept.base_wait_minutes if dept else 15
    per_patient = max(avg, base) if avg is not None else base
    return per_patient * max(position - 1, 0)

def get_wait_time_trend(dept_id, hours=2):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    completed = QueueEntry.query.filter(
        QueueEntry.department_id == dept_id,
        QueueEntry.status == 'done',
        QueueEntry.served_at >= cutoff
    ).order_by(QueueEntry.served_at.asc()).all()
    if not completed:
        return []
    from collections import defaultdict
    buckets = defaultdict(list)
    for entry in completed:
        dt = entry.served_at
        minute_bucket = (dt.minute // 30) * 30
        bucket_key = dt.replace(minute=minute_bucket, second=0, microsecond=0)
        wait = (entry.served_at - entry.booked_at).seconds // 60
        buckets[bucket_key].append(wait)
    trend = []
    for bucket in sorted(buckets.keys()):
        avg_wait = sum(buckets[bucket]) / len(buckets[bucket])
        trend.append({'time': bucket.strftime('%H:%M'), 'wait': round(avg_wait)})
    return trend

def renumber_queue(dept_id):
    waiting = QueueEntry.query.filter_by(
        department_id=dept_id,
        status='waiting'
    ).order_by(QueueEntry.ticket_number.asc()).all()
    for idx, entry in enumerate(waiting, start=1):
        if entry.ticket_number != idx:
            entry.ticket_number = idx
    db.session.commit()

# ---------- Auth routes ----------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        existing = User.query.filter_by(email=form.email.data).first()
        if existing:
            flash('Email already registered.', 'danger')
            return redirect(url_for('register'))
        user = User(
            full_name=form.full_name.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            role='patient'
        )
        db.session.add(user)
        db.session.commit()
        flash('Account created. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid email or password.', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# ----- Seed route (development only) -----
@app.route('/seed')
def seed():
    if Department.query.first():
        flash('Already seeded.', 'info')
        return redirect(url_for('index'))
    departments = ['General OPD', 'Cardiology', 'Pediatrics', 'Orthopedics', 'ENT']
    for name in departments:
        db.session.add(Department(name=name, base_wait_minutes=15))
    if not User.query.filter_by(email='admin@hospital.com').first():
        db.session.add(User(
            full_name='Admin User',
            email='admin@hospital.com',
            password_hash=generate_password_hash('admin123'),
            role='admin',
            is_available=True
        ))
    if not User.query.filter_by(email='doctor@hospital.com').first():
        db.session.add(User(
            full_name='Dr. Default',
            email='doctor@hospital.com',
            password_hash=generate_password_hash('doctor123'),
            role='doctor',
            is_available=True
        ))
    db.session.commit()
    # Assign default doctor to all departments
    doctor = User.query.filter_by(email='doctor@hospital.com').first()
    all_depts = Department.query.all()
    doctor.departments = all_depts
    db.session.commit()
    flash('Database seeded.', 'success')
    return redirect(url_for('index'))

# ---------- Patient routes ----------
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if current_user.role in ['doctor', 'admin']:
        return redirect(url_for('admin'))
    form = BookSlotForm()
    form.department.choices = [(d.id, d.name) for d in Department.query.all()]
    active_ticket = QueueEntry.query.filter_by(
        user_id=current_user.id
    ).filter(QueueEntry.status.in_(['waiting', 'serving'])).first()
    if active_ticket:
        waiting_count = QueueEntry.query.filter_by(
            department_id=active_ticket.department_id,
            status='waiting'
        ).count()
        position = QueueEntry.query.filter_by(
            department_id=active_ticket.department_id,
            status='waiting'
        ).filter(QueueEntry.ticket_number <= active_ticket.ticket_number).count()
        est_wait = estimate_wait_time(active_ticket.department_id, position)
        trend_data = get_wait_time_trend(active_ticket.department_id, hours=2)
        return render_template('dashboard.html',
                               form=form,
                               active_ticket=active_ticket,
                               position=position,
                               total_waiting=waiting_count,
                               est_wait=est_wait,
                               trend_data=trend_data
                               )
    if form.validate_on_submit():
        last = QueueEntry.query.filter_by(
            department_id=form.department.data
        ).order_by(QueueEntry.ticket_number.desc()).first()
        next_ticket = (last.ticket_number + 1) if last else 1
        entry = QueueEntry(
            user_id=current_user.id,
            department_id=form.department.data,
            ticket_number=next_ticket,
            status='waiting',
            notes=form.notes.data or None
        )
        db.session.add(entry)
        db.session.commit()
        socketio.emit('queue_update', {'dept_id': form.department.data}, room=f"dept_{form.department.data}")
        flash(f'Ticket #{next_ticket} booked successfully.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('dashboard.html', form=form, active_ticket=None, position=0, total_waiting=0, est_wait=0,
                           trend_data=[])

@app.route('/queue-status')
@login_required
def queue_status():
    departments = Department.query.all()
    queue_data_list = []
    for dept in departments:
        entries = QueueEntry.query.filter_by(
            department_id=dept.id
        ).filter(
            QueueEntry.status.in_(['waiting', 'serving'])
        ).order_by(QueueEntry.ticket_number.asc()).all()
        queue_data_list.append((dept.id, dept.name, entries))
    return render_template('queue_status.html', queue_data_list=queue_data_list)

@app.route('/api/wait-trend/<int:dept_id>')
@login_required
def wait_trend_api(dept_id):
    trend = get_wait_time_trend(dept_id, hours=2)
    return {'trend': trend}

# ---------- Cancellation routes ----------
@app.route('/cancel-ticket', methods=['POST'])
@login_required
def cancel_ticket():
    ticket = QueueEntry.query.filter_by(
        user_id=current_user.id
    ).filter(QueueEntry.status.in_(['waiting', 'serving'])).first()
    if not ticket:
        flash('No active ticket to cancel.', 'warning')
        return redirect(url_for('dashboard'))
    reason = request.form.get('cancel_reason')
    if not reason:
        flash('Please select a cancellation reason.', 'danger')
        return redirect(url_for('dashboard'))
    dept_id = ticket.department_id
    ticket.status = 'cancelled'
    ticket.cancel_reason = reason
    db.session.commit()
    renumber_queue(dept_id)
    socketio.emit('queue_update', {'dept_id': dept_id}, room=f"dept_{dept_id}")
    flash('Your ticket has been cancelled.', 'info')
    return redirect(url_for('dashboard'))

# ---------- Doctor/Admin routes ----------
@app.route('/admin')
@login_required
@role_required('doctor', 'admin', 'receptionist')
def admin():
    # Determine which departments to show
    if current_user.role in ['admin', 'receptionist']:
        departments = Department.query.all()
    else:  # doctor only
        departments = current_user.departments

    selected_id = request.args.get('dept', type=int)
    search_name = request.args.get('search_name', '').strip()
    search_ticket = request.args.get('search_ticket', '').strip()

    if not selected_id and departments:
        selected_id = departments[0].id
    elif not selected_id:
        selected_id = None
        if departments:
            selected_id = departments[0].id
        else:
            flash('No departments assigned to you.', 'danger')
            return redirect(url_for('dashboard'))

    # Base query for waiting entries
    waiting_query = QueueEntry.query.filter_by(
        department_id=selected_id,
        status='waiting'
    )

    if search_name:
        waiting_query = waiting_query.join(User).filter(User.full_name.ilike(f'%{search_name}%'))
    if search_ticket:
        waiting_query = waiting_query.filter(QueueEntry.ticket_number == search_ticket)

    waiting = waiting_query.order_by(QueueEntry.ticket_number.asc()).all()

    # Currently serving
    serving = QueueEntry.query.filter_by(
        department_id=selected_id,
        status='serving'
    ).first()

    # Done today count
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    done_today = QueueEntry.query.filter_by(
        department_id=selected_id,
        status='done'
    ).filter(QueueEntry.served_at >= today_start).count()

    # Department stats for bar chart
    dept_stats = []
    for d in departments:
        count = QueueEntry.query.filter_by(
            department_id=d.id
        ).filter(QueueEntry.booked_at >= today_start).count()
        dept_stats.append({'name': d.name, 'count': count})

    # Peak hours data for selected department
    peak_hours = []
    for hour in range(24):
        start = today_start + timedelta(hours=hour)
        end = start + timedelta(hours=1)
        count = QueueEntry.query.filter(
            QueueEntry.department_id == selected_id,
            QueueEntry.booked_at >= start,
            QueueEntry.booked_at < end
        ).count()
        peak_hours.append({'hour': f'{hour:02d}:00', 'count': count})

    # Doctor performance stats
    doctor_stats = None
    if current_user.role == 'doctor' and current_user.is_available is not None:
        served_today = QueueEntry.query.filter(
            QueueEntry.served_by == current_user.id,
            QueueEntry.status == 'done',
            QueueEntry.served_at >= today_start
        ).all()
        total_patients = len(served_today)
        patients_per_hour = round(total_patients / 8, 1) if total_patients > 0 else 0
        if total_patients > 0:
            total_wait = sum((e.served_at - e.booked_at).seconds // 60 for e in served_today)
            avg_wait = round(total_wait / total_patients)
        else:
            avg_wait = 0
        doctor_stats = {
            'patients_today': total_patients,
            'patients_per_hour': patients_per_hour,
            'avg_wait_minutes': avg_wait
        }

    return render_template('admin.html',
                           departments=departments,
                           selected_id=selected_id,
                           waiting=waiting,
                           serving=serving,
                           done_today=done_today,
                           search_name=search_name,
                           search_ticket=search_ticket,
                           dept_stats=dept_stats,
                           peak_hours=peak_hours,
                           doctor_stats=doctor_stats,
                           is_available=current_user.is_available if current_user.role == 'doctor' else None
                           )

@app.route('/call-next/<int:dept_id>', methods=['POST'])
@login_required
@role_required('doctor', 'admin')
def call_next(dept_id):
    if current_user.role == 'doctor' and not current_user.is_available:
        flash('You are currently paused. Unpause to call next patient.', 'warning')
        return redirect(url_for('admin', dept=dept_id))

    current_serving = QueueEntry.query.filter_by(
        department_id=dept_id,
        status='serving'
    ).first()
    if current_serving:
        current_serving.status = 'done'
        current_serving.served_at = datetime.now(timezone.utc)
        current_serving.served_by = current_user.id

    next_patient = QueueEntry.query.filter_by(
        department_id=dept_id,
        status='waiting'
    ).order_by(QueueEntry.ticket_number.asc()).first()

    if next_patient:
        next_patient.status = 'serving'
        db.session.commit()
        socketio.emit('queue_update', {'dept_id': dept_id}, room=f"dept_{dept_id}")
        flash(f'Now serving Ticket #{next_patient.ticket_number}.', 'success')
    else:
        db.session.commit()
        flash('No more patients in queue.', 'info')
    return redirect(url_for('admin', dept=dept_id))

@app.route('/call-multiple/<int:dept_id>/<int:count>', methods=['POST'])
@login_required
@role_required('doctor', 'admin')
def call_multiple(dept_id, count):
    if current_user.role == 'doctor' and not current_user.is_available:
        flash('You are paused. Unpause to call patients.', 'warning')
        return redirect(url_for('admin', dept=dept_id))
    if count < 1 or count > 10:
        flash('Count must be between 1 and 10.', 'danger')
        return redirect(url_for('admin', dept=dept_id))

    current_serving = QueueEntry.query.filter_by(
        department_id=dept_id,
        status='serving'
    ).first()
    if current_serving:
        current_serving.status = 'done'
        current_serving.served_at = datetime.now(timezone.utc)
        current_serving.served_by = current_user.id

    next_patients = QueueEntry.query.filter_by(
        department_id=dept_id,
        status='waiting'
    ).order_by(QueueEntry.ticket_number.asc()).limit(count).all()

    if not next_patients:
        db.session.commit()
        flash('No waiting patients.', 'info')
        return redirect(url_for('admin', dept=dept_id))

    first = next_patients[0]
    first.status = 'serving'
    db.session.commit()
    socketio.emit('queue_update', {'dept_id': dept_id}, room=f"dept_{dept_id}")
    flash(f'Called #{first.ticket_number}. There are {len(next_patients) - 1} more waiting.', 'success')
    return redirect(url_for('admin', dept=dept_id))

@app.route('/reset-queue/<int:dept_id>', methods=['POST'])
@login_required
@role_required('admin')
def reset_queue(dept_id):
    waiting = QueueEntry.query.filter_by(
        department_id=dept_id,
        status='waiting'
    ).all()
    for entry in waiting:
        entry.status = 'cancelled'
        entry.cancel_reason = 'reset_by_admin'
    db.session.commit()
    renumber_queue(dept_id)
    socketio.emit('queue_update', {'dept_id': dept_id}, room=f"dept_{dept_id}")
    flash(f'Reset queue for department: {len(waiting)} tickets cancelled.', 'info')
    return redirect(url_for('admin', dept=dept_id))

@app.route('/export-csv/<int:dept_id>')
@login_required
@role_required('doctor', 'admin', 'receptionist')
def export_csv(dept_id):
    waiting = QueueEntry.query.filter_by(
        department_id=dept_id,
        status='waiting'
    ).order_by(QueueEntry.ticket_number.asc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Ticket Number', 'Patient Name', 'Booked At', 'Notes'])
    for entry in waiting:
        writer.writerow([
            entry.ticket_number,
            entry.patient.full_name,
            entry.booked_at.strftime('%Y-%m-%d %H:%M:%S'),
            entry.notes or ''
        ])

    response = make_response(output.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename=waiting_list_dept_{dept_id}.csv'
    response.headers['Content-type'] = 'text/csv'
    return response

@app.route('/admin/no-show/<int:entry_id>', methods=['POST'])
@login_required
@role_required('doctor', 'admin')
def mark_no_show(entry_id):
    entry = db.session.get(QueueEntry, entry_id)
    if not entry or entry.status != 'waiting':
        flash('Can only mark waiting patients as no-show.', 'danger')
        return redirect(url_for('admin', dept=entry.department_id if entry else 0))
    dept_id = entry.department_id
    entry.status = 'cancelled'
    entry.cancel_reason = 'no-show'
    db.session.commit()
    renumber_queue(dept_id)
    socketio.emit('queue_update', {'dept_id': dept_id}, room=f"dept_{dept_id}")
    flash(f'Patient {entry.patient.full_name} marked as no-show.', 'info')
    return redirect(url_for('admin', dept=dept_id))

@app.route('/doctor/toggle-availability', methods=['POST'])
@login_required
@role_required('doctor')
def toggle_availability():
    current_user.is_available = not current_user.is_available
    db.session.commit()
    status = 'available' if current_user.is_available else 'paused'
    flash(f'You are now {status}.', 'success')
    return redirect(url_for('admin'))

# ---------- Admin user management ----------
@app.route('/admin/users')
@login_required
@role_required('admin')
def manage_users():
    users = User.query.order_by(User.role.asc(), User.full_name.asc()).all()
    form = CreateUserForm()
    all_departments = Department.query.all()
    return render_template('manage_users.html', users=users, form=form, all_departments=all_departments)

@app.route('/admin/users/assign-departments/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def assign_departments(user_id):
    user = db.session.get(User, user_id)
    if not user or user.role != 'doctor':
        flash('Only doctors can be assigned to departments.', 'danger')
        return redirect(url_for('manage_users'))
    dept_ids = request.form.getlist('departments')
    dept_ids = [int(x) for x in dept_ids if x]
    user.departments = Department.query.filter(Department.id.in_(dept_ids)).all()
    db.session.commit()
    flash(f'Departments assigned to {user.full_name}.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/admin/users/create', methods=['POST'])
@login_required
@role_required('admin')
def create_user():
    form = CreateUserForm()
    if form.validate_on_submit():
        existing = User.query.filter_by(email=form.email.data).first()
        if existing:
            flash('Email already registered.', 'danger')
            return redirect(url_for('manage_users'))
        user = User(
            full_name=form.full_name.data,
            email=form.email.data,
            password_hash=generate_password_hash(form.password.data),
            role=form.role.data,
            is_available=True
        )
        db.session.add(user)
        db.session.commit()
        flash(f'{form.role.data.capitalize()} account created for {form.full_name.data}.', 'success')
    return redirect(url_for('manage_users'))

@app.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def edit_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('manage_users'))
    form = EditUserForm(obj=user)
    if form.validate_on_submit():
        user.full_name = form.full_name.data
        user.email = form.email.data
        user.role = form.role.data
        db.session.commit()
        flash(f'User {user.full_name} updated successfully.', 'success')
        return redirect(url_for('manage_users'))
    return render_template('edit_user.html', form=form, user=user)

@app.route('/admin/users/reset-password/<int:user_id>', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def reset_user_password(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('manage_users'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.password_hash = generate_password_hash(form.new_password.data)
        db.session.commit()
        flash(f'Password reset for {user.full_name}.', 'success')
        return redirect(url_for('manage_users'))
    return render_template('reset_password.html', form=form, user=user)

@app.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('manage_users'))
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('manage_users'))
    db.session.delete(user)
    db.session.commit()
    flash(f'{user.full_name} has been removed.', 'info')
    return redirect(url_for('manage_users'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.full_name = form.full_name.data
        current_user.phone = form.phone.data
        current_user.emergency_contact = form.emergency_contact.data
        current_user.emergency_phone = form.emergency_phone.data
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html', form=form)

# ---------- Department management routes ----------
@app.route('/admin/departments')
@login_required
@role_required('admin')
def manage_departments():
    departments = Department.query.order_by(Department.name.asc()).all()
    form = DepartmentForm()
    return render_template('manage_departments.html', departments=departments, form=form)

@app.route('/admin/departments/create', methods=['POST'])
@login_required
@role_required('admin')
def create_department():
    form = DepartmentForm()
    if form.validate_on_submit():
        existing = Department.query.filter_by(name=form.name.data).first()
        if existing:
            flash('Department already exists.', 'danger')
            return redirect(url_for('manage_departments'))
        dept = Department(
            name=form.name.data,
            base_wait_minutes=form.base_wait_minutes.data
        )
        db.session.add(dept)
        db.session.commit()
        flash(f'Department "{form.name.data}" created.', 'success')
    return redirect(url_for('manage_departments'))

@app.route('/admin/departments/delete/<int:dept_id>', methods=['POST'])
@login_required
@role_required('admin')
def delete_department(dept_id):
    dept = db.session.get(Department, dept_id)
    if not dept:
        flash('Department not found.', 'danger')
        return redirect(url_for('manage_departments'))
    active = QueueEntry.query.filter_by(
        department_id=dept_id
    ).filter(QueueEntry.status.in_(['waiting', 'serving'])).count()
    if active > 0:
        flash(f'Cannot delete "{dept.name}" — {active} active patients in queue.', 'danger')
        return redirect(url_for('manage_departments'))
    db.session.delete(dept)
    db.session.commit()
    flash(f'Department "{dept.name}" deleted.', 'info')
    return redirect(url_for('manage_departments'))

@app.route('/admin/departments/rename/<int:dept_id>', methods=['POST'])
@login_required
@role_required('admin')
def rename_department(dept_id):
    dept = db.session.get(Department, dept_id)
    if not dept:
        flash('Department not found.', 'danger')
        return redirect(url_for('manage_departments'))
    name = request.form.get('name', '').strip()
    if not name:
        flash('Name cannot be empty.', 'danger')
        return redirect(url_for('manage_departments'))
    existing = Department.query.filter_by(name=name).first()
    if existing and existing.id != dept_id:
        flash('A department with that name already exists.', 'danger')
        return redirect(url_for('manage_departments'))
    dept.name = name
    db.session.commit()
    flash(f'Department renamed to "{name}".', 'success')
    return redirect(url_for('manage_departments'))

@app.route('/admin/departments/update_base/<int:dept_id>', methods=['POST'])
@login_required
@role_required('admin')
def update_department_base(dept_id):
    dept = db.session.get(Department, dept_id)
    if not dept:
        flash('Department not found.', 'danger')
        return redirect(url_for('manage_departments'))
    new_base = request.form.get('base_wait_minutes', type=int)
    if new_base and 1 <= new_base <= 120:
        dept.base_wait_minutes = new_base
        db.session.commit()
        flash(f'Base wait time for {dept.name} updated to {new_base} minutes.', 'success')
    else:
        flash('Invalid base time (must be 1-120).', 'danger')
    return redirect(url_for('manage_departments'))

# ---------- PDF and History ----------
@app.route('/ticket/pdf')
@login_required
def ticket_pdf():
    from reportlab.lib.pagesizes import A6
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode.qr import QrCodeWidget
    from reportlab.graphics import renderPDF
    from reportlab.graphics.shapes import Drawing
    from io import BytesIO

    active_ticket = QueueEntry.query.filter_by(
        user_id=current_user.id
    ).filter(QueueEntry.status.in_(['waiting', 'serving'])).first()

    if not active_ticket:
        flash('No active ticket to print.', 'warning')
        return redirect(url_for('dashboard'))

    waiting_count = QueueEntry.query.filter_by(
        department_id=active_ticket.department_id,
        status='waiting'
    ).count()
    position = QueueEntry.query.filter_by(
        department_id=active_ticket.department_id,
        status='waiting'
    ).filter(QueueEntry.ticket_number <= active_ticket.ticket_number).count()
    est_wait = estimate_wait_time(active_ticket.department_id, position)

    hospital_name = "City General Hospital"
    hospital_address = "123 Health Avenue, Medical District, City, 12345"
    hospital_phone = "+1 (555) 123-4567"
    emergency = "In case of emergency, please contact the reception desk immediately."

    base_url = request.url_root.rstrip('/')
    qr_data = f"{base_url}/checkin?ticket={active_ticket.ticket_number}"

    buffer = BytesIO()
    w, h = A6
    c = canvas.Canvas(buffer, pagesize=A6)

    primary = colors.HexColor('#0066CC')
    white = colors.white
    dark = colors.HexColor('#1A202C')
    muted = colors.HexColor('#64748B')
    success = colors.HexColor('#00A86B')
    warning = colors.HexColor('#F59E0B')

    c.setFillColor(primary)
    c.roundRect(5*mm, h - 28*mm, w - 10*mm, 22*mm, 4*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 16)
    c.drawCentredString(w/2, h - 14*mm, hospital_name)
    c.setFont('Helvetica', 6)
    c.drawCentredString(w/2, h - 19*mm, 'QUEUE MANAGEMENT TICKET')

    c.setStrokeColor(colors.HexColor('#E2E8F0'))
    c.setLineWidth(0.5)
    c.line(5*mm, h - 31*mm, w - 5*mm, h - 31*mm)

    c.setFillColor(muted)
    c.setFont('Helvetica', 7)
    c.drawCentredString(w/2, h - 36*mm, 'YOUR TICKET NUMBER')
    c.setFillColor(primary)
    c.setFont('Helvetica-Bold', 52)
    c.drawCentredString(w/2, h - 52*mm, f'#{active_ticket.ticket_number}')
    c.setFillColor(dark)
    c.setFont('Helvetica-Bold', 11)
    c.drawCentredString(w/2, h - 57*mm, active_ticket.department.name)

    c.setStrokeColor(colors.HexColor('#E2E8F0'))
    c.setDash(2, 3)
    c.line(5*mm, h - 60*mm, w - 5*mm, h - 60*mm)
    c.setDash()

    def info_row(y, label, value):
        c.setFillColor(muted)
        c.setFont('Helvetica', 7)
        c.drawString(8*mm, y, label.upper())
        c.setFillColor(dark)
        c.setFont('Helvetica-Bold', 8)
        c.drawRightString(w - 8*mm, y, value)

    info_row(h - 65*mm, 'Patient', current_user.full_name)
    info_row(h - 70*mm, 'Date', active_ticket.booked_at.strftime('%d %b %Y'))
    info_row(h - 75*mm, 'Booked At', active_ticket.booked_at.strftime('%I:%M %p'))
    if active_ticket.notes:
        info_row(h - 80*mm, 'Notes', active_ticket.notes[:35])

    c.setStrokeColor(colors.HexColor('#E2E8F0'))
    c.setDash(2, 3)
    c.line(5*mm, h - 83*mm, w - 5*mm, h - 83*mm)
    c.setDash()

    c.setFillColor(primary)
    c.setFont('Helvetica-Bold', 20)
    c.drawCentredString(w/4, h - 93*mm, f"{position}/{waiting_count}")
    c.drawCentredString(3*w/4, h - 93*mm, f'~{est_wait}m')
    c.setFillColor(muted)
    c.setFont('Helvetica', 6.5)
    c.drawCentredString(w/4, h - 97*mm, 'QUEUE POSITION')
    c.drawCentredString(3*w/4, h - 97*mm, 'EST. WAIT')

    badge_color = success if active_ticket.status == 'serving' else warning
    badge_text = 'NOW SERVING' if active_ticket.status == 'serving' else 'WAITING'
    c.setFillColor(badge_color)
    c.roundRect(w/2 - 18*mm, h - 106*mm, 36*mm, 7*mm, 3*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont('Helvetica-Bold', 8)
    c.drawCentredString(w/2, h - 101.5*mm, badge_text)

    qr_size = 20*mm
    qr_x = w - 5*mm - qr_size
    qr_y = h - 106*mm - qr_size
    qr_widget = QrCodeWidget(qr_data)
    qr_drawing = Drawing(qr_size, qr_size)
    qr_drawing.add(qr_widget)
    renderPDF.draw(qr_drawing, c, qr_x, qr_y)

    c.setFillColor(muted)
    c.setFont('Helvetica', 6)
    c.drawString(5*mm, h - 114*mm, hospital_address[:50])
    c.drawString(5*mm, h - 118*mm, f"Tel: {hospital_phone}")
    c.drawString(5*mm, h - 122*mm, emergency[:50])

    c.setFillColor(colors.HexColor('#CBD5E1'))
    c.setFont('Helvetica', 6)
    c.drawCentredString(w/2, h - 128*mm,
        f"Generated {active_ticket.booked_at.strftime('%d %b %Y at %I:%M %p')}")

    c.save()
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'inline; filename=ticket_{active_ticket.ticket_number}.pdf'
    return response

@app.route('/checkin')
def checkin():
    ticket_num = request.args.get('ticket', type=int)
    if not ticket_num:
        return "Invalid ticket", 400
    return redirect(url_for('queue_status'))

@app.route('/history')
@login_required
def history():
    query = QueueEntry.query.filter(
        QueueEntry.user_id == current_user.id,
        QueueEntry.status.in_(['done', 'cancelled'])
    )

    date_filter = request.args.get('date_filter', 'all')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    if date_filter == 'last_week':
        start = datetime.now(timezone.utc) - timedelta(days=7)
        query = query.filter(QueueEntry.booked_at >= start)
    elif date_filter == 'last_month':
        start = datetime.now(timezone.utc) - timedelta(days=30)
        query = query.filter(QueueEntry.booked_at >= start)
    elif date_filter == 'custom' and start_date and end_date:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(QueueEntry.booked_at >= start, QueueEntry.booked_at < end)

    search = request.args.get('search', '').strip()
    if search:
        query = query.join(Department).filter(
            db.or_(
                Department.name.ilike(f'%{search}%'),
                QueueEntry.notes.ilike(f'%{search}%')
            )
        )

    past_tickets = query.order_by(QueueEntry.booked_at.desc()).all()
    completed = [t for t in past_tickets if t.status == 'done' and t.served_at]
    if completed:
        total_wait = sum((t.served_at - t.booked_at).seconds // 60 for t in completed)
        avg_wait = round(total_wait / len(completed))
    else:
        avg_wait = 0

    return render_template('history.html',
                           past_tickets=past_tickets,
                           avg_wait=avg_wait,
                           date_filter=date_filter,
                           search=search,
                           start_date=start_date,
                           end_date=end_date)

@app.route('/rate-visit/<int:entry_id>', methods=['POST'])
@login_required
def rate_visit(entry_id):
    entry = db.session.get(QueueEntry, entry_id)
    if not entry or entry.user_id != current_user.id:
        flash('Invalid request.', 'danger')
        return redirect(url_for('history'))
    rating = request.form.get('rating', type=int)
    if rating and 1 <= rating <= 5:
        entry.rating = rating
        db.session.commit()
        flash('Thank you for your rating!', 'success')
    else:
        flash('Invalid rating.', 'danger')
    return redirect(url_for('history'))

@app.route('/history/download-pdf')
@login_required
def history_pdf():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from io import BytesIO

    query = QueueEntry.query.filter(
        QueueEntry.user_id == current_user.id,
        QueueEntry.status.in_(['done', 'cancelled'])
    )

    date_filter = request.args.get('date_filter', 'all')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    if date_filter == 'last_week':
        start = datetime.now(timezone.utc) - timedelta(days=7)
        query = query.filter(QueueEntry.booked_at >= start)
    elif date_filter == 'last_month':
        start = datetime.now(timezone.utc) - timedelta(days=30)
        query = query.filter(QueueEntry.booked_at >= start)
    elif date_filter == 'custom' and start_date and end_date:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(QueueEntry.booked_at >= start, QueueEntry.booked_at < end)

    search = request.args.get('search', '')
    if search:
        query = query.join(Department).filter(
            db.or_(
                Department.name.ilike(f'%{search}%'),
                QueueEntry.notes.ilike(f'%{search}%')
            )
        )
    tickets = query.order_by(QueueEntry.booked_at.desc()).all()

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    title = Paragraph(f"Visit History for {current_user.full_name}", styles['Title'])
    elements.append(title)
    elements.append(Spacer(1, 10))

    data = [['Ticket', 'Department', 'Date', 'Status', 'Wait (min)', 'Rating']]
    for t in tickets:
        wait = (t.served_at - t.booked_at).seconds // 60 if t.served_at else '-'
        rating = '★' * t.rating if t.rating else '-'
        data.append([
            str(t.ticket_number),
            t.department.name,
            t.booked_at.strftime('%d %b %Y'),
            'Completed' if t.status == 'done' else 'Cancelled',
            str(wait) if wait != '-' else '-',
            rating
        ])

    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    response = make_response(buffer.read())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=history_{current_user.id}.pdf'
    return response

# ----- Entry point (for local development) -----
if __name__ == '__main__':
    socketio.run(app, debug=True)