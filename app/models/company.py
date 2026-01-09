from datetime import datetime
from app import db
import secrets


class Company(db.Model):
    __tablename__ = 'companies'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20))
    address = db.Column(db.Text)
    logo_url = db.Column(db.String(200))

    # Subscription info
    plan = db.Column(db.String(20), default='free')  # free, pro, business, enterprise
    max_employees = db.Column(db.Integer, default=5)
    trial_ends_at = db.Column(db.DateTime)
    subscription_ends_at = db.Column(db.DateTime)
    billing_cycle = db.Column(db.String(20), default='monthly')  # monthly, yearly

    # Stripe integration
    stripe_customer_id = db.Column(db.String(100), unique=True, nullable=True, index=True)
    stripe_subscription_id = db.Column(db.String(100), unique=True, nullable=True)
    stripe_subscription_status = db.Column(db.String(50), nullable=True)  # active, past_due, canceled, etc.

    # Settings
    timezone = db.Column(db.String(50), default='Europe/Paris')
    locale = db.Column(db.String(10), default='fr')
    week_starts_on = db.Column(db.Integer, default=1)  # 1 = Monday

    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    users = db.relationship('User', backref='company', lazy='dynamic')
    teams = db.relationship('Team', backref='company', lazy='dynamic')
    leave_types = db.relationship('LeaveType', backref='company', lazy='dynamic')

    # Plan constants
    PLAN_FREE = 'free'
    PLAN_PRO = 'pro'
    PLAN_BUSINESS = 'business'
    PLAN_ENTERPRISE = 'enterprise'

    # Legacy - pour migration
    PLAN_TRIAL = 'trial'
    PLAN_STARTER = 'starter'

    PLAN_LIMITS = {
        'free': 5,
        'pro': 25,
        'business': 100,
        'enterprise': 9999,
        # Legacy
        'trial': 5,
        'starter': 25,
    }

    PLAN_LABELS = {
        'free': 'Gratuit',
        'pro': 'Pro',
        'business': 'Business',
        'enterprise': 'Enterprise',
        # Legacy
        'trial': 'Essai',
        'starter': 'Starter',
    }

    PLAN_PRICES = {
        'free': {'monthly': 0, 'yearly': 0},
        'pro': {'monthly': 39, 'yearly': 390},
        'business': {'monthly': 79, 'yearly': 790},
        'enterprise': {'monthly': None, 'yearly': None},  # Sur devis
    }

    PLAN_FEATURES = {
        'free': [
            'Jusqu\'à 5 utilisateurs',
            'Demandes et validations',
            'Calendrier d\'équipe',
            '1 an d\'historique',
        ],
        'pro': [
            'Jusqu\'à 25 utilisateurs',
            'Tout le plan Gratuit',
            'Intégration Slack',
            'Notifications email',
            'Export CSV',
            'Support par email',
        ],
        'business': [
            'Jusqu\'à 100 utilisateurs',
            'Tout le plan Pro',
            'Types de contrats',
            'Rapports avancés',
            'API (bientôt)',
            'Support prioritaire',
        ],
        'enterprise': [
            'Utilisateurs illimités',
            'Tout le plan Business',
            'SSO / SAML',
            'SLA garanti',
            'Account manager dédié',
            'Personnalisation',
        ],
    }

    @staticmethod
    def generate_slug(name):
        """Generate a unique slug from company name."""
        base_slug = name.lower().replace(' ', '-').replace("'", '')
        # Remove special characters
        import re
        base_slug = re.sub(r'[^a-z0-9-]', '', base_slug)

        # Check uniqueness
        slug = base_slug
        counter = 1
        while Company.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1
        return slug

    @property
    def plan_label(self):
        return self.PLAN_LABELS.get(self.plan, self.plan)

    @property
    def employee_count(self):
        return self.users.filter_by(is_active=True).count()

    @property
    def can_add_employee(self):
        return self.employee_count < self.max_employees

    @property
    def is_trial_expired(self):
        if self.plan != self.PLAN_TRIAL:
            return False
        if not self.trial_ends_at:
            return False
        return datetime.utcnow() > self.trial_ends_at

    @property
    def is_subscription_active(self):
        if self.plan == self.PLAN_TRIAL:
            return not self.is_trial_expired
        if not self.subscription_ends_at:
            return True
        return datetime.utcnow() <= self.subscription_ends_at

    def upgrade_plan(self, new_plan):
        self.plan = new_plan
        self.max_employees = self.PLAN_LIMITS.get(new_plan, 5)

    @property
    def usage_percent(self):
        """Pourcentage d'utilisation du plan."""
        if self.max_employees == 0:
            return 100
        return int((self.employee_count / self.max_employees) * 100)

    @property
    def slots_remaining(self):
        """Nombre de places restantes."""
        return max(0, self.max_employees - self.employee_count)

    @property
    def needs_upgrade(self):
        """Indique si l'entreprise approche de la limite."""
        return self.usage_percent >= 80

    @property
    def plan_price(self):
        """Prix mensuel du plan actuel."""
        return self.PLAN_PRICES.get(self.plan, {}).get('monthly', 0)

    @classmethod
    def get_plans_for_display(cls):
        """Retourne les plans formatés pour affichage."""
        plans = []
        for plan_id in ['free', 'pro', 'business', 'enterprise']:
            plans.append({
                'id': plan_id,
                'name': cls.PLAN_LABELS[plan_id],
                'price_monthly': cls.PLAN_PRICES[plan_id]['monthly'],
                'price_yearly': cls.PLAN_PRICES[plan_id]['yearly'],
                'max_users': cls.PLAN_LIMITS[plan_id],
                'features': cls.PLAN_FEATURES[plan_id],
            })
        return plans

    def __repr__(self):
        return f'<Company {self.name}>'


class CompanyInvitation(db.Model):
    """Invitation tokens for new employees."""
    __tablename__ = 'company_invitations'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    token = db.Column(db.String(100), unique=True, nullable=False)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    invited_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    is_used = db.Column(db.Boolean, default=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    company = db.relationship('Company', backref='invitations')
    role = db.relationship('Role')
    invited_by = db.relationship('User', backref='sent_invitations')

    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(32)

    @property
    def is_expired(self):
        return datetime.utcnow() > self.expires_at

    @property
    def is_valid(self):
        return not self.is_used and not self.is_expired

    def __repr__(self):
        return f'<CompanyInvitation {self.email}>'
