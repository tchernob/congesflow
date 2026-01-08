from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import current_user
from datetime import datetime, timedelta
from app import db
from app.models import Company, User, Role, LeaveType

bp = Blueprint('marketing', __name__)


@bp.route('/')
def home():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('marketing/home.html')


@bp.route('/features')
def features():
    return render_template('marketing/features.html')


@bp.route('/pricing')
def pricing():
    return render_template('marketing/pricing.html')


@bp.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        # Company info
        company_name = request.form.get('company_name', '').strip()
        company_email = request.form.get('company_email', '').strip()

        # Admin user info
        first_name = request.form.get('first_name', '').strip()
        last_name = request.form.get('last_name', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        password_confirm = request.form.get('password_confirm', '')

        # Validation
        errors = []

        if not company_name:
            errors.append('Le nom de l\'entreprise est requis')
        if not email:
            errors.append('L\'email est requis')
        if not password:
            errors.append('Le mot de passe est requis')
        if len(password) < 8:
            errors.append('Le mot de passe doit contenir au moins 8 caractères')
        if password != password_confirm:
            errors.append('Les mots de passe ne correspondent pas')

        # Check if company name exists
        if Company.query.filter_by(name=company_name).first():
            errors.append('Une entreprise avec ce nom existe déjà')

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('marketing/signup.html')

        # Create company
        company = Company(
            name=company_name,
            slug=Company.generate_slug(company_name),
            email=company_email or email,
            plan=Company.PLAN_TRIAL,
            max_employees=10,
            trial_ends_at=datetime.utcnow() + timedelta(days=14)
        )
        db.session.add(company)
        db.session.flush()

        # Ensure roles exist
        Role.insert_roles()

        # Create admin user for this company
        admin_role = Role.query.filter_by(name='admin').first()
        admin_user = User(
            company_id=company.id,
            email=email,
            first_name=first_name or 'Admin',
            last_name=last_name or company_name,
            role_id=admin_role.id
        )
        admin_user.set_password(password)
        db.session.add(admin_user)

        # Create default leave types for this company
        LeaveType.insert_default_types(company_id=company.id)

        db.session.commit()

        flash('Votre compte a été créé ! Vous pouvez maintenant vous connecter.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('marketing/signup.html')


@bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        # TODO: Handle contact form submission
        flash('Merci pour votre message ! Nous vous répondrons rapidement.', 'success')
        return redirect(url_for('marketing.contact'))

    return render_template('marketing/contact.html')


@bp.route('/demo')
def demo():
    return render_template('marketing/demo.html')
