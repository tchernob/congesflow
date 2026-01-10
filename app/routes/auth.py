from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_user, logout_user, login_required, current_user
from app import db
from app.models.user import User
from app.services.email_service import send_welcome_email, send_2fa_code_email

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

        if not user.email_verified:
            flash('Veuillez vérifier votre adresse email avant de vous connecter.', 'error')
            return redirect(url_for('marketing.verification_sent', email=email))

        # 2FA for superadmins
        if user.is_superadmin:
            # Generate and send 2FA code
            code = user.generate_2fa_code()
            db.session.commit()
            send_2fa_code_email(user, code)

            # Store user id in session for 2FA verification
            session['2fa_user_id'] = user.id
            session['2fa_remember'] = remember

            flash('Un code de vérification a été envoyé à votre adresse email.', 'info')
            return redirect(url_for('auth.verify_2fa'))

        login_user(user, remember=remember)
        next_page = request.args.get('next')
        if not next_page:
            next_page = url_for('main.dashboard')
        return redirect(next_page)

    return render_template('auth/login.html')


@bp.route('/verify-2fa', methods=['GET', 'POST'])
def verify_2fa():
    """Verify 2FA code for superadmin login."""
    user_id = session.get('2fa_user_id')
    if not user_id:
        flash('Session expirée. Veuillez vous reconnecter.', 'error')
        return redirect(url_for('auth.login'))

    user = User.query.get(user_id)
    if not user or not user.is_superadmin:
        session.pop('2fa_user_id', None)
        session.pop('2fa_remember', None)
        flash('Session invalide.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        code = request.form.get('code', '').strip()

        if user.verify_2fa_code(code):
            # Clear 2FA code and session
            user.clear_2fa_code()
            db.session.commit()

            remember = session.pop('2fa_remember', False)
            session.pop('2fa_user_id', None)

            login_user(user, remember=remember)
            flash('Connexion réussie.', 'success')
            return redirect(url_for('root.dashboard'))
        else:
            flash('Code invalide ou expiré.', 'error')

    return render_template('auth/verify_2fa.html', user=user)


@bp.route('/resend-2fa', methods=['POST'])
def resend_2fa():
    """Resend 2FA code."""
    user_id = session.get('2fa_user_id')
    if not user_id:
        flash('Session expirée. Veuillez vous reconnecter.', 'error')
        return redirect(url_for('auth.login'))

    user = User.query.get(user_id)
    if not user or not user.is_superadmin:
        session.pop('2fa_user_id', None)
        flash('Session invalide.', 'error')
        return redirect(url_for('auth.login'))

    # Generate new code
    code = user.generate_2fa_code()
    db.session.commit()
    send_2fa_code_email(user, code)

    flash('Un nouveau code a été envoyé.', 'success')
    return redirect(url_for('auth.verify_2fa'))


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


@bp.route('/verify-email/<token>')
def verify_email(token):
    """Verify email address from signup."""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    user = User.query.filter_by(email_verification_token=token).first()

    if not user:
        flash('Lien de vérification invalide', 'error')
        return redirect(url_for('auth.login'))

    if not user.verify_email_token():
        flash('Ce lien de vérification a expiré. Veuillez demander un nouveau lien.', 'error')
        return redirect(url_for('marketing.verification_sent', email=user.email))

    # Mark email as verified
    user.confirm_email()
    db.session.commit()

    # Send welcome email
    send_welcome_email(user)

    flash('Votre email a été vérifié ! Vous pouvez maintenant vous connecter.', 'success')
    return redirect(url_for('auth.login'))
