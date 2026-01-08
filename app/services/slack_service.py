"""
Slack integration service for CongesFlow.
Handles sending notifications and interactive messages to Slack.
"""
import requests
from flask import current_app, url_for
from app.models.slack import SlackIntegration, SlackUserMapping


class SlackService:
    """Service for interacting with Slack API."""

    SLACK_API_BASE = 'https://slack.com/api'

    def __init__(self, integration: SlackIntegration):
        self.integration = integration
        self.token = integration.access_token

    def _headers(self):
        return {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }

    def _post(self, endpoint: str, data: dict) -> dict:
        """Make a POST request to Slack API."""
        try:
            response = requests.post(
                f'{self.SLACK_API_BASE}/{endpoint}',
                headers=self._headers(),
                json=data,
                timeout=10
            )
            return response.json()
        except Exception as e:
            current_app.logger.error(f'Slack API error: {e}')
            return {'ok': False, 'error': str(e)}

    def send_message(self, channel: str, text: str, blocks: list = None) -> dict:
        """Send a message to a Slack channel."""
        data = {
            'channel': channel,
            'text': text,
        }
        if blocks:
            data['blocks'] = blocks
        return self._post('chat.postMessage', data)

    def send_dm(self, slack_user_id: str, text: str, blocks: list = None) -> dict:
        """Send a direct message to a Slack user."""
        # First, open a DM channel
        response = self._post('conversations.open', {'users': slack_user_id})
        if not response.get('ok'):
            return response

        channel_id = response['channel']['id']
        return self.send_message(channel_id, text, blocks)

    def notify_new_request(self, leave_request):
        """Notify about a new leave request."""
        if not self.integration.notify_new_request:
            return

        employee = leave_request.employee
        leave_type = leave_request.leave_type

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Nouvelle demande de congés",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Employé:*\n{employee.full_name}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Type:*\n{leave_type.name}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Du:*\n{leave_request.start_date.strftime('%d/%m/%Y')}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Au:*\n{leave_request.end_date.strftime('%d/%m/%Y')}"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Durée:*\n{leave_request.days_count} jour(s)"
                    }
                ]
            }
        ]

        if leave_request.reason:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Motif:*\n{leave_request.reason}"
                }
            })

        # Add action buttons for manager
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Approuver",
                        "emoji": True
                    },
                    "style": "primary",
                    "action_id": "approve_request",
                    "value": str(leave_request.id)
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Refuser",
                        "emoji": True
                    },
                    "style": "danger",
                    "action_id": "reject_request",
                    "value": str(leave_request.id)
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "Voir détails",
                        "emoji": True
                    },
                    "action_id": "view_request",
                    "value": str(leave_request.id)
                }
            ]
        })

        text = f"Nouvelle demande de congés de {employee.full_name}"

        # Notify manager via DM if mapped
        if employee.manager:
            manager_mapping = SlackUserMapping.query.filter_by(user_id=employee.manager_id).first()
            if manager_mapping:
                self.send_dm(manager_mapping.slack_user_id, text, blocks)

        # Also post to default channel if configured
        if self.integration.default_channel_id:
            self.send_message(self.integration.default_channel_id, text, blocks)

    def notify_request_approved(self, leave_request, approved_by):
        """Notify that a request was approved."""
        if not self.integration.notify_request_approved:
            return

        employee = leave_request.employee
        employee_mapping = SlackUserMapping.query.filter_by(user_id=employee.id).first()

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Demande approuvée",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"Votre demande de *{leave_request.leave_type.name}* du *{leave_request.start_date.strftime('%d/%m/%Y')}* au *{leave_request.end_date.strftime('%d/%m/%Y')}* a été approuvée par {approved_by.full_name}."
                }
            }
        ]

        text = f"Votre demande de congés a été approuvée"

        if employee_mapping:
            self.send_dm(employee_mapping.slack_user_id, text, blocks)

    def notify_request_rejected(self, leave_request, rejected_by, reason=None):
        """Notify that a request was rejected."""
        if not self.integration.notify_request_rejected:
            return

        employee = leave_request.employee
        employee_mapping = SlackUserMapping.query.filter_by(user_id=employee.id).first()

        message = f"Votre demande de *{leave_request.leave_type.name}* du *{leave_request.start_date.strftime('%d/%m/%Y')}* au *{leave_request.end_date.strftime('%d/%m/%Y')}* a été refusée par {rejected_by.full_name}."

        if reason:
            message += f"\n\n*Motif:* {reason}"

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "Demande refusée",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message
                }
            }
        ]

        text = f"Votre demande de congés a été refusée"

        if employee_mapping:
            self.send_dm(employee_mapping.slack_user_id, text, blocks)

    def get_user_info(self, slack_user_id: str) -> dict:
        """Get information about a Slack user."""
        return self._post('users.info', {'user': slack_user_id})

    def list_channels(self) -> list:
        """List available channels for notification configuration."""
        response = self._post('conversations.list', {
            'types': 'public_channel,private_channel',
            'exclude_archived': True
        })
        if response.get('ok'):
            return response.get('channels', [])
        return []

    def list_users(self) -> list:
        """List all users in the Slack workspace."""
        response = self._post('users.list', {})
        if response.get('ok'):
            return response.get('members', [])
        return []

    def sync_users_by_email(self, company_id: int) -> dict:
        """
        Synchronise les utilisateurs Slack avec CongesFlow par email.
        Retourne un dict avec les stats de synchronisation.
        """
        from app import db
        from app.models.user import User

        stats = {'linked': 0, 'already_linked': 0, 'not_found': 0, 'errors': []}

        slack_users = self.list_users()

        for slack_user in slack_users:
            # Ignorer les bots et les utilisateurs désactivés
            if slack_user.get('is_bot') or slack_user.get('deleted'):
                continue

            profile = slack_user.get('profile', {})
            email = profile.get('email', '').lower()

            if not email:
                continue

            slack_user_id = slack_user.get('id')

            # Vérifier si déjà lié
            existing_mapping = SlackUserMapping.query.filter_by(slack_user_id=slack_user_id).first()
            if existing_mapping:
                stats['already_linked'] += 1
                continue

            # Chercher l'utilisateur CongesFlow par email
            user = User.query.filter_by(
                email=email,
                company_id=company_id,
                is_active=True
            ).first()

            if user:
                # Vérifier si l'utilisateur n'a pas déjà un mapping
                user_mapping = SlackUserMapping.query.filter_by(user_id=user.id).first()
                if user_mapping:
                    stats['already_linked'] += 1
                    continue

                # Créer le mapping
                mapping = SlackUserMapping(
                    user_id=user.id,
                    slack_user_id=slack_user_id,
                    slack_username=slack_user.get('name', '')
                )
                db.session.add(mapping)
                stats['linked'] += 1
            else:
                stats['not_found'] += 1

        db.session.commit()
        return stats


def get_slack_service(company_id: int) -> SlackService | None:
    """Get a SlackService instance for a company if integration exists."""
    integration = SlackIntegration.query.filter_by(
        company_id=company_id,
        is_active=True
    ).first()

    if integration:
        return SlackService(integration)
    return None


def notify_slack_new_request(leave_request):
    """Helper to notify Slack about a new request."""
    service = get_slack_service(leave_request.employee.company_id)
    if service:
        try:
            service.notify_new_request(leave_request)
        except Exception as e:
            current_app.logger.error(f'Failed to send Slack notification: {e}')


def notify_slack_approved(leave_request, approved_by):
    """Helper to notify Slack about approval."""
    service = get_slack_service(leave_request.employee.company_id)
    if service:
        try:
            service.notify_request_approved(leave_request, approved_by)
        except Exception as e:
            current_app.logger.error(f'Failed to send Slack notification: {e}')


def notify_slack_rejected(leave_request, rejected_by, reason=None):
    """Helper to notify Slack about rejection."""
    service = get_slack_service(leave_request.employee.company_id)
    if service:
        try:
            service.notify_request_rejected(leave_request, rejected_by, reason)
        except Exception as e:
            current_app.logger.error(f'Failed to send Slack notification: {e}')
