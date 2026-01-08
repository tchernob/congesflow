from datetime import datetime
from app import db


class Team(db.Model):
    __tablename__ = 'teams'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300))
    color = db.Column(db.String(7), default='#3B82F6')
    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'name', name='unique_team_name_per_company'),
    )

    members = db.relationship('User', backref='team', lazy='dynamic',
                              foreign_keys='User.team_id')

    @property
    def member_count(self):
        return self.members.filter_by(is_active=True).count()

    def get_absences_for_period(self, start_date, end_date):
        from app.models.leave import LeaveRequest
        member_ids = [m.id for m in self.members.filter_by(is_active=True)]
        return LeaveRequest.query.filter(
            LeaveRequest.employee_id.in_(member_ids),
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_date
        ).all()

    def __repr__(self):
        return f'<Team {self.name}>'
