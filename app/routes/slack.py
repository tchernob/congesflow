"""
Slack integration routes for TimeOff.
Handles OAuth flow, webhooks, and interactive messages.
"""
import hmac
import hashlib
import time
import requests
from flask import Blueprint, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from app import db
from app.models.slack import SlackIntegration, SlackUserMapping
from app.models.leave import LeaveRequest, LeaveType, LeaveBalance, CompanyLeaveSettings
from app.models.user import User
from app.models.notification import Notification
from app.services.slack_service import SlackService, notify_slack_new_request

bp = Blueprint('slack', __name__, url_prefix='/slack')


# OAuth Installation Flow
@bp.route('/install')
@login_required
def install():
    """Initiate Slack OAuth installation."""
    if not current_user.is_admin():
        flash('Accès réservé aux administrateurs', 'error')
        return redirect(url_for('main.dashboard'))

    client_id = current_app.config.get('SLACK_CLIENT_ID')
    if not client_id:
        flash('Configuration Slack manquante', 'error')
        return redirect(url_for('admin.slack_settings'))

    # Scopes needed for the bot
    scopes = [
        'chat:write',
        'channels:read',
        'groups:read',
        'im:write',
        'users:read',
        'users:read.email'
    ]

    # URL de callback fixe pour la production
    redirect_uri = "https://www.timeoff.fr/slack/oauth/callback"

    state = f"{current_user.company_id}"  # Store company_id in state

    oauth_url = (
        f"https://slack.com/oauth/v2/authorize"
        f"?client_id={client_id}"
        f"&scope={','.join(scopes)}"
        f"&redirect_uri={redirect_uri}"
        f"&state={state}"
    )

    return redirect(oauth_url)


@bp.route('/oauth/callback')
@login_required
def oauth_callback():
    """Handle OAuth callback from Slack."""
    error = request.args.get('error')
    if error:
        flash(f'Erreur lors de l\'installation Slack: {error}', 'error')
        return redirect(url_for('slack.settings'))

    code = request.args.get('code')
    state = request.args.get('state')

    if not code:
        flash('Code d\'autorisation manquant', 'error')
        return redirect(url_for('slack.settings'))

    # Verify state matches company_id
    try:
        company_id = int(state)
        if company_id != current_user.company_id:
            flash('Erreur de validation', 'error')
            return redirect(url_for('slack.settings'))
    except (ValueError, TypeError):
        flash('État invalide', 'error')
        return redirect(url_for('slack.settings'))

    # Exchange code for access token
    client_id = current_app.config.get('SLACK_CLIENT_ID')
    client_secret = current_app.config.get('SLACK_CLIENT_SECRET')

    # URL de callback fixe pour la production
    redirect_uri = "https://www.timeoff.fr/slack/oauth/callback"

    response = requests.post(
        'https://slack.com/api/oauth.v2.access',
        data={
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'redirect_uri': redirect_uri
        },
        timeout=10
    )

    data = response.json()

    if not data.get('ok'):
        error_msg = data.get('error', 'Erreur inconnue')
        current_app.logger.error(f'Slack OAuth error: {error_msg}')
        flash(f'Erreur Slack: {error_msg}', 'error')
        return redirect(url_for('slack.settings'))

    # Save or update integration
    integration = SlackIntegration.query.filter_by(company_id=company_id).first()

    if not integration:
        integration = SlackIntegration(company_id=company_id)
        db.session.add(integration)

    integration.access_token = data['access_token']
    integration.bot_user_id = data.get('bot_user_id')
    integration.team_id = data.get('team', {}).get('id')
    integration.team_name = data.get('team', {}).get('name')
    integration.is_active = True

    db.session.commit()

    # Synchroniser automatiquement les utilisateurs par email
    service = SlackService(integration)
    sync_stats = service.sync_users_by_email(company_id)

    flash(f'Slack connecté à {integration.team_name}! {sync_stats["linked"]} compte(s) lié(s) automatiquement.', 'success')
    return redirect(url_for('admin.slack_settings'))


