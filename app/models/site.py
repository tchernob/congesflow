"""
Site model for multi-location companies with different holidays.
"""
from datetime import datetime, date
from app import db


class Site(db.Model):
    """Company site/location with specific settings."""
    __tablename__ = 'sites'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)

    name = db.Column(db.String(100), nullable=False)
    code = db.Column(db.String(20))  # Short code like "PAR", "LYO"
    address = db.Column(db.Text)
    timezone = db.Column(db.String(50), default='Europe/Paris')
    country = db.Column(db.String(2), default='FR')  # ISO country code

    # Work schedule
    work_days = db.Column(db.String(20), default='1,2,3,4,5')  # Mon-Fri by default

    is_main = db.Column(db.Boolean, default=False)  # Main/HQ site
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    company = db.relationship('Company', backref='sites')
    holidays = db.relationship('SiteHoliday', backref='site', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.UniqueConstraint('company_id', 'code', name='unique_site_code_per_company'),
    )

    @property
    def work_days_list(self):
        """Get list of work days (1=Monday, 7=Sunday)."""
        if not self.work_days:
            return [1, 2, 3, 4, 5]
        return [int(x.strip()) for x in self.work_days.split(',') if x.strip()]

    def is_work_day(self, d):
        """Check if a date is a work day for this site."""
        # Check day of week (1=Monday in isoweekday)
        if d.isoweekday() not in self.work_days_list:
            return False
        # Check holidays
        if self.holidays.filter_by(date=d).first():
            return False
        return True

    def get_holidays_for_year(self, year):
        """Get all holidays for a specific year."""
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        return self.holidays.filter(
            SiteHoliday.date >= start,
            SiteHoliday.date <= end
        ).order_by(SiteHoliday.date).all()

    def __repr__(self):
        return f'<Site {self.name}>'


class SiteHoliday(db.Model):
    """Public holidays for a specific site."""
    __tablename__ = 'site_holidays'

    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('sites.id'), nullable=False, index=True)

    date = db.Column(db.Date, nullable=False)
    name = db.Column(db.String(100), nullable=False)  # e.g., "Jour de l'An"

    # Is this a recurring holiday (same date every year)?
    is_recurring = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('site_id', 'date', name='unique_holiday_per_site_date'),
    )

    def __repr__(self):
        return f'<SiteHoliday {self.name} on {self.date}>'


# Default French holidays
FRENCH_HOLIDAYS = [
    {'month': 1, 'day': 1, 'name': "Jour de l'An"},
    {'month': 5, 'day': 1, 'name': "Fête du Travail"},
    {'month': 5, 'day': 8, 'name': "Victoire 1945"},
    {'month': 7, 'day': 14, 'name': "Fête Nationale"},
    {'month': 8, 'day': 15, 'name': "Assomption"},
    {'month': 11, 'day': 1, 'name': "Toussaint"},
    {'month': 11, 'day': 11, 'name': "Armistice 1918"},
    {'month': 12, 'day': 25, 'name': "Noël"},
]


def create_default_holidays_for_site(site, year):
    """Create default French holidays for a site and year."""
    from datetime import date

    for holiday in FRENCH_HOLIDAYS:
        d = date(year, holiday['month'], holiday['day'])
        existing = SiteHoliday.query.filter_by(site_id=site.id, date=d).first()
        if not existing:
            h = SiteHoliday(
                site_id=site.id,
                date=d,
                name=holiday['name'],
                is_recurring=True
            )
            db.session.add(h)

    db.session.commit()
