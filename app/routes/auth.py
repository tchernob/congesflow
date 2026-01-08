from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember', False)

        user = User.query.filter_by(email=email).first()

        if user is None or not user.check_password(password):
            flash('Email ou mot de passe incorrect', 'error')
            return redirect(url_for('auth.login'))

        if not user.is_active:
            flash('Votre compte a été désactivé', 'error')
            return redirect(url_for('auth.login'))

        login_user(user, remember=remember)
        next_page = request.args.get('next')
        if not next_page:
            next_page = url_for('main.dashboard')
        return redirect(next_page)

    return render_template('auth/login.html')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Vous avez été déconnecté', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()
        if user:
            # TODO: Envoyer email de réinitialisation
            pass
        flash('Si un compte existe avec cet email, vous recevrez un lien de réinitialisation', 'info')
        return redirect(url_for('auth.login'))

    return render_template('auth/forgot_password.html')


@bp.route('/setup-password/<token>', methods=['GET', 'POST'])
def setup_password(token):
    """Allow invited users to set their password."""
    if current_user.is_authenticated:
        logout_user()

    user = User.query.filter_by(invitation_token=token).first()

    if not user:
        flash('Lien d\'invitation invalide', 'error')
        return redirect(url_for('auth.login'))

    if not user.verify_invitation_token():
        flash('Ce lien d\'invitation a expiré. Contactez votre administrateur.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        password = request.form.get('password')
        password_confirm = request.form.get('password_confirm')

        if not password or len(password) < 8:
            flash('Le mot de passe doit contenir au moins 8 caractères', 'error')
            return render_template('auth/setup_password.html', user=user, token=token)

        if password != password_confirm:
            flash('Les mots de passe ne correspondent pas', 'error')
            return render_template('auth/setup_password.html', user=user, token=token)

        user.set_password(password)
        user.clear_invitation_token()
        db.session.commit()

        flash('Votre mot de passe a été défini. Vous pouvez maintenant vous connecter.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/setup_password.html', user=user, token=token)
