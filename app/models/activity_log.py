"""
Activity log model for tracking important actions.
"""
from datetime import datetime
from app import db


class ActivityLog(db.Model):
    """Log of important platform activities."""
    __tablename__ = 'activity_logs'

    id = db.Column(db.Integer, primary_key=True)

    # Who performed the action
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    # Which company is affected (if applicable)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True)

    # Action details
    action = db.Column(db.String(50), nullable=False)  # login, signup, plan_change, etc.
    category = db.Column(db.String(30), default='general')  # auth, billing, admin, system
    description = db.Column(db.Text)

    # Additional context stored as JSON string
    metadata = db.Column(db.Text)  # JSON encoded extra data

    # Request info
    ip_address = db.Column(db.String(45))  # IPv6 support
    user_agent = db.Column(db.String(500))

    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # Relations
    user = db.relationship('User', backref=db.backref('activity_logs', lazy='dynamic'))
    company = db.relationship('Company', backref=db.backref('activity_logs', lazy='dynamic'))

    # Action constants
    ACTION_LOGIN = 'login'
    ACTION_LOGOUT = 'logout'
    ACTION_SIGNUP = 'signup'
    ACTION_PASSWORD_RESET = 'password_reset'
    ACTION_PLAN_CHANGE = 'plan_change'
    ACTION_SUBSCRIPTION_CREATED = 'subscription_created'
    ACTION_SUBSCRIPTION_CANCELED = 'subscription_canceled'
    ACTION_PAYMENT_SUCCESS = 'payment_success'
    ACTION_PAYMENT_FAILED = 'payment_failed'
    ACTION_COMPANY_CREATED = 'company_created'
    ACTION_COMPANY_DEACTIVATED = 'company_deactivated'
    ACTION_COMPANY_ACTIVATED = 'company_activated'
    ACTION_USER_INVITED = 'user_invited'
    ACTION_USER_DEACTIVATED = 'user_deactivated'
    ACTION_IMPERSONATE_START = 'impersonate_start'
    ACTION_IMPERSONATE_STOP = 'impersonate_stop'
    ACTION_COUPON_APPLIED = 'coupon_applied'
    ACTION_TRIAL_STARTED = 'trial_started'
    ACTION_TRIAL_EXPIRED = 'trial_expired'

    # Categories
    CATEGORY_AUTH = 'auth'
    CATEGORY_BILLING = 'billing'
    CATEGORY_ADMIN = 'admin'
    CATEGORY_SYSTEM = 'system'
    CATEGORY_ROOT = 'root'

    ACTION_LABELS = {
        'login': 'Connexion',
        'logout': 'Déconnexion',
        'signup': 'Inscription',
        'password_reset': 'Réinitialisation mot de passe',
        'plan_change': 'Changement de plan',
        'subscription_created': 'Abonnement créé',
        'subscription_canceled': 'Abonnement annulé',
        'payment_success': 'Paiement réussi',
        'payment_failed': 'Paiement échoué',
        'company_created': 'Entreprise créée',
        'company_deactivated': 'Entreprise désactivée',
        'company_activated': 'Entreprise activée',
        'user_invited': 'Utilisateur invité',
        'user_deactivated': 'Utilisateur désactivé',
        'impersonate_start': 'Impersonation démarrée',
        'impersonate_stop': 'Impersonation terminée',
        'coupon_applied': 'Coupon appliqué',
        'trial_started': 'Essai démarré',
        'trial_expired': 'Essai expiré',
    }

    CATEGORY_LABELS = {
        'auth': 'Authentification',
        'billing': 'Facturation',
        'admin': 'Administration',
        'system': 'Système',
        'root': 'Root',
    }

    CATEGORY_COLORS = {
        'auth': '#3B82F6',
        'billing': '#10B981',
        'admin': '#F59E0B',
        'system': '#6B7280',
        'root': '#7C3AED',
    }

    @property
    def action_label(self):
        return self.ACTION_LABELS.get(self.action, self.action)

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category)

    @property
    def category_color(self):
        return self.CATEGORY_COLORS.get(self.category, '#6B7280')

    @classmethod
    def log(cls, action, category='general', user_id=None, company_id=None,
            description=None, metadata=None, ip_address=None, user_agent=None):
        """Create a new activity log entry."""
        import json

        log_entry = cls(
            action=action,
            category=category,
            user_id=user_id,
            company_id=company_id,
            description=description,
            metadata=json.dumps(metadata) if metadata else None,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db.session.add(log_entry)
        return log_entry

    def get_metadata(self):
        """Parse and return metadata as dict."""
        import json
        if self.metadata:
            try:
                return json.loads(self.metadata)
            except json.JSONDecodeError:
                return {}
        return {}

    def __repr__(self):
        return f'<ActivityLog {self.action} at {self.created_at}>'