@bp.route('/disconnect', methods=['POST'])
@login_required
def disconnect():
    """Disconnect Slack integration."""
    if not current_user.is_admin():
        flash('Accès réservé aux administrateurs', 'error')
        return redirect(url_for('main.dashboard'))

    integration = SlackIntegration.query.filter_by(
        company_id=current_user.company_id
    ).first()

    if integration:
        integration.is_active = False
        integration.access_token = ''
        db.session.commit()
        flash('Slack déconnecté', 'success')

    return redirect(url_for('admin.slack_settings'))


# Settings Page
@bp.route('/settings')
@login_required
def settings():
    """Slack integration settings page - redirect to admin."""
    return redirect(url_for('admin.slack_settings'))


@bp.route('/sync-users', methods=['POST'])
@login_required
def sync_users():
    """Synchroniser les utilisateurs Slack avec TimeOff."""
    if not current_user.is_admin():
        flash('Accès réservé aux administrateurs', 'error')
        return redirect(url_for('main.dashboard'))

    integration = SlackIntegration.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).first()

    if not integration:
        flash('Slack n\'est pas connecté', 'error')
        return redirect(url_for('admin.slack_settings'))

    service = SlackService(integration)
    stats = service.sync_users_by_email(current_user.company_id)

    flash(f'Synchronisation terminée : {stats["linked"]} nouveau(x) compte(s) lié(s), '
          f'{stats["already_linked"]} déjà lié(s), {stats["not_found"]} non trouvé(s) dans TimeOff.', 'success')

    return redirect(url_for('admin.slack_settings'))


@bp.route('/settings/update', methods=['POST'])
@login_required
def update_settings():
    """Update Slack notification settings."""
    if not current_user.is_admin():
        return jsonify({'error': 'Non autorisé'}), 403

    integration = SlackIntegration.query.filter_by(
        company_id=current_user.company_id
    ).first()

    if not integration:
        flash('Intégration Slack non configurée', 'error')
        return redirect(url_for('slack.settings'))

    # Update notification settings
    integration.notify_new_request = request.form.get('notify_new_request') == 'on'
    integration.notify_request_approved = request.form.get('notify_approved') == 'on'
    integration.notify_request_rejected = request.form.get('notify_rejected') == 'on'
    integration.notify_manager_pending = request.form.get('notify_manager') == 'on'

    # Update default channel
    channel_id = request.form.get('default_channel_id')
    channel_name = request.form.get('default_channel_name')
    if channel_id:
        integration.default_channel_id = channel_id
        integration.default_channel_name = channel_name

    db.session.commit()
    flash('Paramètres Slack mis à jour', 'success')
    return redirect(url_for('admin.slack_settings'))


# Slash Command Handler
@bp.route('/commands', methods=['POST'])
def slash_commands():
    """Handle slash commands from Slack (e.g., /conges)."""
    # Verify request signature
    if not verify_slack_signature(request):
        return jsonify({'error': 'Invalid signature'}), 403

    command = request.form.get('command')
    slack_user_id = request.form.get('user_id')
    team_id = request.form.get('team_id')
    trigger_id = request.form.get('trigger_id')

    if command == '/conges':
        return handle_conges_command(slack_user_id, team_id, trigger_id)
    elif command == '/soldes':
        return handle_soldes_command(slack_user_id, team_id)
    elif command == '/absents':
        return handle_absents_command(slack_user_id, team_id)
    elif command == '/equipe':
        return handle_equipe_command(slack_user_id, team_id)
    elif command == '/demandes':
        return handle_demandes_command(slack_user_id, team_id)

    return jsonify({'text': 'Commande non reconnue'}), 200


