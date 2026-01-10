"""
Document model for leave request attachments (justificatifs).
"""
from datetime import datetime
import os
from app import db


class LeaveDocument(db.Model):
    """Documents attached to leave requests (medical certificates, etc.)."""
    __tablename__ = 'leave_documents'

    id = db.Column(db.Integer, primary_key=True)
    leave_request_id = db.Column(db.Integer, db.ForeignKey('leave_requests.id'), nullable=False, index=True)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # File info
    filename = db.Column(db.String(255), nullable=False)  # Original filename
    stored_filename = db.Column(db.String(255), nullable=False)  # UUID-based stored name
    file_size = db.Column(db.Integer)  # Size in bytes
    mime_type = db.Column(db.String(100))

    # Document type
    document_type = db.Column(db.String(50), default='other')  # medical, other

    # Optional description
    description = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relations
    leave_request = db.relationship('LeaveRequest', backref=db.backref('documents', lazy='dynamic'))
    uploaded_by = db.relationship('User', backref='uploaded_documents')

    # Constants
    TYPE_JUSTIFICATIF = 'justificatif'
    TYPE_OTHER = 'other'

    TYPE_LABELS = {
        'justificatif': 'Justificatif',
        'other': 'Autre document',
    }

    # Allowed extensions
    ALLOWED_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx'}
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

    @property
    def type_label(self):
        return self.TYPE_LABELS.get(self.document_type, self.document_type)

    @property
    def file_size_display(self):
        """Human-readable file size."""
        if not self.file_size:
            return 'N/A'
        if self.file_size < 1024:
            return f'{self.file_size} B'
        elif self.file_size < 1024 * 1024:
            return f'{self.file_size / 1024:.1f} KB'
        else:
            return f'{self.file_size / (1024 * 1024):.1f} MB'

    @property
    def extension(self):
        """Get file extension."""
        if '.' in self.filename:
            return self.filename.rsplit('.', 1)[1].lower()
        return ''

    @property
    def is_image(self):
        """Check if document is an image."""
        return self.extension in {'png', 'jpg', 'jpeg', 'gif'}

    @property
    def is_pdf(self):
        """Check if document is a PDF."""
        return self.extension == 'pdf'

    @classmethod
    def allowed_file(cls, filename):
        """Check if file extension is allowed."""
        return '.' in filename and \
               filename.rsplit('.', 1)[1].lower() in cls.ALLOWED_EXTENSIONS

    def __repr__(self):
        return f'<LeaveDocument {self.filename}>'
