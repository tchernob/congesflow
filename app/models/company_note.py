"""
Company notes model for internal root admin notes.
"""
from datetime import datetime
from app import db


class CompanyNote(db.Model):
    """Internal notes on companies, visible only to root admins."""
    __tablename__ = 'company_notes'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)

    # Note type for categorization
    note_type = db.Column(db.String(20), default='general')  # general, support, billing, technical

    # Optional: link to a specific event
    is_pinned = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    company = db.relationship('Company', backref=db.backref('notes', lazy='dynamic', order_by='desc(CompanyNote.created_at)'))
    author = db.relationship('User', backref='company_notes')

    # Note types
    TYPE_GENERAL = 'general'
    TYPE_SUPPORT = 'support'
    TYPE_BILLING = 'billing'
    TYPE_TECHNICAL = 'technical'

    TYPE_LABELS = {
        'general': 'Général',
        'support': 'Support',
        'billing': 'Facturation',
        'technical': 'Technique',
    }

    TYPE_COLORS = {
        'general': '#6B7280',
        'support': '#3B82F6',
        'billing': '#10B981',
        'technical': '#F59E0B',
    }

    @property
    def type_label(self):
        return self.TYPE_LABELS.get(self.note_type, self.note_type)

    @property
    def type_color(self):
        return self.TYPE_COLORS.get(self.note_type, '#6B7280')

    def __repr__(self):
        return f'<CompanyNote {self.id} for company {self.company_id}>'
