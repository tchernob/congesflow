"""
Blocked period model for preventing leave requests during specific dates.
"""
from datetime import datetime, date
from app import db


class BlockedPeriod(db.Model):
    """Periods when leave requests are blocked or restricted."""
    __tablename__ = 'blocked_periods'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)

    name = db.Column(db.String(100), nullable=False)  # e.g., "Clôture comptable", "Soldes"
    reason = db.Column(db.Text)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    # Block type: 'hard' = no requests allowed, 'soft' = warning only
    block_type = db.Column(db.String(20), default='soft')

    # Optional: only block specific teams
    team_ids = db.Column(db.Text)  # Comma-separated team IDs, empty = all teams

    # Optional: only block specific leave types
    leave_type_ids = db.Column(db.Text)  # Comma-separated, empty = all types

    # Max concurrent absences allowed (0 = fully blocked for hard type)
    max_concurrent_absences = db.Column(db.Integer, default=0)

    is_active = db.Column(db.Boolean, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    company = db.relationship('Company', backref='blocked_periods')
    created_by = db.relationship('User', backref='created_blocked_periods')

    # Constants
    TYPE_HARD = 'hard'
    TYPE_SOFT = 'soft'

    @property
    def team_ids_list(self):
        """Get list of team IDs."""
        if not self.team_ids:
            return []
        return [int(x.strip()) for x in self.team_ids.split(',') if x.strip()]

    @property
    def leave_type_ids_list(self):
        """Get list of leave type IDs."""
        if not self.leave_type_ids:
            return []
        return [int(x.strip()) for x in self.leave_type_ids.split(',') if x.strip()]

    def applies_to_team(self, team_id):
        """Check if this block applies to a specific team."""
        if not self.team_ids:
            return True  # Applies to all
        return team_id in self.team_ids_list

    def applies_to_leave_type(self, leave_type_id):
        """Check if this block applies to a specific leave type."""
        if not self.leave_type_ids:
            return True  # Applies to all
        return leave_type_id in self.leave_type_ids_list

    def overlaps_with(self, start_date, end_date):
        """Check if a date range overlaps with this blocked period."""
        return not (end_date < self.start_date or start_date > self.end_date)

    @classmethod
    def get_blocking_periods(cls, company_id, start_date, end_date, team_id=None, leave_type_id=None):
        """Get all blocked periods that overlap with given dates."""
        query = cls.query.filter(
            cls.company_id == company_id,
            cls.is_active == True,
            cls.start_date <= end_date,
            cls.end_date >= start_date
        )

        periods = query.all()

        # Filter by team and leave type
        result = []
        for period in periods:
            if team_id and not period.applies_to_team(team_id):
                continue
            if leave_type_id and not period.applies_to_leave_type(leave_type_id):
                continue
            result.append(period)

        return result

    @classmethod
    def check_blocked(cls, company_id, start_date, end_date, team_id=None, leave_type_id=None):
        """Check if a date range is blocked. Returns the first blocking period or None."""
        periods = cls.get_blocking_periods(company_id, start_date, end_date, team_id, leave_type_id)

        # Return hard blocks first, then soft blocks
        for period in periods:
            if period.block_type == cls.TYPE_HARD:
                return period

        for period in periods:
            if period.block_type == cls.TYPE_SOFT:
                return period

        return None

    def __repr__(self):
        return f'<BlockedPeriod {self.name}>'
