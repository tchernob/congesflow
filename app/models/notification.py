from datetime import datetime
from app import db


class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(20), default='info')
    link = db.Column(db.String(200))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    TYPE_INFO = 'info'
    TYPE_SUCCESS = 'success'
    TYPE_WARNING = 'warning'
    TYPE_ERROR = 'error'

    @staticmethod
    def create_for_user(user_id, title, message, type='info', link=None):
        notification = Notification(
            user_id=user_id,
            title=title,
            message=message,
            type=type,
            link=link
        )
        db.session.add(notification)
        return notification

    @staticmethod
    def notify_leave_request_created(leave_request):
        if leave_request.employee.manager:
            Notification.create_for_user(
                user_id=leave_request.employee.manager_id,
                title='Nouvelle demande de congés',
                message=f'{leave_request.employee.full_name} a soumis une demande de {leave_request.leave_type.name}',
                type=Notification.TYPE_INFO,
                link=f'/manager/requests/{leave_request.id}'
            )

    @staticmethod
    def notify_leave_request_approved(leave_request, approver):
        Notification.create_for_user(
            user_id=leave_request.employee_id,
            title='Demande approuvée',
            message=f'Votre demande de {leave_request.leave_type.name} a été approuvée par {approver.full_name}',
            type=Notification.TYPE_SUCCESS,
            link=f'/employee/requests/{leave_request.id}'
        )

    @staticmethod
    def notify_leave_request_rejected(leave_request, reviewer):
        Notification.create_for_user(
            user_id=leave_request.employee_id,
            title='Demande refusée',
            message=f'Votre demande de {leave_request.leave_type.name} a été refusée par {reviewer.full_name}',
            type=Notification.TYPE_ERROR,
            link=f'/employee/requests/{leave_request.id}'
        )

    def mark_as_read(self):
        self.is_read = True

    def __repr__(self):
        return f'<Notification {self.id} - {self.user_id}>'
