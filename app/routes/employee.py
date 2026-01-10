from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_from_directory, current_app
from flask_login import login_required, current_user
from datetime import datetime, date
from werkzeug.utils import secure_filename
import os
import uuid
from app import db
from app.models.leave import LeaveRequest, LeaveType, LeaveBalance, CompanyLeaveSettings
from app.models.notification import Notification
from app.models.blocked_period import BlockedPeriod
from app.models.auto_approval_rule import AutoApprovalRule
from app.models.announcement import Announcement
from app.models.document import LeaveDocument

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

    # Annonces actives pour l'employé
    announcements = Announcement.get_active_for_user(current_user)

    return render_template('employee/dashboard.html',
                           balances=balances,
                           recent_requests=recent_requests,
                           upcoming=upcoming,
                           notifications=unread_notifications,
                           announcements=announcements)


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

        # Vérifier les périodes bloquées
        blocked = BlockedPeriod.check_blocked(
            company_id=current_user.company_id,
            start_date=start_date,
            end_date=end_date,
            team_id=current_user.team_id,
            leave_type_id=leave_type_id
        )

        if blocked:
            if blocked.block_type == 'hard':
                flash(f'Période bloquée : {blocked.name}. {blocked.reason or "Demandes non autorisées."}', 'error')
                return redirect(url_for('employee.new_request'))
            else:
                # Soft block: just warn but allow
                flash(f'Attention : {blocked.name}. {blocked.reason or ""}', 'warning')

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

        # Vérifier les règles d'auto-approbation
        auto_rule = AutoApprovalRule.get_matching_rule(leave_request)
        if auto_rule:
            # Auto-approve the request
            leave_request.status = 'approved'
            leave_request.hr_reviewed_at = datetime.utcnow()

            # Update balance
            if balance:
                balance.pending -= leave_request.days_count
                balance.used += leave_request.days_count

            db.session.commit()

            # Notify employee
            Notification.create(
                user_id=current_user.id,
                type='leave_approved',
                title='Demande approuvée automatiquement',
                message=f'Votre demande du {start_date.strftime("%d/%m")} au {end_date.strftime("%d/%m")} a été approuvée automatiquement.',
                link=url_for('employee.view_request', request_id=leave_request.id)
            )
            db.session.commit()

            flash(f'Demande approuvée automatiquement (règle: {auto_rule.name})', 'success')
            return redirect(url_for('employee.requests'))

        # Notification au manager
        Notification.notify_leave_request_created(leave_request)
        db.session.commit()

        # Notification Slack
        from app.services.slack_service import notify_slack_new_request
        notify_slack_new_request(leave_request)

        # Notification email au manager
        from app.services.email_service import send_leave_request_notification
        if current_user.manager:
            send_leave_request_notification(leave_request, current_user.manager)

        flash('Demande de congés créée avec succès', 'success')
        return redirect(url_for('employee.requests'))

    leave_types = LeaveType.query.filter_by(is_active=True, company_id=current_user.company_id).all()
    today = date.today().strftime('%Y-%m-%d')

    # Get active blocked periods to show warnings
    blocked_periods = BlockedPeriod.query.filter(
        BlockedPeriod.company_id == current_user.company_id,
        BlockedPeriod.is_active == True,
        BlockedPeriod.end_date >= date.today()
    ).all()

    return render_template('employee/new_request.html',
        leave_types=leave_types,
        today=today,
        blocked_periods=blocked_periods
    )


@bp.route('/requests/<int:request_id>')
@login_required
def view_request(request_id):
    # Vérifier que la demande appartient à l'utilisateur courant
    leave_request = LeaveRequest.query.filter_by(
        id=request_id,
        employee_id=current_user.id
    ).first_or_404()

    return render_template('employee/view_request.html', request=leave_request)


@bp.route('/requests/<int:request_id>/cancel', methods=['POST'])
@login_required
def cancel_request(request_id):
    # Vérifier que la demande appartient à l'utilisateur courant
    leave_request = LeaveRequest.query.filter_by(
        id=request_id,
        employee_id=current_user.id
    ).first_or_404()

    if not leave_request.can_cancel:
        flash('Cette demande ne peut pas être annulée', 'error')
        return redirect(url_for('employee.view_request', request_id=request_id))

    leave_request.cancel()
    db.session.commit()

    flash('Demande annulée avec succès', 'success')
    return redirect(url_for('employee.requests'))


