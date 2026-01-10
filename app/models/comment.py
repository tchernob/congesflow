"""
Comment model for leave request discussions.
"""
from datetime import datetime
from app import db


class LeaveRequestComment(db.Model):
    """Comments on leave requests for discussion between employee and approvers."""
    __tablename__ = 'leave_request_comments'

    id = db.Column(db.Integer, primary_key=True)
    leave_request_id = db.Column(db.Integer, db.ForeignKey('leave_requests.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    content = db.Column(db.Text, nullable=False)

    # Optional: mark as internal (only visible to managers/HR)
    is_internal = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    leave_request = db.relationship('LeaveRequest', backref=db.backref('comments', lazy='dynamic', order_by='LeaveRequestComment.created_at'))
    author = db.relationship('User', backref='leave_comments')

    def __repr__(self):
        return f'<LeaveRequestComment {self.id} on {self.leave_request_id}>'
