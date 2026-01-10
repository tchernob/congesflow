"""
Auto-approval rules for leave requests.
"""
from datetime import datetime
from app import db


class AutoApprovalRule(db.Model):
    """Rules for automatic approval of certain leave requests."""
    __tablename__ = 'auto_approval_rules'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)

    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)

    # Conditions
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=True)  # Null = all types
    max_days = db.Column(db.Float, nullable=True)  # Max duration to auto-approve (e.g., 0.5 for half-day)
    min_advance_days = db.Column(db.Integer, default=0)  # Minimum days in advance

    # Optional: only for specific roles
    applies_to_roles = db.Column(db.Text)  # Comma-separated role IDs

    # Optional: only for specific teams
    applies_to_teams = db.Column(db.Text)  # Comma-separated team IDs

    # Priority (higher = checked first)
    priority = db.Column(db.Integer, default=0)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relations
    company = db.relationship('Company', backref='auto_approval_rules')
    leave_type = db.relationship('LeaveType', backref='auto_approval_rules')
    created_by = db.relationship('User', backref='created_auto_rules')

    @property
    def role_ids_list(self):
        if not self.applies_to_roles:
            return []
        return [int(x.strip()) for x in self.applies_to_roles.split(',') if x.strip()]

    @property
    def team_ids_list(self):
        if not self.applies_to_teams:
            return []
        return [int(x.strip()) for x in self.applies_to_teams.split(',') if x.strip()]

    def applies_to_request(self, leave_request):
        """Check if this rule applies to a leave request."""
        from datetime import date

        # Check leave type
        if self.leave_type_id and leave_request.leave_type_id != self.leave_type_id:
            return False

        # Check duration
        if self.max_days is not None and leave_request.days_count > self.max_days:
            return False

        # Check advance notice
        if self.min_advance_days > 0:
            days_advance = (leave_request.start_date - date.today()).days
            if days_advance < self.min_advance_days:
                return False

        # Check role
        if self.applies_to_roles:
            if leave_request.employee.role_id not in self.role_ids_list:
                return False

        # Check team
        if self.applies_to_teams:
            if leave_request.employee.team_id not in self.team_ids_list:
                return False

        return True

    @classmethod
    def get_matching_rule(cls, leave_request):
        """Find the first matching auto-approval rule for a request."""
        rules = cls.query.filter(
            cls.company_id == leave_request.employee.company_id,
            cls.is_active == True
        ).order_by(cls.priority.desc()).all()

        for rule in rules:
            if rule.applies_to_request(leave_request):
                return rule

        return None

    @classmethod
    def should_auto_approve(cls, leave_request):
        """Check if a leave request should be auto-approved."""
        return cls.get_matching_rule(leave_request) is not None

    def __repr__(self):
        return f'<AutoApprovalRule {self.name}>'
