"""
Delegation model for approval delegation during absences.
"""
from datetime import datetime, date
from app import db


class ApprovalDelegation(db.Model):
    """Delegation of approval rights during a manager's absence."""
    __tablename__ = 'approval_delegations'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)

    # Who is delegating
    delegator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Who receives the delegation
    delegate_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Delegation period
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    # Optional: reason for delegation
    reason = db.Column(db.String(200))

    # Status
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    delegator = db.relationship('User', foreign_keys=[delegator_id], backref='delegations_given')
    delegate = db.relationship('User', foreign_keys=[delegate_id], backref='delegations_received')
    company = db.relationship('Company', backref='approval_delegations')

    @property
    def is_currently_active(self):
        """Check if delegation is currently in effect."""
        today = date.today()
        return self.is_active and self.start_date <= today <= self.end_date

    @classmethod
    def get_active_delegations_for(cls, delegate_id):
        """Get all active delegations where user is the delegate."""
        today = date.today()
        return cls.query.filter(
            cls.delegate_id == delegate_id,
            cls.is_active == True,
            cls.start_date <= today,
            cls.end_date >= today
        ).all()

    @classmethod
    def get_delegators_for(cls, delegate_id):
        """Get list of user IDs this user is currently delegating for."""
        delegations = cls.get_active_delegations_for(delegate_id)
        return [d.delegator_id for d in delegations]

    @classmethod
    def get_active_delegation_for(cls, delegator_id, delegate_id):
        """Check if there's an active delegation from delegator to delegate."""
        today = date.today()
        return cls.query.filter(
            cls.delegator_id == delegator_id,
            cls.delegate_id == delegate_id,
            cls.is_active == True,
            cls.start_date <= today,
            cls.end_date >= today
        ).first()

    def __repr__(self):
        return f'<ApprovalDelegation {self.delegator_id} -> {self.delegate_id}>'
