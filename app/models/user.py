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


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True, index=True)
    email = db.Column(db.String(120), nullable=False, index=True)
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

    # Superadmin flag (for platform-level administration)
    is_superadmin = db.Column(db.Boolean, default=False)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'email', name='unique_email_per_company'),
        db.UniqueConstraint('company_id', 'employee_id', name='unique_employee_id_per_company'),
    )

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Invitation token for password setup
    invitation_token = db.Column(db.String(100), unique=True, nullable=True)
    invitation_token_expires = db.Column(db.DateTime, nullable=True)
    invitation_sent_at = db.Column(db.DateTime, nullable=True)

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
