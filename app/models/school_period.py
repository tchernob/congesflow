"""
School period model for tracking when alternants are at school.
"""
from datetime import datetime, date
from app import db


class SchoolPeriod(db.Model):
    """Periods when an alternant is at school (not working)."""
    __tablename__ = 'school_periods'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)

    # Optional description (e.g., "Semaine de cours", "Examens")
    description = db.Column(db.String(200))

    # Recurrence pattern (optional, for future use)
    # e.g., "weekly:1,2,3" for weeks 1,2,3 of month
    recurrence_pattern = db.Column(db.String(100))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relations
    user = db.relationship('User', foreign_keys=[user_id], backref='school_periods')
    company = db.relationship('Company', backref='school_periods')
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    @property
    def duration_days(self):
        """Calculate number of days."""
        if not self.start_date or not self.end_date:
            return 0
        return (self.end_date - self.start_date).days + 1

    def overlaps_with(self, start_date, end_date):
        """Check if a date range overlaps with this school period."""
        return not (end_date < self.start_date or start_date > self.end_date)

    def contains_date(self, check_date):
        """Check if a specific date falls within this period."""
        return self.start_date <= check_date <= self.end_date

    @classmethod
    def get_for_user(cls, user_id, start_date=None, end_date=None):
        """Get school periods for a user, optionally filtered by date range."""
        query = cls.query.filter(cls.user_id == user_id)

        if start_date and end_date:
            query = query.filter(
                cls.start_date <= end_date,
                cls.end_date >= start_date
            )

        return query.order_by(cls.start_date).all()

    @classmethod
    def get_for_company(cls, company_id, start_date=None, end_date=None):
        """Get all school periods for a company, optionally filtered by date range."""
        query = cls.query.filter(cls.company_id == company_id)

        if start_date and end_date:
            query = query.filter(
                cls.start_date <= end_date,
                cls.end_date >= start_date
            )

        return query.order_by(cls.start_date).all()

    @classmethod
    def get_users_at_school_on_date(cls, company_id, check_date):
        """Get all users who are at school on a specific date."""
        periods = cls.query.filter(
            cls.company_id == company_id,
            cls.start_date <= check_date,
            cls.end_date >= check_date
        ).all()

        return [period.user for period in periods]

    @classmethod
    def is_user_at_school(cls, user_id, check_date):
        """Check if a user is at school on a specific date."""
        return cls.query.filter(
            cls.user_id == user_id,
            cls.start_date <= check_date,
            cls.end_date >= check_date
        ).first() is not None

    def __repr__(self):
        return f'<SchoolPeriod {self.user_id} {self.start_date} - {self.end_date}>'
