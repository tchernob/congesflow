from datetime import datetime
from app import db


class SlackIntegration(db.Model):
    """Stores Slack workspace integration details per company."""
    __tablename__ = 'slack_integrations'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, unique=True)

    # OAuth tokens
    access_token = db.Column(db.String(255), nullable=False)
    bot_user_id = db.Column(db.String(50))
    team_id = db.Column(db.String(50))
    team_name = db.Column(db.String(100))

    # Default channel for notifications
    default_channel_id = db.Column(db.String(50))
    default_channel_name = db.Column(db.String(100))

    # Feature toggles
    notify_new_request = db.Column(db.Boolean, default=True)
    notify_request_approved = db.Column(db.Boolean, default=True)
    notify_request_rejected = db.Column(db.Boolean, default=True)
    notify_manager_pending = db.Column(db.Boolean, default=True)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    company = db.relationship('Company', backref=db.backref('slack_integration', uselist=False))

    def __repr__(self):
        return f'<SlackIntegration {self.team_name}>'


class SlackUserMapping(db.Model):
    """Maps TimeOff users to Slack user IDs."""
    __tablename__ = 'slack_user_mappings'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    slack_user_id = db.Column(db.String(50), nullable=False)
    slack_username = db.Column(db.String(100))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationship
    user = db.relationship('User', backref=db.backref('slack_mapping', uselist=False))

    __table_args__ = (
        db.UniqueConstraint('user_id', name='unique_user_slack_mapping'),
    )

    def __repr__(self):
        return f'<SlackUserMapping {self.user_id} -> {self.slack_user_id}>'
