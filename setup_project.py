import os

# ============ Directory structure ============
dirs = [
    'static',
    'templates',
    'instance'
]

for d in dirs:
    os.makedirs(d, exist_ok=True)

# ============ Files and their content ============
files = {
    'app.py': '''from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_socketio import SocketIO, emit
from models import db, User, Doctor, Appointment, Queue
from forms import LoginForm, RegistrationForm, BookingForm
from datetime import datetime, date, time as tm
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///queue.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
socketio = SocketIO(app, cors_allowed_origins="*")
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables (run once)
with app.app_context():
    db.create_all()
    # Optionally create a default doctor user (uncomment if needed)
    # if not User.query.filter_by(username='dr_smith').first():
    #     user = User(username='dr_smith', email='dr@example.com', password=generate_password_hash('password'), role='doctor')
    #     db.session.add(user)
    #     db.session.commit()
    #     doctor = Doctor(user_id=user.id, specialty='Cardiology')
    #     db.session.add(doctor)
    #     db.session.commit()

# ============ Routes ============
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        # Check if user exists
        user = User.query.filter((User.username == form.username.data) | (User.email == form.email.data)).first()
        if user:
            flash('Username or email already exists.', 'danger')
            return redirect(url_for('register'))
        hashed_pw = generate_password_hash(form.password.data)
        new_user = User(username=form.username.data, email=form.email.data, password=hashed_pw, role=form.role.data)
        db.session.add(new_user)
        db.session.commit()
        # If role is doctor, create Doctor record
        if form.role.data == 'doctor':
            doctor = Doctor(user_id=new_user.id, specialty='General')
            db.session.add(doctor)
            db.session.commit()
        flash('Account created! Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and check_password_hash(user.password, form.password.data):
            login_user(user)
            if user.role == 'doctor':
                return redirect(url_for('admin'))
            else:
                return redirect(url_for('dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'patient':
        return redirect(url_for('admin'))
    appointments = Appointment.query.filter_by(patient_id=current_user.id).order_by(Appointment.date, Appointment.time).all()
    return render_template('dashboard.html', appointments=appointments)

@app.route('/book', methods=['GET', 'POST'])
@login_required
def book():
    if current_user.role != 'patient':
        flash('Only patients can book appointments.', 'warning')
        return redirect(url_for('dashboard'))
    form = BookingForm()
    form.doctor_id.choices = [(d.id, d.user.username) for d in Doctor.query.all()]
    if form.validate_on_submit():
        existing = Appointment.query.filter_by(doctor_id=form.doctor_id.data, date=form.date.data, time=form.time.data).first()
        if existing:
            flash('This slot is already booked. Please choose another time.', 'danger')
            return redirect(url_for('book'))
        appointment = Appointment(
            patient_id=current_user.id,
            doctor_id=form.doctor_id.data,
            date=form.date.data,
            time=form.time.data,
            status='waiting'
        )
        db.session.add(appointment)
        db.session.commit()
        last_queue = Queue.query.filter_by(doctor_id=form.doctor_id.data).order_by(Queue.queue_number.desc()).first()
        next_number = (last_queue.queue_number + 1) if last_queue else 1
        queue_entry = Queue(
            doctor_id=form.doctor_id.data,
            appointment_id=appointment.id,
            queue_number=next_number,
            status='waiting'
        )
        db.session.add(queue_entry)
        db.session.commit()
        flash('Appointment booked successfully! Your queue number is {}.'.format(next_number), 'success')
        socketio.emit('queue_update', {'doctor_id': form.doctor_id.data}, broadcast=True)
        return redirect(url_for('dashboard'))
    return render_template('book.html', form=form)

@app.route('/queue/<int:doctor_id>')
@login_required
def queue_status(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    today = date.today()
    queue_entries = Queue.query.join(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date == today
    ).order_by(Queue.queue_number).all()
    return render_template('queue_status.html', doctor=doctor, queue=queue_entries)

@app.route('/admin')
@login_required
def admin():
    if current_user.role != 'doctor':
        flash('Unauthorized access.', 'danger')
        return redirect(url_for('dashboard'))
    doctor = Doctor.query.filter_by(user_id=current_user.id).first()
    today = date.today()
    queue_entries = Queue.query.join(Appointment).filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date == today,
        Queue.status == 'waiting'
    ).order_by(Queue.queue_number).all()
    in_progress = Queue.query.join(Appointment).filter(
        Appointment.doctor_id == doctor.id,
        Appointment.date == today,
        Queue.status == 'called'
    ).first()
    return render_template('admin.html', doctor=doctor, queue=queue_entries, in_progress=in_progress)

@app.route('/call_next/<int:doctor_id>', methods=['POST'])
@login_required
def call_next(doctor_id):
    doctor = Doctor.query.get_or_404(doctor_id)
    if current_user.id != doctor.user_id:
        flash('Not your queue', 'danger')
        return redirect(url_for('admin'))
    today = date.today()
    next_queue = Queue.query.join(Appointment).filter(
        Appointment.doctor_id == doctor_id,
        Appointment.date == today,
        Queue.status == 'waiting'
    ).order_by(Queue.queue_number).first()
    if next_queue:
        next_queue.status = 'called'
        next_queue.appointment.status = 'in_progress'
        db.session.commit()
        socketio.emit('queue_update', {'doctor_id': doctor_id}, broadcast=True)
        flash('Called queue #{}'.format(next_queue.queue_number), 'success')
    else:
        flash('No waiting patients.', 'info')
    return redirect(url_for('admin'))

if __name__ == '__main__':
    socketio.run(app, debug=True)
''',

    'models.py': '''from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'patient' or 'doctor'
    doctor = db.relationship('Doctor', backref='user', uselist=False)

class Doctor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    specialty = db.Column(db.String(100))
    appointments = db.relationship('Appointment', backref='doctor', lazy=True)

class Appointment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    time = db.Column(db.Time, nullable=False)
    status = db.Column(db.String(20), default='waiting')  # waiting, in_progress, completed
    patient = db.relationship('User', foreign_keys=[patient_id])

class Queue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    doctor_id = db.Column(db.Integer, db.ForeignKey('doctor.id'), nullable=False)
    appointment_id = db.Column(db.Integer, db.ForeignKey('appointment.id'), nullable=False)
    queue_number = db.Column(db.Integer)
    status = db.Column(db.String(20), default='waiting')  # waiting, called, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    appointment = db.relationship('Appointment')
''',

    'forms.py': '''from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, DateField, TimeField
from wtforms.validators import DataRequired, Email, EqualTo

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    role = SelectField('Role', choices=[('patient', 'Patient'), ('doctor', 'Doctor')], validators=[DataRequired()])
    submit = SubmitField('Register')

class BookingForm(FlaskForm):
    doctor_id = SelectField('Doctor', coerce=int, validators=[DataRequired()])
    date = DateField('Date', validators=[DataRequired()])
    time = TimeField('Time', validators=[DataRequired()])
    submit = SubmitField('Book Slot')
''',

    'requirements.txt': '''flask
flask-sqlalchemy
flask-login
flask-socketio
eventlet
''',

    'static/style.css': '''/* Add your custom CSS here */
body {
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
}
''',

    'templates/base.html': '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Queue Management System</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container">
            <a class="navbar-brand" href="{{ url_for('index') }}">Queue Manager</a>
            <div class="collapse navbar-collapse">
                <ul class="navbar-nav ms-auto">
                    {% if current_user.is_authenticated %}
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('dashboard') }}">Dashboard</a></li>
                        {% if current_user.role == 'patient' %}
                            <li class="nav-item"><a class="nav-link" href="{{ url_for('book') }}">Book Appointment</a></li>
                        {% elif current_user.role == 'doctor' %}
                            <li class="nav-item"><a class="nav-link" href="{{ url_for('admin') }}">Admin Panel</a></li>
                        {% endif %}
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('logout') }}">Logout</a></li>
                    {% else %}
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('login') }}">Login</a></li>
                        <li class="nav-item"><a class="nav-link" href="{{ url_for('register') }}">Register</a></li>
                    {% endif %}
                </ul>
            </div>
        </div>
    </nav>
    <div class="container mt-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% for category, message in messages %}
                <div class="alert alert-{{ category }}">{{ message }}</div>
            {% endfor %}
        {% endwith %}
        {% block content %}{% endblock %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
''',

    'templates/index.html': '''{% extends "base.html" %}
{% block content %}
<div class="jumbotron text-center">
    <h1 class="display-4">Welcome to Digital Queue Management System</h1>
    <p class="lead">Reduce waiting times in clinics by booking slots remotely and tracking the queue in real time.</p>
    <hr class="my-4">
    {% if not current_user.is_authenticated %}
        <a class="btn btn-primary btn-lg" href="{{ url_for('login') }}" role="button">Login</a>
        <a class="btn btn-secondary btn-lg" href="{{ url_for('register') }}" role="button">Register</a>
    {% else %}
        <a class="btn btn-primary btn-lg" href="{{ url_for('dashboard') }}" role="button">Go to Dashboard</a>
    {% endif %}
</div>
{% endblock %}
''',

    'templates/login.html': '''{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-6">
        <h2>Login</h2>
        <form method="POST" action="">
            {{ form.hidden_tag() }}
            <div class="mb-3">
                {{ form.username.label(class="form-label") }}
                {{ form.username(class="form-control") }}
                {% for error in form.username.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.password.label(class="form-label") }}
                {{ form.password(class="form-control") }}
                {% for error in form.password.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.submit(class="btn btn-primary") }}
            </div>
        </form>
        <p>Don't have an account? <a href="{{ url_for('register') }}">Register here</a></p>
    </div>
