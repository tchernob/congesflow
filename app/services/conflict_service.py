"""
Service for detecting leave conflicts within teams.
"""
from datetime import date, timedelta
from app import db
from app.models.leave import LeaveRequest
from app.models.user import User
from app.models.team import Team


class ConflictService:
    """Service to detect and manage leave conflicts."""

    def __init__(self, company_id):
        self.company_id = company_id

    def get_team_conflicts(self, team_id, start_date, end_date, exclude_request_id=None):
        """
        Get all approved or pending leaves that overlap with the given period.
        Returns list of conflicting LeaveRequest objects.
        """
        team = Team.query.get(team_id)
        if not team:
            return []

        member_ids = [m.id for m in team.members if m.is_active]
        if not member_ids:
            return []

        query = LeaveRequest.query.filter(
            LeaveRequest.employee_id.in_(member_ids),
            LeaveRequest.status.in_(['approved', 'pending_manager', 'pending_hr']),
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_date
        )

        if exclude_request_id:
            query = query.filter(LeaveRequest.id != exclude_request_id)

        return query.all()

    def get_conflict_summary(self, team_id, start_date, end_date, exclude_request_id=None):
        """
        Get a summary of conflicts for a given period.
        Returns dict with conflict info.
        """
        conflicts = self.get_team_conflicts(team_id, start_date, end_date, exclude_request_id)

        if not conflicts:
            return {
                'has_conflicts': False,
                'conflict_count': 0,
                'employees': [],
                'severity': 'none'
            }

        employees = []
        for c in conflicts:
            employees.append({
                'id': c.employee_id,
                'name': c.employee.full_name,
                'leave_type': c.leave_type.name,
                'start_date': c.start_date,
                'end_date': c.end_date,
                'status': c.status
            })

        # Determine severity based on team size
        team = Team.query.get(team_id)
        team_size = len([m for m in team.members if m.is_active]) if team else 0

        # Calculate max overlap percentage
        overlap_count = len(conflicts) + 1  # +1 for the new request
        overlap_percentage = (overlap_count / team_size * 100) if team_size > 0 else 100

        if overlap_percentage >= 50:
            severity = 'high'
        elif overlap_percentage >= 25:
            severity = 'medium'
        else:
            severity = 'low'

        return {
            'has_conflicts': True,
            'conflict_count': len(conflicts),
            'employees': employees,
            'severity': severity,
            'overlap_percentage': round(overlap_percentage, 1),
            'team_size': team_size
        }

    def get_team_availability(self, team_id, check_date):
        """
        Get team availability for a specific date.
        Returns dict with available and absent counts.
        """
        team = Team.query.get(team_id)
        if not team:
            return {'available': 0, 'absent': 0, 'total': 0}

        members = [m for m in team.members if m.is_active]
        total = len(members)
        member_ids = [m.id for m in members]

        if not member_ids:
            return {'available': 0, 'absent': 0, 'total': 0}

        absent = LeaveRequest.query.filter(
            LeaveRequest.employee_id.in_(member_ids),
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= check_date,
            LeaveRequest.end_date >= check_date
        ).count()

        return {
            'available': total - absent,
            'absent': absent,
            'total': total,
            'availability_percentage': round((total - absent) / total * 100, 1) if total > 0 else 100
        }

    def get_weekly_availability(self, team_id, start_date=None):
        """
        Get team availability for the next 7 days.
        Returns list of daily availability.
        """
        if start_date is None:
            start_date = date.today()

        availability = []
        for i in range(7):
            check_date = start_date + timedelta(days=i)
            daily = self.get_team_availability(team_id, check_date)
            daily['date'] = check_date
            daily['weekday'] = check_date.strftime('%a')
            availability.append(daily)

        return availability

    @classmethod
    def check_max_concurrent_absences(cls, company_id, team_id, start_date, end_date, max_absences=None):
        """
        Check if adding a leave request would exceed max concurrent absences.
        Returns True if it's OK to add the leave, False otherwise.
        """
        from app.models.blocked_period import BlockedPeriod

        # Check if there's a blocked period with max_concurrent_absences
        blocked_periods = BlockedPeriod.get_blocking_periods(
            company_id, start_date, end_date, team_id
        )

        for period in blocked_periods:
            if period.max_concurrent_absences > 0:
                # Count current approved absences
                team = Team.query.get(team_id)
                if team:
                    member_ids = [m.id for m in team.members if m.is_active]
                    current_absences = LeaveRequest.query.filter(
                        LeaveRequest.employee_id.in_(member_ids),
                        LeaveRequest.status == 'approved',
                        LeaveRequest.start_date <= end_date,
                        LeaveRequest.end_date >= start_date
                    ).count()

                    if current_absences >= period.max_concurrent_absences:
                        return False

        return True
