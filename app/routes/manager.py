from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from functools import wraps
from app import db
from app.models.user import User
from app.models.leave import LeaveRequest, LeaveType, LeaveBalance, CompanyLeaveSettings
from app.models.notification import Notification

bp = Blueprint('manager', __name__, url_prefix='/manager')


def manager_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_manager():
            flash('Accès réservé aux managers', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/dashboard')
@login_required
@manager_required
def dashboard():
    # Demandes en attente de validation
    pending_requests = current_user.get_pending_approvals()

    # Équipe
    team_members = current_user.subordinates.filter_by(is_active=True).all()

    # Absences en cours dans l'équipe
    today = date.today()
    team_member_ids = [m.id for m in team_members]
    current_absences = LeaveRequest.query.filter(
        LeaveRequest.employee_id.in_(team_member_ids),
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= today
    ).all()

    # Absences à venir (7 prochains jours)
    next_week = today + timedelta(days=7)
    upcoming_absences = LeaveRequest.query.filter(
        LeaveRequest.employee_id.in_(team_member_ids),
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date > today,
        LeaveRequest.start_date <= next_week
    ).order_by(LeaveRequest.start_date).all()

    # Statistiques
    stats = {
        'pending_count': len(pending_requests),
        'team_size': len(team_members),
        'absent_today': len(current_absences),
        'upcoming_count': len(upcoming_absences)
    }

    return render_template('manager/dashboard.html',
                           pending_requests=pending_requests,
                           team_members=team_members,
                           current_absences=current_absences,
                           upcoming_absences=upcoming_absences,
                           stats=stats)


@bp.route('/requests')
@login_required
@manager_required
def requests():
    status_filter = request.args.get('status', 'pending')
    team_member_ids = [m.id for m in current_user.subordinates]

    query = LeaveRequest.query.filter(LeaveRequest.employee_id.in_(team_member_ids))

    if status_filter == 'pending':
        query = query.filter_by(status=LeaveRequest.STATUS_PENDING_MANAGER)
    elif status_filter != 'all':
        query = query.filter_by(status=status_filter)

    requests_list = query.order_by(LeaveRequest.created_at.desc()).all()

    return render_template('manager/requests.html',
                           requests=requests_list,
                           status_filter=status_filter)


@bp.route('/requests/<int:request_id>')
@login_required
@manager_required
def view_request(request_id):
    # Vérifier que la demande appartient à un employé de la même entreprise
    leave_request = LeaveRequest.query.join(User).filter(
        LeaveRequest.id == request_id,
        User.company_id == current_user.company_id
    ).first_or_404()

    if not current_user.can_approve(leave_request):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('manager.requests'))

    # Vérifier les conflits d'équipe
    team_member_ids = [m.id for m in current_user.subordinates]
    conflicts = LeaveRequest.query.filter(
        LeaveRequest.employee_id.in_(team_member_ids),
        LeaveRequest.id != request_id,
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date <= leave_request.end_date,
        LeaveRequest.end_date >= leave_request.start_date
    ).all()

    settings = CompanyLeaveSettings.get_or_create_for_company(current_user.company_id)
    return render_template('manager/view_request.html',
                           request=leave_request,
                           conflicts=conflicts,
                           settings=settings)


@bp.route('/requests/<int:request_id>/approve', methods=['POST'])
@login_required
@manager_required
def approve_request(request_id):
    # Vérifier que la demande appartient à un employé de la même entreprise
    leave_request = LeaveRequest.query.join(User).filter(
        LeaveRequest.id == request_id,
        User.company_id == current_user.company_id
    ).first_or_404()

    if not current_user.can_approve(leave_request):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('manager.requests'))

    if leave_request.status != LeaveRequest.STATUS_PENDING_MANAGER:
        flash('Cette demande ne peut pas être approuvée', 'error')
        return redirect(url_for('manager.view_request', request_id=request_id))

    leave_request.approve_by_manager(current_user)
    db.session.commit()

    # Notification Slack
    from app.services.slack_service import notify_slack_approved
    notify_slack_approved(leave_request, current_user)

    flash('Demande approuvée et transmise aux RH', 'success')
    return redirect(url_for('manager.requests'))


@bp.route('/requests/<int:request_id>/reject', methods=['POST'])
@login_required
@manager_required
def reject_request(request_id):
    # Vérifier que la demande appartient à un employé de la même entreprise
    leave_request = LeaveRequest.query.join(User).filter(
        LeaveRequest.id == request_id,
        User.company_id == current_user.company_id
    ).first_or_404()

    if not current_user.can_approve(leave_request):
        flash('Accès non autorisé', 'error')
        return redirect(url_for('manager.requests'))

    if leave_request.status != LeaveRequest.STATUS_PENDING_MANAGER:
        flash('Cette demande ne peut pas être refusée', 'error')
        return redirect(url_for('manager.view_request', request_id=request_id))

    reason = request.form.get('reason', '')
    leave_request.reject(current_user, reason)

    Notification.notify_leave_request_rejected(leave_request, current_user)
    db.session.commit()

    # Notification Slack
    from app.services.slack_service import notify_slack_rejected
    notify_slack_rejected(leave_request, current_user, reason)

    flash('Demande refusée', 'success')
    return redirect(url_for('manager.requests'))


@bp.route('/team')
@login_required
@manager_required
def team():
    team_members = current_user.subordinates.filter_by(is_active=True).all()
    return render_template('manager/team.html', team_members=team_members)


@bp.route('/team/<int:user_id>')
@login_required
@manager_required
def team_member(user_id):
    # Vérifier que l'utilisateur appartient à la même entreprise et est un subordonné
    member = User.query.filter_by(
        id=user_id,
        company_id=current_user.company_id,
        manager_id=current_user.id
    ).first_or_404()

    # Soldes de congés
    current_year = date.today().year
    balances = LeaveBalance.query.filter_by(
        user_id=member.id,
        year=current_year
    ).all()

    # Historique des demandes
    requests_history = LeaveRequest.query.filter_by(
        employee_id=member.id
    ).order_by(LeaveRequest.created_at.desc()).limit(10).all()

    return render_template('manager/team_member.html',
                           member=member,
                           balances=balances,
                           requests=requests_history)


@bp.route('/calendar')
@login_required
@manager_required
def calendar():
    team_members = current_user.subordinates.filter_by(is_active=True).all()
    return render_template('manager/calendar.html', team_members=team_members)