</div>
{% endblock %}
''',

    'templates/register.html': '''{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-6">
        <h2>Register</h2>
        <form method="POST" action="">
            {{ form.hidden_tag() }}
            <div class="mb-3">
                {{ form.username.label(class="form-label") }}
                {{ form.username(class="form-control") }}
                {% for error in form.username.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.email.label(class="form-label") }}
                {{ form.email(class="form-control") }}
                {% for error in form.email.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.password.label(class="form-label") }}
                {{ form.password(class="form-control") }}
                {% for error in form.password.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.confirm_password.label(class="form-label") }}
                {{ form.confirm_password(class="form-control") }}
                {% for error in form.confirm_password.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.role.label(class="form-label") }}
                {{ form.role(class="form-select") }}
                {% for error in form.role.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.submit(class="btn btn-primary") }}
            </div>
        </form>
        <p>Already have an account? <a href="{{ url_for('login') }}">Login here</a></p>
    </div>
</div>
{% endblock %}
''',

    'templates/dashboard.html': '''{% extends "base.html" %}
{% block content %}
<h2>Your Appointments</h2>
{% if appointments %}
    <table class="table table-striped">
        <thead>
            <tr>
                <th>Doctor</th>
                <th>Date</th>
                <th>Time</th>
                <th>Status</th>
                <th>Queue</th>
            </tr>
        </thead>
        <tbody>
            {% for appt in appointments %}
            <tr>
                <td>{{ appt.doctor.user.username }}</td>
                <td>{{ appt.date }}</td>
                <td>{{ appt.time }}</td>
                <td>{{ appt.status }}</td>
                <td>
                    {% for q in appt.doctor.queue if q.appointment_id == appt.id %}
                        #{{ q.queue_number }}
                    {% endfor %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
{% else %}
    <p>No appointments yet. <a href="{{ url_for('book') }}">Book a slot</a></p>
{% endif %}
{% endblock %}
''',

    'templates/book.html': '''{% extends "base.html" %}
{% block content %}
<div class="row justify-content-center">
    <div class="col-md-6">
        <h2>Book an Appointment</h2>
        <form method="POST" action="">
            {{ form.hidden_tag() }}
            <div class="mb-3">
                {{ form.doctor_id.label(class="form-label") }}
                {{ form.doctor_id(class="form-select") }}
                {% for error in form.doctor_id.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.date.label(class="form-label") }}
                {{ form.date(class="form-control") }}
                {% for error in form.date.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.time.label(class="form-label") }}
                {{ form.time(class="form-control") }}
                {% for error in form.time.errors %}
                    <div class="text-danger">{{ error }}</div>
                {% endfor %}
            </div>
            <div class="mb-3">
                {{ form.submit(class="btn btn-primary") }}
            </div>
        </form>
    </div>
