"""
Announcement model for company-wide messages.
"""
from datetime import datetime, date
from app import db


class Announcement(db.Model):
    """Company announcements visible to all employees."""
    __tablename__ = 'announcements'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, index=True)

    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)

    # Announcement type for styling
    announcement_type = db.Column(db.String(20), default='info')  # info, warning, success, urgent

    # Visibility
    is_pinned = db.Column(db.Boolean, default=False)  # Always show at top
    publish_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)  # None = never expires

    # Target audience (empty = all)
    team_ids = db.Column(db.Text)  # Comma-separated team IDs

    is_active = db.Column(db.Boolean, default=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    company = db.relationship('Company', backref='announcements')
    author = db.relationship('User', backref='announcements_created')

    # Constants
    TYPE_INFO = 'info'
    TYPE_WARNING = 'warning'
    TYPE_SUCCESS = 'success'
    TYPE_URGENT = 'urgent'

    TYPE_LABELS = {
        'info': 'Information',
        'warning': 'Attention',
        'success': 'Bonne nouvelle',
        'urgent': 'Urgent',
    }

    TYPE_COLORS = {
        'info': '#3B82F6',
        'warning': '#F59E0B',
        'success': '#10B981',
        'urgent': '#EF4444',
    }

    @property
    def type_label(self):
        return self.TYPE_LABELS.get(self.announcement_type, self.announcement_type)

    @property
    def type_color(self):
        return self.TYPE_COLORS.get(self.announcement_type, '#6B7280')

    @property
    def team_ids_list(self):
        """Get list of team IDs."""
        if not self.team_ids:
            return []
        return [int(x.strip()) for x in self.team_ids.split(',') if x.strip()]

    @property
    def is_published(self):
        """Check if announcement is currently published."""
        now = datetime.utcnow()
        if not self.is_active:
            return False
        if self.publish_at and now < self.publish_at:
            return False
        if self.expires_at and now > self.expires_at:
            return False
        return True

    def is_visible_to(self, user):
        """Check if announcement is visible to a specific user."""
        if not self.is_published:
            return False
        if not self.team_ids:
            return True  # Visible to all
        return user.team_id in self.team_ids_list

    @classmethod
    def get_active_for_user(cls, user):
        """Get all active announcements for a user."""
        now = datetime.utcnow()
        announcements = cls.query.filter(
            cls.company_id == user.company_id,
            cls.is_active == True,
            cls.publish_at <= now,
            db.or_(cls.expires_at == None, cls.expires_at > now)
        ).order_by(cls.is_pinned.desc(), cls.publish_at.desc()).all()

        # Filter by team
        return [a for a in announcements if a.is_visible_to(user)]

    def __repr__(self):
        return f'<Announcement {self.title}>'
