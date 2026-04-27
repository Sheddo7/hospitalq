from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField, TextAreaField, IntegerField, SelectMultipleField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SelectField, SubmitField, TextAreaField, IntegerField
from wtforms.validators import DataRequired, Email, EqualTo, Length, NumberRange, Optional


class RegistrationForm(FlaskForm):
    full_name  = StringField('Full Name',  validators=[DataRequired(), Length(min=2, max=100)])
    email      = StringField('Email',      validators=[DataRequired(), Email()])
    password   = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm    = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit     = SubmitField('Register')


class LoginForm(FlaskForm):
    email      = StringField('Email',    validators=[DataRequired(), Email()])
    password   = PasswordField('Password', validators=[DataRequired()])
    submit     = SubmitField('Login')


class BookSlotForm(FlaskForm):
    department = SelectField('Department', coerce=int, validators=[DataRequired()])
    notes      = TextAreaField('Notes (optional)', validators=[Length(max=300)])
    submit     = SubmitField('Book My Slot')


class CreateUserForm(FlaskForm):
    full_name = StringField('Full Name',  validators=[DataRequired(), Length(min=2, max=100)])
    email     = StringField('Email',      validators=[DataRequired(), Email()])
    password  = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    role = SelectField('Role', choices=[('patient', 'Patient'), ('doctor', 'Doctor'), ('admin', 'Admin'), ('receptionist', 'Receptionist')], validators=[DataRequired()])
    submit    = SubmitField('Create Account')


class DepartmentForm(FlaskForm):
    name = StringField('Department Name', validators=[DataRequired(), Length(min=2, max=100)])
    base_wait_minutes = IntegerField('Base Wait Time (minutes)', validators=[DataRequired(), NumberRange(min=1, max=120)], default=15)
    submit = SubmitField('Save')


class AssignDepartmentsForm(FlaskForm):
    departments = SelectMultipleField('Assigned Departments', coerce=int, validators=[DataRequired()])
    submit = SubmitField('Save Assignments')


class EditUserForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email', validators=[DataRequired(), Email()])
    role = SelectField('Role', choices=[('patient', 'Patient'), ('doctor', 'Doctor'), ('admin', 'Admin'), ('receptionist', 'Receptionist')], validators=[DataRequired()])
    submit = SubmitField('Update User')


class ResetPasswordForm(FlaskForm):
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('new_password')])
    submit = SubmitField('Reset Password')


class ProfileForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    phone = StringField('Phone Number', validators=[Optional(), Length(max=20)])
    emergency_contact = StringField('Emergency Contact Name', validators=[Optional(), Length(max=100)])
    emergency_phone = StringField('Emergency Contact Phone', validators=[Optional(), Length(max=20)])
    submit = SubmitField('Update Profile')