def handle_conges_command(slack_user_id, team_id, trigger_id):
    """Handle the /conges slash command - open a modal to request leave."""
    # Find user mapping
    user_mapping = SlackUserMapping.query.filter_by(slack_user_id=slack_user_id).first()

    if not user_mapping:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':warning: Votre compte Slack n\'est pas lié à TimeOff.\n\nConnectez-vous à TimeOff et liez votre compte Slack dans votre profil pour utiliser cette commande.'
        })

    user = user_mapping.user

    # Get the Slack integration for this team
    integration = SlackIntegration.query.filter_by(team_id=team_id, is_active=True).first()

    if not integration:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':warning: L\'intégration Slack n\'est pas configurée pour votre entreprise.'
        })

    # Get leave types for this company
    leave_types = LeaveType.query.filter_by(
        company_id=user.company_id,
        is_active=True
    ).all()

    if not leave_types:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':warning: Aucun type de congé configuré. Contactez votre administrateur.'
        })

    # Build leave type options
    leave_type_options = [
        {
            "text": {"type": "plain_text", "text": lt.name},
            "value": str(lt.id)
        }
        for lt in leave_types
    ]

    # Open modal
    modal = {
        "type": "modal",
        "callback_id": "leave_request_modal",
        "title": {"type": "plain_text", "text": "Demande de congés"},
        "submit": {"type": "plain_text", "text": "Envoyer"},
        "close": {"type": "plain_text", "text": "Annuler"},
        "private_metadata": str(user.id),
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":wave: Bonjour *{user.first_name}* !\n\nRemplissez ce formulaire pour soumettre votre demande de congés."
                }
            },
            {"type": "divider"},
            {
                "type": "input",
                "block_id": "leave_type_block",
                "element": {
                    "type": "static_select",
                    "action_id": "leave_type",
                    "placeholder": {"type": "plain_text", "text": "Sélectionnez un type"},
                    "options": leave_type_options
                },
                "label": {"type": "plain_text", "text": "Type de congé"}
            },
            {
                "type": "input",
                "block_id": "start_date_block",
                "element": {
                    "type": "datepicker",
                    "action_id": "start_date",
                    "placeholder": {"type": "plain_text", "text": "Date de début"}
                },
                "label": {"type": "plain_text", "text": "Date de début"}
            },
            {
                "type": "input",
                "block_id": "end_date_block",
                "element": {
                    "type": "datepicker",
                    "action_id": "end_date",
                    "placeholder": {"type": "plain_text", "text": "Date de fin"}
                },
                "label": {"type": "plain_text", "text": "Date de fin"}
            },
            {
                "type": "input",
                "block_id": "reason_block",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "reason",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Motif de la demande (optionnel)"}
                },
                "label": {"type": "plain_text", "text": "Motif"}
            }
        ]
    }

    # Call Slack API to open modal
    service = SlackService(integration)
    response = service._post('views.open', {
        'trigger_id': trigger_id,
        'view': modal
    })

    if not response.get('ok'):
        current_app.logger.error(f'Failed to open modal: {response}')
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':x: Erreur lors de l\'ouverture du formulaire. Réessayez.'
        })

    # Return empty 200 to acknowledge the command
    return '', 200


def handle_soldes_command(slack_user_id, team_id):
    """Handle the /soldes command - show leave balances."""
    user_mapping = SlackUserMapping.query.filter_by(slack_user_id=slack_user_id).first()

    if not user_mapping:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':warning: Votre compte Slack n\'est pas lié à TimeOff.'
        })

    user = user_mapping.user
    current_year = date.today().year

    balances = LeaveBalance.query.filter_by(
        user_id=user.id,
        year=current_year
    ).all()

    if not balances:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':information_source: Aucun solde de congés configuré pour cette année.'
        })

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Vos soldes de congés {current_year}", "emoji": True}
        },
        {"type": "divider"}
    ]

    for balance in balances:
        leave_type = balance.leave_type
        available = balance.available
        used = balance.used + balance.carried_over_used
        total = balance.total

        # Emoji based on balance
        if available <= 0:
            emoji = ":red_circle:"
        elif available <= 5:
            emoji = ":large_orange_circle:"
        else:
            emoji = ":large_green_circle:"

        blocks.append({
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"{emoji} *{leave_type.name}*"},
                {"type": "mrkdwn", "text": f"*{available:.1f}* jours disponibles"},
                {"type": "mrkdwn", "text": f"Utilisés: {used:.1f}"},
                {"type": "mrkdwn", "text": f"Total: {total:.1f}"}
            ]
        })

        # Alert for expiring days
        if balance.days_expiring_soon > 0:
            blocks.append({
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f":warning: *{balance.days_expiring_soon} jour(s)* expirent le {balance.carried_over_expires_at.strftime('%d/%m/%Y')}"}
                ]
            })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": ":bulb: Utilisez `/conges` pour faire une demande"}
        ]
    })

    return jsonify({
        'response_type': 'ephemeral',
        'blocks': blocks
    })


