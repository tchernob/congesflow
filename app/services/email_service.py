from flask import current_app, render_template, url_for
from flask_mail import Message
from app import mail
from threading import Thread


def send_async_email(app, msg):
    """Send email asynchronously."""
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            current_app.logger.error(f"Failed to send email: {e}")


def send_email(subject, recipient, template, **kwargs):
    """
    Send an email using a template.

    Args:
        subject: Email subject
        recipient: Email address to send to
        template: Template name (without extension) in templates/emails/
        **kwargs: Variables to pass to the template
    """
    app = current_app._get_current_object()

    msg = Message(
        subject=subject,
        recipients=[recipient],
        sender=current_app.config['MAIL_DEFAULT_SENDER']
    )

    # Render HTML and text versions
    msg.html = render_template(f'emails/{template}.html', **kwargs)

    # Try to render text version if it exists
    try:
        msg.body = render_template(f'emails/{template}.txt', **kwargs)
    except:
        # If no text template, create a simple text version
        msg.body = f"Veuillez consulter la version HTML de cet email."

    # Send asynchronously to not block the request
    thread = Thread(target=send_async_email, args=(app, msg))
    thread.start()

    return thread


def send_verification_email(user, token):
    """Send email verification to a new user."""
    verification_url = url_for('auth.verify_email', token=token, _external=True)

    send_email(
        subject='TimeOff - Confirmez votre adresse email',
        recipient=user.email,
        template='verify_email',
        user=user,
        verification_url=verification_url
    )


def send_welcome_email(user):
    """Send welcome email after verification."""
    login_url = url_for('auth.login', _external=True)

    send_email(
        subject='Bienvenue sur TimeOff !',
        recipient=user.email,
        template='welcome',
        user=user,
        login_url=login_url
    )


def send_password_reset_email(user, token):
    """Send password reset email."""
    reset_url = url_for('auth.reset_password', token=token, _external=True)

    send_email(
        subject='TimeOff - Réinitialisation de votre mot de passe',
        recipient=user.email,
        template='reset_password',
        user=user,
        reset_url=reset_url
    )


def send_invitation_email(user, token, inviter):
    """Send invitation email to a new team member."""
    setup_url = url_for('auth.setup_password', token=token, _external=True)

    send_email(
        subject=f'TimeOff - Invitation à rejoindre {user.company.name}',
        recipient=user.email,
        template='invitation',
        user=user,
        inviter=inviter,
        setup_url=setup_url
    )
