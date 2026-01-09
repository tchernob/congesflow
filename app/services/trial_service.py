"""
Service de gestion des périodes d'essai.
Gère les rappels par email et la dégradation vers le plan Free.
"""
from datetime import datetime, timedelta
from flask import current_app, url_for
from app import db
from app.models.company import Company
from app.services.email_service import send_email


# Jours avant la fin de l'essai où envoyer un rappel
REMINDER_DAYS = [7, 3, 1, 0]


def get_companies_needing_reminder(days_remaining):
    """
    Récupère les entreprises dont l'essai se termine dans X jours.

    Args:
        days_remaining: Nombre de jours avant la fin (7, 3, 1, 0)

    Returns:
        Liste des Company
    """
    target_date = datetime.utcnow() + timedelta(days=days_remaining)
    start_of_day = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = target_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    return Company.query.filter(
        Company.trial_ends_at >= start_of_day,
        Company.trial_ends_at <= end_of_day,
        Company.is_active == True,
        # Ne pas envoyer si déjà abonné
        Company.stripe_subscription_status.is_(None)
    ).all()


def get_expired_trials():
    """
    Récupère les entreprises dont l'essai est expiré mais pas encore passées en Free.
    """
    return Company.query.filter(
        Company.trial_ends_at < datetime.utcnow(),
        Company.is_active == True,
        Company.plan != Company.PLAN_FREE,
        Company.stripe_subscription_status.is_(None)
    ).all()


def send_trial_reminder(company, days_remaining):
    """
    Envoie un email de rappel d'essai.

    Args:
        company: L'entreprise
        days_remaining: Jours restants (7, 3, 1, 0)
    """
    # Trouver l'admin de l'entreprise
    from app.models.user import User, Role
    admin_role = Role.query.filter_by(name='admin').first()
    admin = User.query.filter_by(
        company_id=company.id,
        role_id=admin_role.id,
        is_active=True
    ).first()

    if not admin:
        current_app.logger.warning(f"No admin found for company {company.id}")
        return

    # Déterminer le template selon les jours restants
    if days_remaining == 7:
        template = 'trial_reminder_7days'
        subject = 'TimeOff - Plus qu\'une semaine d\'essai'
    elif days_remaining == 3:
        template = 'trial_reminder_3days'
        subject = 'TimeOff - Votre essai se termine dans 3 jours'
    elif days_remaining == 1:
        template = 'trial_reminder_1day'
        subject = 'TimeOff - Dernier jour d\'essai demain !'
    else:  # 0
        template = 'trial_ended'
        subject = 'TimeOff - Votre essai est terminé'

    subscription_url = url_for('admin.subscription', _external=True)

    send_email(
        subject=subject,
        recipient=admin.email,
        template=template,
        company=company,
        admin=admin,
        days_remaining=days_remaining,
        subscription_url=subscription_url
    )

    current_app.logger.info(f"Trial reminder sent to {admin.email} ({days_remaining} days remaining)")


def expire_trial(company):
    """
    Fait passer une entreprise en plan Free après fin d'essai.

    Args:
        company: L'entreprise dont l'essai a expiré
    """
    company.expire_trial()
    db.session.commit()

    current_app.logger.info(f"Company {company.id} ({company.name}) trial expired, downgraded to Free")


def process_trial_reminders():
    """
    Traite tous les rappels d'essai.
    À appeler quotidiennement via un cron job.

    Returns:
        dict avec les statistiques
    """
    stats = {
        'reminders_sent': 0,
        'trials_expired': 0,
        'errors': []
    }

    # Envoyer les rappels pour chaque intervalle
    for days in REMINDER_DAYS:
        companies = get_companies_needing_reminder(days)
        for company in companies:
            try:
                send_trial_reminder(company, days)
                stats['reminders_sent'] += 1
            except Exception as e:
                error_msg = f"Failed to send reminder to company {company.id}: {e}"
                current_app.logger.error(error_msg)
                stats['errors'].append(error_msg)

    # Expirer les essais terminés
    expired_companies = get_expired_trials()
    for company in expired_companies:
        try:
            expire_trial(company)
            stats['trials_expired'] += 1
        except Exception as e:
            error_msg = f"Failed to expire trial for company {company.id}: {e}"
            current_app.logger.error(error_msg)
            stats['errors'].append(error_msg)

    return stats