def handle_absents_command(slack_user_id, team_id):
    """Handle the /absents command - show who is absent today."""
    user_mapping = SlackUserMapping.query.filter_by(slack_user_id=slack_user_id).first()

    if not user_mapping:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':warning: Votre compte Slack n\'est pas lié à TimeOff.'
        })

    user = user_mapping.user
    today = date.today()

    # Get all approved leaves that include today
    absents = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == user.company_id,
        LeaveRequest.status == LeaveRequest.STATUS_APPROVED,
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= today
    ).all()

    if not absents:
        return jsonify({
            'response_type': 'ephemeral',
            'text': f':office: Personne n\'est absent aujourd\'hui ({today.strftime("%d/%m/%Y")}) !'
        })

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Absents aujourd'hui ({today.strftime('%d/%m/%Y')})", "emoji": True}
        },
        {"type": "divider"}
    ]

    for leave in absents:
        employee = leave.employee
        leave_type = leave.leave_type

        # Determine if half day
        info = ""
        if leave.start_date == today and leave.start_half_day:
            info = " (après-midi uniquement)"
        elif leave.end_date == today and leave.end_half_day:
            info = " (matin uniquement)"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f":palm_tree: *{employee.full_name}*\n{leave_type.name}{info}\nJusqu'au {leave.end_date.strftime('%d/%m/%Y')}"
            }
        })

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f":busts_in_silhouette: {len(absents)} personne(s) absente(s)"}
        ]
    })

    return jsonify({
        'response_type': 'ephemeral',
        'blocks': blocks
    })


def handle_equipe_command(slack_user_id, team_id):
    """Handle the /equipe command - show team planning."""
    user_mapping = SlackUserMapping.query.filter_by(slack_user_id=slack_user_id).first()

    if not user_mapping:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':warning: Votre compte Slack n\'est pas lié à TimeOff.'
        })

    user = user_mapping.user
    today = date.today()

    # Get team members (if user is manager, show their team; otherwise show their own team)
    if user.is_manager():
        # Show direct reports
        team_members = User.query.filter_by(manager_id=user.id, is_active=True).all()
        team_name = "Votre équipe"
    elif user.team_id:
        # Show same team
        team_members = User.query.filter_by(team_id=user.team_id, is_active=True).all()
        team_name = user.team.name if user.team else "Votre équipe"
    else:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':information_source: Vous n\'êtes pas assigné à une équipe.'
        })

    if not team_members:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':information_source: Aucun membre dans votre équipe.'
        })

    # Get upcoming 7 days
    end_date = today + timedelta(days=7)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Planning - {team_name}", "emoji": True}
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Du {today.strftime('%d/%m')} au {end_date.strftime('%d/%m/%Y')}"}
            ]
        },
        {"type": "divider"}
    ]

    for member in team_members:
        # Get leaves in the period
        leaves = LeaveRequest.query.filter(
            LeaveRequest.employee_id == member.id,
            LeaveRequest.status == LeaveRequest.STATUS_APPROVED,
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= today
        ).all()

        if leaves:
            leave_info = []
            for leave in leaves:
                leave_info.append(f"{leave.leave_type.name}: {leave.start_date.strftime('%d/%m')} - {leave.end_date.strftime('%d/%m')}")
            status = ":palm_tree: " + ", ".join(leave_info)
        else:
            status = ":white_check_mark: Présent(e)"

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{member.full_name}*\n{status}"
            }
        })

    return jsonify({
        'response_type': 'ephemeral',
        'blocks': blocks
    })