@bp.route('/requests/<int:request_id>/upload', methods=['POST'])
@login_required
def upload_document(request_id):
    """Upload a document to a leave request."""
    # Vérifier que la demande appartient à l'utilisateur courant
    leave_request = LeaveRequest.query.filter_by(
        id=request_id,
        employee_id=current_user.id
    ).first_or_404()

    if 'document' not in request.files:
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('employee.view_request', request_id=request_id))

    file = request.files['document']

    if file.filename == '':
        flash('Aucun fichier sélectionné', 'error')
        return redirect(url_for('employee.view_request', request_id=request_id))

    if not LeaveDocument.allowed_file(file.filename):
        flash('Type de fichier non autorisé. Formats acceptés: PDF, PNG, JPG, DOC, DOCX', 'error')
        return redirect(url_for('employee.view_request', request_id=request_id))

    # Check file size
    file.seek(0, 2)
    file_size = file.tell()
    file.seek(0)

    if file_size > LeaveDocument.MAX_FILE_SIZE:
        flash('Fichier trop volumineux (max 5 MB)', 'error')
        return redirect(url_for('employee.view_request', request_id=request_id))

    # Generate unique filename
    original_filename = secure_filename(file.filename)
    extension = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    stored_filename = f"{uuid.uuid4().hex}.{extension}"

    # Ensure upload directory exists
    upload_dir = os.path.join(current_app.root_path, 'uploads', 'documents', str(current_user.company_id))
    os.makedirs(upload_dir, exist_ok=True)

    # Save file
    file_path = os.path.join(upload_dir, stored_filename)
    file.save(file_path)

    # Create document record
    document = LeaveDocument(
        leave_request_id=request_id,
        uploaded_by_id=current_user.id,
        filename=original_filename,
        stored_filename=stored_filename,
        file_size=file_size,
        mime_type=file.content_type,
        document_type=request.form.get('document_type', 'other'),
        description=request.form.get('description', '')
    )

    db.session.add(document)
    db.session.commit()

    flash('Document ajouté avec succès', 'success')
    return redirect(url_for('employee.view_request', request_id=request_id))


@bp.route('/requests/<int:request_id>/documents/<int:document_id>')
@login_required
def view_document(request_id, document_id):
    """View/download a document."""
    # Vérifier que la demande appartient à l'utilisateur courant
    leave_request = LeaveRequest.query.filter_by(
        id=request_id,
        employee_id=current_user.id
    ).first_or_404()

    document = LeaveDocument.query.filter_by(
        id=document_id,
        leave_request_id=request_id
    ).first_or_404()

    upload_dir = os.path.join(current_app.root_path, 'uploads', 'documents', str(current_user.company_id))

    return send_from_directory(
        upload_dir,
        document.stored_filename,
        as_attachment=True,
        download_name=document.filename
    )


@bp.route('/requests/<int:request_id>/documents/<int:document_id>/delete', methods=['POST'])
@login_required
def delete_document(request_id, document_id):
    """Delete a document."""
    # Vérifier que la demande appartient à l'utilisateur courant
    leave_request = LeaveRequest.query.filter_by(
        id=request_id,
        employee_id=current_user.id
    ).first_or_404()

    document = LeaveDocument.query.filter_by(
        id=document_id,
        leave_request_id=request_id
    ).first_or_404()

    # Only allow deletion if request is still pending
    if leave_request.status not in ['pending_manager', 'pending_hr']:
        flash('Impossible de supprimer un document sur une demande traitée', 'error')
        return redirect(url_for('employee.view_request', request_id=request_id))

    # Delete file
    upload_dir = os.path.join(current_app.root_path, 'uploads', 'documents', str(current_user.company_id))
    file_path = os.path.join(upload_dir, document.stored_filename)

    if os.path.exists(file_path):
        os.remove(file_path)

    # Delete record
    db.session.delete(document)
    db.session.commit()

    flash('Document supprimé', 'success')
    return redirect(url_for('employee.view_request', request_id=request_id))


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
    # Vérifier que la notification appartient à l'utilisateur courant
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id
    ).first_or_404()

    notification.mark_as_read()
    db.session.commit()

    return jsonify({'success': True})
