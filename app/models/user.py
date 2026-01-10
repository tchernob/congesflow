from datetime import datetime, timedelta
import secrets
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import db, login_manager


class Role(db.Model):
    __tablename__ = 'roles'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    description = db.Column(db.String(200))

    users = db.relationship('User', backref='role', lazy='dynamic')

    EMPLOYEE = 'employee'
    MANAGER = 'manager'
    HR = 'hr'
    ADMIN = 'admin'

    @staticmethod
    def insert_roles():
        roles = {
            'employee': 'Employé standard',
            'manager': 'Manager d\'équipe',
            'hr': 'Ressources Humaines',
            'admin': 'Administrateur système'
        }
        for name, description in roles.items():
            role = Role.query.filter_by(name=name).first()
            if role is None:
                role = Role(name=name, description=description)
                db.session.add(role)
        db.session.commit()


class ContractType(db.Model):
    """Types de contrat avec règles d'acquisition de congés."""
    __tablename__ = 'contract_types'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)  # CDI, CDD, Alternant, Stagiaire, etc.
    code = db.Column(db.String(20), nullable=False)  # CDI, CDD, ALT, STG, etc.
    description = db.Column(db.String(200))

    # Règles d'acquisition CP
    cp_acquisition_rate = db.Column(db.Float, default=2.08)  # Jours par mois (2.08 = 25j/an)
    cp_annual_allowance = db.Column(db.Float, default=25.0)  # Allocation annuelle totale

    # Règles RTT
    has_rtt = db.Column(db.Boolean, default=True)
    rtt_annual_allowance = db.Column(db.Float, default=10.0)  # Jours RTT par an

    # Congés spéciaux
    has_exam_leave = db.Column(db.Boolean, default=False)  # Congés pour examens (alternants)
    exam_leave_days = db.Column(db.Float, default=0)

    # Autres règles
    is_paid_leave = db.Column(db.Boolean, default=True)  # Congés payés ou non
    min_tenure_days = db.Column(db.Integer, default=0)  # Ancienneté min pour congés (ex: 0 pour salariés)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    users = db.relationship('User', backref='contract_type', lazy='dynamic')

    __table_args__ = (
        db.UniqueConstraint('company_id', 'code', name='unique_contract_code_per_company'),
    )

    # Codes standards
    CDI = 'CDI'
    CDD = 'CDD'
    ALTERNANT = 'ALT'
    STAGIAIRE = 'STG'
    INTERIM = 'INT'

    @staticmethod
    def insert_default_types(company_id):
        """Crée les types de contrat par défaut pour une entreprise."""
        defaults = [
            {
                'code': 'CDI',
                'name': 'CDI',
                'description': 'Contrat à durée indéterminée',
                'cp_acquisition_rate': 2.08,
                'cp_annual_allowance': 25.0,
                'has_rtt': True,
                'rtt_annual_allowance': 10.0,
                'has_exam_leave': False,
                'is_paid_leave': True,
            },
            {
                'code': 'CDD',
                'name': 'CDD',
                'description': 'Contrat à durée déterminée',
                'cp_acquisition_rate': 2.08,
                'cp_annual_allowance': 25.0,
                'has_rtt': True,
                'rtt_annual_allowance': 10.0,
                'has_exam_leave': False,
                'is_paid_leave': True,
            },
            {
                'code': 'ALT',
                'name': 'Alternant',
                'description': 'Contrat d\'apprentissage ou de professionnalisation',
                'cp_acquisition_rate': 2.08,
                'cp_annual_allowance': 25.0,
                'has_rtt': True,
                'rtt_annual_allowance': 10.0,
                'has_exam_leave': True,
                'exam_leave_days': 5.0,
                'is_paid_leave': True,
            },
            {
                'code': 'STG',
                'name': 'Stagiaire',
                'description': 'Convention de stage',
                'cp_acquisition_rate': 0,
                'cp_annual_allowance': 0,
                'has_rtt': False,
                'rtt_annual_allowance': 0,
                'has_exam_leave': False,
                'is_paid_leave': False,
            },
            {
                'code': 'INT',
                'name': 'Intérimaire',
                'description': 'Travail temporaire',
                'cp_acquisition_rate': 0,  # Indemnité compensatrice à la place
                'cp_annual_allowance': 0,
                'has_rtt': False,
                'rtt_annual_allowance': 0,
                'has_exam_leave': False,
                'is_paid_leave': False,
            },
        ]

        for data in defaults:
            existing = ContractType.query.filter_by(
                company_id=company_id,
                code=data['code']
            ).first()
            if not existing:
                contract_type = ContractType(company_id=company_id, **data)
                db.session.add(contract_type)

        db.session.commit()

    def __repr__(self):
        return f'<ContractType {self.code}>'


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True, index=True)
    email = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(50), nullable=False)
    last_name = db.Column(db.String(50), nullable=False)
    employee_id = db.Column(db.String(20))
    phone = db.Column(db.String(20))
    hire_date = db.Column(db.Date)
    avatar_url = db.Column(db.String(200))

    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False)
    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    contract_type_id = db.Column(db.Integer, db.ForeignKey('contract_types.id'), nullable=True)

    # Superadmin flag (for platform-level administration)
    is_superadmin = db.Column(db.Boolean, default=False)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'employee_id', name='unique_employee_id_per_company'),
    )

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Email verification
    email_verified = db.Column(db.Boolean, default=False)
    email_verification_token = db.Column(db.String(100), unique=True, nullable=True)
    email_verification_expires = db.Column(db.DateTime, nullable=True)

    # Invitation token for password setup
    invitation_token = db.Column(db.String(100), unique=True, nullable=True)
    invitation_token_expires = db.Column(db.DateTime, nullable=True)
    invitation_sent_at = db.Column(db.DateTime, nullable=True)

    # 2FA for superadmins
    twofa_code = db.Column(db.String(6), nullable=True)
    twofa_code_expires = db.Column(db.DateTime, nullable=True)

    # Relations
    leave_requests = db.relationship('LeaveRequest', backref='employee', lazy='dynamic',
                                     foreign_keys='LeaveRequest.employee_id')
    leave_balances = db.relationship('LeaveBalance', backref='user', lazy='dynamic')
    subordinates = db.relationship('User', backref=db.backref('manager', remote_side=[id]),
                                   lazy='dynamic', foreign_keys='User.manager_id')
    notifications = db.relationship('Notification', backref='user', lazy='dynamic')

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def initials(self):
        return f"{self.first_name[0]}{self.last_name[0]}".upper()

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_invitation_token(self):
        """Generate a secure invitation token valid for 7 days."""
        self.invitation_token = secrets.token_urlsafe(32)
        self.invitation_token_expires = datetime.utcnow() + timedelta(days=7)
        self.invitation_sent_at = datetime.utcnow()
        return self.invitation_token

    def verify_invitation_token(self):
        """Check if the invitation token is still valid."""
        if not self.invitation_token or not self.invitation_token_expires:
            return False
        return datetime.utcnow() < self.invitation_token_expires

    def clear_invitation_token(self):
        """Clear the invitation token after password is set."""
        self.invitation_token = None
        self.invitation_token_expires = None

    def generate_email_verification_token(self):
        """Generate a secure email verification token valid for 24 hours."""
        self.email_verification_token = secrets.token_urlsafe(32)
        self.email_verification_expires = datetime.utcnow() + timedelta(hours=24)
        return self.email_verification_token

    def verify_email_token(self):
        """Check if the email verification token is still valid."""
        if not self.email_verification_token or not self.email_verification_expires:
            return False
        return datetime.utcnow() < self.email_verification_expires

    def confirm_email(self):
        """Mark email as verified and clear the token."""
        self.email_verified = True
        self.email_verification_token = None
        self.email_verification_expires = None

    def generate_2fa_code(self):
        """Generate a 6-digit 2FA code valid for 10 minutes."""
        import random
        self.twofa_code = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        self.twofa_code_expires = datetime.utcnow() + timedelta(minutes=10)
        return self.twofa_code

    def verify_2fa_code(self, code):
        """Verify the 2FA code."""
        if not self.twofa_code or not self.twofa_code_expires:
            return False
        if datetime.utcnow() > self.twofa_code_expires:
            return False
        return self.twofa_code == code

    def clear_2fa_code(self):
        """Clear the 2FA code after successful verification."""
        self.twofa_code = None
        self.twofa_code_expires = None

    @property
    def is_pending_invitation(self):
        """Check if user has a pending invitation."""
        return self.invitation_token is not None and self.verify_invitation_token()

    def is_manager(self):
        return self.role.name in [Role.MANAGER, Role.HR, Role.ADMIN]

    def is_hr(self):
        return self.role.name in [Role.HR, Role.ADMIN]

    def is_admin(self):
        return self.role.name == Role.ADMIN

    def can_approve(self, leave_request):
        if self.is_hr():
            return True
        if self.is_manager() and leave_request.employee.manager_id == self.id:
            return True
        return False

    def get_pending_approvals(self):
        from app.models.leave import LeaveRequest
        if self.is_hr():
            return LeaveRequest.query.filter_by(status='pending_hr').all()
        elif self.is_manager():
            subordinate_ids = [u.id for u in self.subordinates]
            return LeaveRequest.query.filter(
                LeaveRequest.employee_id.in_(subordinate_ids),
                LeaveRequest.status == 'pending_manager'
            ).all()
        return []

    def __repr__(self):
        return f'<User {self.email}>'


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