</div>
{% endblock %}
''',

    'templates/queue_status.html': '''{% extends "base.html" %}
{% block content %}
<h2>Queue for Dr. {{ doctor.user.username }}</h2>
<ul id="queue-list" class="list-group">
    {% for q in queue %}
        <li class="list-group-item d-flex justify-content-between align-items-center" data-id="{{ q.id }}">
            Queue #{{ q.queue_number }}
            <span class="badge bg-{% if q.status == 'waiting' %}secondary{% elif q.status == 'called' %}warning{% else %}success{% endif %} rounded-pill">
                {{ q.status }}
            </span>
        </li>
    {% else %}
        <li class="list-group-item">No patients in queue</li>
    {% endfor %}
</ul>
{% block scripts %}
<script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
<script>
    var socket = io();
    socket.on('queue_update', function(data) {
        if (data.doctor_id == {{ doctor.id }}) {
            location.reload();
        }
    });
</script>
{% endblock %}
{% endblock %}
''',

    'templates/admin.html': '''{% extends "base.html" %}
{% block content %}
<h2>Admin Panel - Dr. {{ doctor.user.username }}</h2>
<h4>Today's Queue</h4>
{% if in_progress %}
    <div class="alert alert-warning">
        Currently with doctor: Queue #{{ in_progress.queue_number }}
    </div>
{% endif %}
<table class="table">
    <thead>
        <tr>
            <th>Queue #</th>
            <th>Patient</th>
            <th>Time</th>
            <th>Status</th>
        </tr>
    </thead>
    <tbody>
        {% for q in queue %}
        <tr>
            <td>{{ q.queue_number }}</td>
            <td>{{ q.appointment.patient.username }}</td>
            <td>{{ q.appointment.time }}</td>
            <td>{{ q.status }}</td>
        </tr>
        {% else %}
        <tr><td colspan="4">No waiting patients</td></tr>
        {% endfor %}
    </tbody>
</table>
<form method="POST" action="{{ url_for('call_next', doctor_id=doctor.id) }}">
    <button type="submit" class="btn btn-primary">Call Next Patient</button>
</form>
{% endblock %}
'''
}

# Write each file
for path, content in files.items():
    # Ensure parent directories exist
    dirname = os.path.dirname(path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

print("Project structure and files created successfully!")