def handle_demandes_command(slack_user_id, team_id):
    """Handle the /demandes command - show pending requests."""
    user_mapping = SlackUserMapping.query.filter_by(slack_user_id=slack_user_id).first()

    if not user_mapping:
        return jsonify({
            'response_type': 'ephemeral',
            'text': ':warning: Votre compte Slack n\'est pas lié à TimeOff.'
        })

    user = user_mapping.user

    # Get user's own pending requests
    my_requests = LeaveRequest.query.filter(
        LeaveRequest.employee_id == user.id,
        LeaveRequest.status.in_([LeaveRequest.STATUS_PENDING_MANAGER, LeaveRequest.STATUS_PENDING_HR])
    ).order_by(LeaveRequest.created_at.desc()).all()

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "Vos demandes en cours", "emoji": True}
        },
        {"type": "divider"}
    ]

    if my_requests:
        for req in my_requests:
            status_emoji = ":hourglass_flowing_sand:" if req.status == LeaveRequest.STATUS_PENDING_MANAGER else ":clock3:"
            status_text = "En attente manager" if req.status == LeaveRequest.STATUS_PENDING_MANAGER else "En attente RH"

            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{status_emoji} *{req.leave_type.name}*\n{req.start_date.strftime('%d/%m/%Y')} - {req.end_date.strftime('%d/%m/%Y')} ({req.days_count} j)\n_{status_text}_"
                }
            })
    else:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": ":white_check_mark: Vous n'avez aucune demande en attente."
            }
        })

    # If user is manager, show pending requests to approve
    if user.is_manager() or user.is_hr():
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "header",
            "text": {"type": "plain_text", "text": "Demandes à traiter", "emoji": True}
        })

        if user.is_hr():
            pending = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
                User.company_id == user.company_id,
                LeaveRequest.status == LeaveRequest.STATUS_PENDING_HR
            ).order_by(LeaveRequest.created_at.desc()).limit(5).all()
        else:
            pending = LeaveRequest.query.filter(
                LeaveRequest.status == LeaveRequest.STATUS_PENDING_MANAGER,
                LeaveRequest.employee.has(manager_id=user.id)
            ).order_by(LeaveRequest.created_at.desc()).limit(5).all()

        if pending:
            for req in pending:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f":inbox_tray: *{req.employee.full_name}*\n{req.leave_type.name}: {req.start_date.strftime('%d/%m')} - {req.end_date.strftime('%d/%m')} ({req.days_count} j)"
                    },
                    "accessory": {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Voir"},
                        "action_id": "view_request",
                        "value": str(req.id)
                    }
                })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": ":white_check_mark: Aucune demande à traiter."
                }
            })

    return jsonify({
        'response_type': 'ephemeral',
        'blocks': blocks
    })


# Interactive Messages Webhook
@bp.route('/interactions', methods=['POST'])
def interactions():
    """Handle interactive messages from Slack (button clicks, modal submissions)."""
    # Verify request signature
    if not verify_slack_signature(request):
        return jsonify({'error': 'Invalid signature'}), 403

    # Parse payload
    import json
    payload = json.loads(request.form.get('payload', '{}'))

    action_type = payload.get('type')

    if action_type == 'block_actions':
        return handle_block_action(payload)
    elif action_type == 'view_submission':
        return handle_view_submission(payload)

    return jsonify({'ok': True})


def handle_view_submission(payload):
    """Handle modal form submissions."""
    import json

    callback_id = payload.get('view', {}).get('callback_id')

    if callback_id == 'leave_request_modal':
        return handle_leave_request_submission(payload)

    return jsonify({'ok': True})


