from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

doctor_departments = db.Table('doctor_departments',
    db.Column('doctor_id', db.Integer, db.ForeignKey('users.id')),
    db.Column('department_id', db.Integer, db.ForeignKey('departments.id'))
)

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id                = db.Column(db.Integer, primary_key=True)
    full_name         = db.Column(db.String(100), nullable=False)
    email             = db.Column(db.String(120), unique=True, nullable=False)
    password_hash     = db.Column(db.String(200), nullable=False)
    role              = db.Column(db.String(20), default='patient')
    is_available      = db.Column(db.Boolean, default=True)
    # New profile fields
    phone             = db.Column(db.String(20), nullable=True)
    emergency_contact = db.Column(db.String(100), nullable=True)
    emergency_phone   = db.Column(db.String(20), nullable=True)

    departments = db.relationship('Department', secondary=doctor_departments, backref='doctors')
    queue_entries = db.relationship('QueueEntry', foreign_keys='[QueueEntry.user_id]', backref='patient', lazy=True)
    served_entries = db.relationship('QueueEntry', foreign_keys='[QueueEntry.served_by]', backref='doctor', lazy=True)

    def __repr__(self):
        return f'<User {self.email} | {self.role}>'


class Department(db.Model):
    __tablename__ = 'departments'

    id   = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    base_wait_minutes = db.Column(db.Integer, default=15)

    queue_entries = db.relationship('QueueEntry', backref='department', lazy=True)

    def __repr__(self):
        return f'<Department {self.name}>'


class QueueEntry(db.Model):
    __tablename__ = 'queue_entries'

    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    ticket_number = db.Column(db.Integer, nullable=False)
    status        = db.Column(db.String(20), default='waiting')
    booked_at     = db.Column(db.DateTime, default=datetime.utcnow)
    served_at     = db.Column(db.DateTime, nullable=True)
    notes         = db.Column(db.String(300), nullable=True)
    cancel_reason = db.Column(db.String(50), nullable=True)
    served_by     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    rating        = db.Column(db.Integer, nullable=True)

    def __repr__(self):
        return f'<QueueEntry Ticket#{self.ticket_number} | {self.status}>'