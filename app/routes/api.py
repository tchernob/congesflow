from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from app import db
from app.models.user import User
from app.models.leave import LeaveRequest, LeaveType, LeaveBalance, CompanyLeaveSettings
from app.models.team import Team
from app.models.notification import Notification

bp = Blueprint('api', __name__, url_prefix='/api')


@bp.route('/calendar/events')
@login_required
def calendar_events():
    start = request.args.get('start')
    end = request.args.get('end')
    team_id = request.args.get('team_id', type=int)

    if start:
        start_date = datetime.strptime(start, '%Y-%m-%d').date()
    else:
        start_date = date.today().replace(day=1)

    if end:
        end_date = datetime.strptime(end, '%Y-%m-%d').date()
    else:
        end_date = start_date + timedelta(days=31)

    # Toujours filtrer par entreprise
    query = LeaveRequest.query.join(User).filter(
        User.company_id == current_user.company_id,
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date <= end_date,
        LeaveRequest.end_date >= start_date
    )

    # Filtrer par équipe si spécifié (vérifier que l'équipe appartient à l'entreprise)
    if team_id:
        team = Team.query.filter_by(id=team_id, company_id=current_user.company_id).first()
        if team:
            team_member_ids = [u.id for u in User.query.filter_by(team_id=team_id, company_id=current_user.company_id).all()]
            query = query.filter(LeaveRequest.employee_id.in_(team_member_ids))
    elif not current_user.is_hr():
        # Si non-RH, limiter à son équipe
        if current_user.is_manager():
            team_member_ids = [m.id for m in current_user.subordinates] + [current_user.id]
        else:
            team_member_ids = [current_user.id]
            if current_user.team_id:
                team_member_ids = [u.id for u in User.query.filter_by(team_id=current_user.team_id, company_id=current_user.company_id).all()]
        query = query.filter(LeaveRequest.employee_id.in_(team_member_ids))

    leaves = query.all()

    events = []
    for leave in leaves:
        events.append({
            'id': leave.id,
            'title': f"{leave.employee.full_name} - {leave.leave_type.name}",
            'start': leave.start_date.isoformat(),
            'end': (leave.end_date + timedelta(days=1)).isoformat(),
            'color': leave.leave_type.color,
            'extendedProps': {
                'employee_id': leave.employee_id,
                'employee_name': leave.employee.full_name,
                'leave_type': leave.leave_type.name,
                'days_count': leave.days_count,
                'status': leave.status
            }
        })

    return jsonify(events)


@bp.route('/user/balances')
@login_required
def user_balances():
    user_id = request.args.get('user_id', current_user.id, type=int)
    year = request.args.get('year', date.today().year, type=int)

    # Vérifier que l'utilisateur appartient à la même entreprise
    target_user = User.query.filter_by(id=user_id, company_id=current_user.company_id).first()
    if not target_user:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404

    # Vérifier les permissions
    if user_id != current_user.id and not current_user.is_hr():
        if not current_user.is_manager():
            return jsonify({'error': 'Non autorisé'}), 403
        subordinate_ids = [u.id for u in current_user.subordinates]
        if user_id not in subordinate_ids:
            return jsonify({'error': 'Non autorisé'}), 403

    balances = LeaveBalance.query.filter_by(user_id=user_id, year=year).all()

    result = []
    for balance in balances:
        result.append({
            'leave_type': balance.leave_type.name,
            'leave_type_code': balance.leave_type.code,
            'color': balance.leave_type.color,
            'initial': balance.initial_balance,
            'used': balance.used,
            'pending': balance.pending,
            'adjusted': balance.adjusted,
            'available': balance.available,
            'total': balance.total
        })

    return jsonify(result)


@bp.route('/leave-types')
@login_required
def leave_types():
    # Filtrer par entreprise
    types = LeaveType.query.filter_by(is_active=True, company_id=current_user.company_id).all()
    result = [{
        'id': lt.id,
        'name': lt.name,
        'code': lt.code,
        'color': lt.color,
        'requires_justification': lt.requires_justification,
        'max_consecutive_days': lt.max_consecutive_days,
        'is_paid': lt.is_paid
    } for lt in types]
    return jsonify(result)