def handle_leave_request_submission(payload):
    """Handle the leave request modal submission."""
    view = payload.get('view', {})
    values = view.get('state', {}).get('values', {})
    user_id = int(view.get('private_metadata', '0'))

    # Extract form values
    leave_type_id = int(values.get('leave_type_block', {}).get('leave_type', {}).get('selected_option', {}).get('value', 0))
    start_date_str = values.get('start_date_block', {}).get('start_date', {}).get('selected_date')
    end_date_str = values.get('end_date_block', {}).get('end_date', {}).get('selected_date')
    reason = values.get('reason_block', {}).get('reason', {}).get('value', '')

    # Validate
    errors = {}

    if not leave_type_id:
        errors['leave_type_block'] = 'Veuillez sélectionner un type de congé'

    if not start_date_str:
        errors['start_date_block'] = 'Veuillez sélectionner une date de début'

    if not end_date_str:
        errors['end_date_block'] = 'Veuillez sélectionner une date de fin'

    if errors:
        return jsonify({
            'response_action': 'errors',
            'errors': errors
        })

    # Parse dates
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

    # More validation
    if start_date > end_date:
        return jsonify({
            'response_action': 'errors',
            'errors': {'end_date_block': 'La date de fin doit être après la date de début'}
        })

    if start_date < date.today():
        return jsonify({
            'response_action': 'errors',
            'errors': {'start_date_block': 'La date de début ne peut pas être dans le passé'}
        })

    # Get user
    user = User.query.get(user_id)
    if not user:
        return jsonify({
            'response_action': 'errors',
            'errors': {'leave_type_block': 'Utilisateur non trouvé'}
        })

    # Déterminer le statut initial selon le workflow
    settings = CompanyLeaveSettings.get_or_create_for_company(user.company_id)
    initial_status = settings.get_initial_status()

    # Create leave request
    leave_request = LeaveRequest(
        employee_id=user.id,
        leave_type_id=leave_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason or '',
        status=initial_status
    )
    leave_request.days_count = leave_request.calculate_days()

    # Check balance
    balance = LeaveBalance.query.filter_by(
        user_id=user.id,
        leave_type_id=leave_type_id,
        year=start_date.year
    ).first()

    if balance and balance.available < leave_request.days_count:
        return jsonify({
            'response_action': 'errors',
            'errors': {'leave_type_block': f'Solde insuffisant. Disponible: {balance.available} jours'}
        })

    # Update pending balance
    if balance:
        balance.pending += leave_request.days_count

    db.session.add(leave_request)
    db.session.commit()

    # Send notifications
    Notification.notify_leave_request_created(leave_request)
    db.session.commit()

    # Send Slack notification to manager
    notify_slack_new_request(leave_request)

    # Send confirmation to user via Slack DM
    slack_user_id = payload.get('user', {}).get('id')
    team_id = payload.get('team', {}).get('id')

    integration = SlackIntegration.query.filter_by(team_id=team_id, is_active=True).first()
    if integration:
        # Message adapté selon le workflow
        if initial_status == LeaveRequest.STATUS_PENDING_HR:
            pending_msg = "_Votre demande est en attente de validation par les RH._"
        else:
            pending_msg = "_Votre demande est en attente de validation par votre manager._"

        service = SlackService(integration)
        service.send_dm(
            slack_user_id,
            f":white_check_mark: Votre demande de congés a été créée !",
            [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Demande enregistrée*\n\n"
                               f"*Type:* {leave_request.leave_type.name}\n"
                               f"*Du:* {start_date.strftime('%d/%m/%Y')}\n"
                               f"*Au:* {end_date.strftime('%d/%m/%Y')}\n"
                               f"*Durée:* {leave_request.days_count} jour(s)\n\n"
                               f"{pending_msg}"
                    }
                }
            ]
        )

    # Close modal
    return jsonify({'response_action': 'clear'})


