from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from app import db
from app.models.leave import LeaveRequest, LeaveType, LeaveBalance, CompanyLeaveSettings
from app.models.notification import Notification

bp = Blueprint('employee', __name__, url_prefix='/employee')


@bp.route('/dashboard')
@login_required
def dashboard():
    # Soldes de congés
    current_year = date.today().year
    balances = LeaveBalance.query.filter_by(
        user_id=current_user.id,
        year=current_year
    ).all()

    # Demandes récentes
    recent_requests = LeaveRequest.query.filter_by(
        employee_id=current_user.id
    ).order_by(LeaveRequest.created_at.desc()).limit(5).all()

    # Prochains congés approuvés
    upcoming = LeaveRequest.query.filter(
        LeaveRequest.employee_id == current_user.id,
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date >= date.today()
    ).order_by(LeaveRequest.start_date).limit(3).all()

    # Notifications non lues
    unread_notifications = Notification.query.filter_by(
        user_id=current_user.id,
        is_read=False
    ).order_by(Notification.created_at.desc()).limit(5).all()

    return render_template('employee/dashboard.html',
                           balances=balances,
                           recent_requests=recent_requests,
                           upcoming=upcoming,
                           notifications=unread_notifications)


@bp.route('/requests')
@login_required
def requests():
    status_filter = request.args.get('status', 'all')
    year_filter = request.args.get('year', date.today().year, type=int)

    query = LeaveRequest.query.filter_by(employee_id=current_user.id)

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)

    query = query.filter(
        db.extract('year', LeaveRequest.start_date) == year_filter
    )

    requests_list = query.order_by(LeaveRequest.created_at.desc()).all()
    leave_types = LeaveType.query.filter_by(is_active=True, company_id=current_user.company_id).all()

    return render_template('employee/requests.html',
                           requests=requests_list,
                           leave_types=leave_types,
                           status_filter=status_filter,
                           year_filter=year_filter)


@bp.route('/requests/new', methods=['GET', 'POST'])
@login_required
def new_request():
    if request.method == 'POST':
        leave_type_id = request.form.get('leave_type_id', type=int)
        start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
        start_half_day = request.form.get('start_half_day') == 'on'
        end_half_day = request.form.get('end_half_day') == 'on'
        reason = request.form.get('reason', '')

        # Validation
        if start_date > end_date:
            flash('La date de fin doit être après la date de début', 'error')
            return redirect(url_for('employee.new_request'))

        if start_date < date.today():
            flash('La date de début ne peut pas être dans le passé', 'error')
            return redirect(url_for('employee.new_request'))

        # Déterminer le statut initial selon le workflow de l'entreprise
        settings = CompanyLeaveSettings.get_or_create_for_company(current_user.company_id)
        initial_status = settings.get_initial_status()

        # Créer la demande
        leave_request = LeaveRequest(
            employee_id=current_user.id,
            leave_type_id=leave_type_id,
            start_date=start_date,
            end_date=end_date,
            start_half_day=start_half_day,
            end_half_day=end_half_day,
            reason=reason,
            status=initial_status
        )
        leave_request.days_count = leave_request.calculate_days()

        # Vérifier le solde
        balance = LeaveBalance.query.filter_by(
            user_id=current_user.id,
            leave_type_id=leave_type_id,
            year=start_date.year
        ).first()

        if balance and balance.available < leave_request.days_count:
            flash(f'Solde insuffisant. Disponible: {balance.available} jours', 'error')
            return redirect(url_for('employee.new_request'))

        # Mettre à jour le solde pending
        if balance:
            balance.pending += leave_request.days_count

        db.session.add(leave_request)
        db.session.commit()

        # Notification au manager
        Notification.notify_leave_request_created(leave_request)
        db.session.commit()

        # Notification Slack
        from app.services.slack_service import notify_slack_new_request
        notify_slack_new_request(leave_request)

        flash('Demande de congés créée avec succès', 'success')
        return redirect(url_for('employee.requests'))

    leave_types = LeaveType.query.filter_by(is_active=True, company_id=current_user.company_id).all()
    today = date.today().strftime('%Y-%m-%d')
    return render_template('employee/new_request.html', leave_types=leave_types, today=today)


@bp.route('/requests/<int:request_id>')
@login_required
def view_request(request_id):
    leave_request = LeaveRequest.query.get_or_404(request_id)

    if leave_request.employee_id != current_user.id:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('employee.requests'))

    return render_template('employee/view_request.html', request=leave_request)


@bp.route('/requests/<int:request_id>/cancel', methods=['POST'])
@login_required
def cancel_request(request_id):
    leave_request = LeaveRequest.query.get_or_404(request_id)

    if leave_request.employee_id != current_user.id:
        flash('Accès non autorisé', 'error')
        return redirect(url_for('employee.requests'))

    if not leave_request.can_cancel:
        flash('Cette demande ne peut pas être annulée', 'error')
        return redirect(url_for('employee.view_request', request_id=request_id))

    leave_request.cancel()
    db.session.commit()

    flash('Demande annulée avec succès', 'success')
    return redirect(url_for('employee.requests'))


@bp.route('/calendar')
@login_required
def calendar():
    return render_template('employee/calendar.html')


@bp.route('/balances')
@login_required
def balances():
    from app.services.leave_period_service import LeavePeriodService

    service = LeavePeriodService(current_user.company_id)
    current_year = service.settings.get_current_period_year()
    period_label = service.get_period_label()

    balances = LeaveBalance.query.filter_by(
        user_id=current_user.id,
        year=current_year
    ).all()

    return render_template('employee/balances.html',
                           balances=balances,
                           year=current_year,
                           period_label=period_label)


@bp.route('/profile')
@login_required
def profile():
    return render_template('employee/profile.html')


@bp.route('/notifications')
@login_required
def notifications():
    all_notifications = Notification.query.filter_by(
        user_id=current_user.id
    ).order_by(Notification.created_at.desc()).all()

    return render_template('employee/notifications.html', notifications=all_notifications)


@bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)

    if notification.user_id != current_user.id:
        return jsonify({'error': 'Non autorisé'}), 403

    notification.mark_as_read()
    db.session.commit()

    return jsonify({'success': True})