@bp.route('/notifications')
@login_required
def notifications():
    notifications_list = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).order_by(Notification.created_at.desc()).limit(10).all()

    result = [{
        'id': n.id,
        'title': n.title,
        'message': n.message,
        'type': n.type,
        'link': n.link,
        'created_at': n.created_at.isoformat()
    } for n in notifications_list]

    return jsonify({
        'notifications': result,
        'unread_count': len(result)
    })


@bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_read(notification_id):
    # Vérifier que la notification appartient à l'utilisateur courant
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first_or_404()

    notification.mark_as_read()
    db.session.commit()

    return jsonify({'success': True})


@bp.route('/notifications/read-all', methods=['POST'])
@login_required
def mark_all_read():
    Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).update({'is_read': True})
    db.session.commit()

    return jsonify({'success': True})


@bp.route('/teams')
@login_required
def teams():
    # Filtrer par entreprise
    teams_list = Team.query.filter_by(is_active=True, company_id=current_user.company_id).all()
    result = [{
        'id': t.id,
        'name': t.name,
        'color': t.color,
        'member_count': t.member_count
    } for t in teams_list]
    return jsonify(result)


@bp.route('/stats/dashboard')
@login_required
def dashboard_stats():
    today = date.today()
    current_year = today.year
    company_id = current_user.company_id

    if current_user.is_hr():
        # Stats globales pour RH (filtrées par entreprise)
        pending_count = LeaveRequest.query.join(User).filter(
            User.company_id == company_id,
            LeaveRequest.status == LeaveRequest.STATUS_PENDING_HR
        ).count()

        absent_today = LeaveRequest.query.join(User).filter(
            User.company_id == company_id,
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today
        ).count()

        total_employees = User.query.filter_by(is_active=True, company_id=company_id).count()

    elif current_user.is_manager():
        # Stats pour manager
        pending_count = len(current_user.get_pending_approvals())
        team_ids = [m.id for m in current_user.subordinates]

        absent_today = LeaveRequest.query.filter(
            LeaveRequest.employee_id.in_(team_ids),
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= today,
            LeaveRequest.end_date >= today
        ).count()

        total_employees = len(team_ids)

    else:
        # Stats pour employé
        pending_count = LeaveRequest.query.filter_by(
            employee_id=current_user.id,
            status=LeaveRequest.STATUS_PENDING_MANAGER
        ).count()

        pending_count += LeaveRequest.query.filter_by(
            employee_id=current_user.id,
            status=LeaveRequest.STATUS_PENDING_HR
        ).count()

        absent_today = 0
        total_employees = 0

    # Solde CP de l'utilisateur courant
    cp_balance = LeaveBalance.query.join(LeaveType).filter(
        LeaveBalance.user_id == current_user.id,
        LeaveBalance.year == current_year,
        LeaveType.code == 'CP'
    ).first()

    return jsonify({
        'pending_count': pending_count,
        'absent_today': absent_today,
        'total_employees': total_employees,
        'cp_available': cp_balance.available if cp_balance else 0
    })


@bp.route('/check-conflicts')
@login_required
def check_conflicts():
    start = request.args.get('start_date')
    end = request.args.get('end_date')
    employee_id = request.args.get('employee_id', current_user.id, type=int)

    if not start or not end:
        return jsonify({'error': 'Dates requises'}), 400

    start_date = datetime.strptime(start, '%Y-%m-%d').date()
    end_date = datetime.strptime(end, '%Y-%m-%d').date()

    # Vérifier que l'employé appartient à la même entreprise
    employee = User.query.filter_by(id=employee_id, company_id=current_user.company_id).first()
    if not employee:
        return jsonify({'error': 'Utilisateur non trouvé'}), 404

    # Trouver les membres de l'équipe (filtrés par entreprise)
    if employee.team_id:
        team_member_ids = [u.id for u in User.query.filter_by(team_id=employee.team_id, company_id=current_user.company_id).all()]
    else:
        team_member_ids = []

    # Chercher les conflits
    conflicts = LeaveRequest.query.filter(
        LeaveRequest.employee_id.in_(team_member_ids),
        LeaveRequest.employee_id != employee_id,
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date <= end_date,
        LeaveRequest.end_date >= start_date
    ).all()

    result = [{
        'employee_name': c.employee.full_name,
        'start_date': c.start_date.isoformat(),
        'end_date': c.end_date.isoformat(),
        'leave_type': c.leave_type.name
    } for c in conflicts]

    return jsonify({
        'has_conflicts': len(result) > 0,
        'conflicts': result
    })