def verify_slack_signature(req):
    """Verify the request came from Slack."""
    signing_secret = current_app.config.get('SLACK_SIGNING_SECRET')
    if not signing_secret:
        current_app.logger.warning('SLACK_SIGNING_SECRET not configured')
        return True  # Skip verification in dev

    timestamp = req.headers.get('X-Slack-Request-Timestamp', '')
    signature = req.headers.get('X-Slack-Signature', '')

    # Check timestamp to prevent replay attacks
    if abs(time.time() - int(timestamp)) > 60 * 5:
        return False

    # Compute signature
    sig_basestring = f"v0:{timestamp}:{req.get_data(as_text=True)}"
    my_signature = 'v0=' + hmac.new(
        signing_secret.encode(),
        sig_basestring.encode(),
        hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(my_signature, signature)


def handle_block_action(payload):
    """Handle button clicks from Slack messages."""
    import json

    actions = payload.get('actions', [])
    if not actions:
        return jsonify({'ok': True})

    action = actions[0]
    action_id = action.get('action_id')
    request_id = action.get('value')

    user_info = payload.get('user', {})
    slack_user_id = user_info.get('id')

    # Find the user mapping
    user_mapping = SlackUserMapping.query.filter_by(slack_user_id=slack_user_id).first()
    if not user_mapping:
        return jsonify({
            'response_type': 'ephemeral',
            'text': 'Votre compte Slack n\'est pas lié à TimeOff. Connectez-vous à l\'application pour lier votre compte.'
        })

    user = user_mapping.user
    leave_request = LeaveRequest.query.get(request_id)

    if not leave_request:
        return jsonify({
            'response_type': 'ephemeral',
            'text': 'Demande introuvable.'
        })

    # Check permissions
    if not user.is_manager_of(leave_request.employee) and not user.is_hr():
        return jsonify({
            'response_type': 'ephemeral',
            'text': 'Vous n\'êtes pas autorisé à traiter cette demande.'
        })

    if action_id == 'approve_request':
        return handle_approve(leave_request, user, payload)
    elif action_id == 'reject_request':
        return handle_reject(leave_request, user, payload)
    elif action_id == 'view_request':
        # Return a link to view the request
        request_url = url_for('leave.view_request', request_id=request_id, _external=True)
        return jsonify({
            'response_type': 'ephemeral',
            'text': f'<{request_url}|Voir la demande dans TimeOff>'
        })

    return jsonify({'ok': True})


def handle_approve(leave_request, approver, payload):
    """Handle approval from Slack."""
    if leave_request.status == LeaveRequest.STATUS_PENDING_MANAGER:
        leave_request.approve_by_manager(approver)
        action_text = "approuvée par le manager"
    elif leave_request.status == LeaveRequest.STATUS_PENDING_HR:
        leave_request.approve_by_hr(approver)
        action_text = "approuvée par les RH"
    else:
        return jsonify({
            'response_type': 'ephemeral',
            'text': 'Cette demande ne peut pas être approuvée dans son état actuel.'
        })

    Notification.notify_leave_request_approved(leave_request, approver)
    db.session.commit()

    # Update the original message
    return jsonify({
        'response_type': 'in_channel',
        'replace_original': True,
        'text': f'Demande de {leave_request.employee.full_name} {action_text} par {approver.full_name}.',
        'blocks': [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":white_check_mark: *Demande approuvée*\n\nDemande de *{leave_request.employee.full_name}* ({leave_request.leave_type.name}) du {leave_request.start_date.strftime('%d/%m/%Y')} au {leave_request.end_date.strftime('%d/%m/%Y')}\n\n_Approuvée par {approver.full_name}_"
                }
            }
        ]
    })


def handle_reject(leave_request, rejector, payload):
    """Handle rejection from Slack."""
    if leave_request.status not in [LeaveRequest.STATUS_PENDING_MANAGER, LeaveRequest.STATUS_PENDING_HR]:
        return jsonify({
            'response_type': 'ephemeral',
            'text': 'Cette demande ne peut pas être refusée dans son état actuel.'
        })

    leave_request.reject(rejector, "Refusé via Slack")
    Notification.notify_leave_request_rejected(leave_request, rejector)
    db.session.commit()

    # Update the original message
    return jsonify({
        'response_type': 'in_channel',
        'replace_original': True,
        'text': f'Demande de {leave_request.employee.full_name} refusée par {rejector.full_name}.',
        'blocks': [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f":x: *Demande refusée*\n\nDemande de *{leave_request.employee.full_name}* ({leave_request.leave_type.name}) du {leave_request.start_date.strftime('%d/%m/%Y')} au {leave_request.end_date.strftime('%d/%m/%Y')}\n\n_Refusée par {rejector.full_name}_"
                }
            }
        ]
    })


# User Mapping
@bp.route('/link', methods=['POST'])
@login_required
def link_account():
    """Link current user's account to their Slack user ID."""
    slack_user_id = request.form.get('slack_user_id')

    if not slack_user_id:
        flash('ID Slack manquant', 'error')
        return redirect(url_for('main.profile'))

    # Check if mapping already exists
    existing = SlackUserMapping.query.filter_by(user_id=current_user.id).first()
    if existing:
        existing.slack_user_id = slack_user_id
    else:
        mapping = SlackUserMapping(
            user_id=current_user.id,
            slack_user_id=slack_user_id
        )
        db.session.add(mapping)

    db.session.commit()
    flash('Compte Slack lié avec succès', 'success')
    return redirect(url_for('main.profile'))


@bp.route('/unlink', methods=['POST'])
@login_required
def unlink_account():
    """Unlink current user's Slack account."""
    mapping = SlackUserMapping.query.filter_by(user_id=current_user.id).first()
    if mapping:
        db.session.delete(mapping)
        db.session.commit()
        flash('Compte Slack délié', 'success')

    return redirect(url_for('main.profile'))
