from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, date
from functools import wraps
from app import db
from app.models.user import User, Role, ContractType
from app.models.leave import LeaveRequest, LeaveType, LeaveBalance, CompanyLeaveSettings
from app.models.team import Team
from app.models.notification import Notification

bp = Blueprint('admin', __name__, url_prefix='/admin')


def hr_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_hr():
            flash('Accès réservé aux RH', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_admin():
            flash('Accès réservé aux administrateurs', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/dashboard')
@login_required
@hr_required
def dashboard():
    # Statistiques globales
    today = date.today()
    current_year = today.year
    company_id = current_user.company_id

    # Demandes en attente RH (filtrées par entreprise)
    pending_hr = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.status == LeaveRequest.STATUS_PENDING_HR
    ).count()

    # Employés actifs de cette entreprise
    active_employees = User.query.filter_by(is_active=True, company_id=company_id).count()

    # Absences aujourd'hui dans cette entreprise
    absent_today = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date <= today,
        LeaveRequest.end_date >= today
    ).count()

    # Demandes ce mois dans cette entreprise
    month_start = today.replace(day=1)
    requests_this_month = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.created_at >= month_start
    ).count()

    stats = {
        'pending_hr': pending_hr,
        'active_employees': active_employees,
        'absent_today': absent_today,
        'requests_this_month': requests_this_month
    }

    # Demandes récentes en attente de cette entreprise
    pending_requests = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.status == LeaveRequest.STATUS_PENDING_HR
    ).order_by(LeaveRequest.created_at.desc()).limit(10).all()

    return render_template('admin/dashboard.html',
                           stats=stats,
                           pending_requests=pending_requests)


@bp.route('/requests')
@login_required
@hr_required
def requests():
    status_filter = request.args.get('status', 'pending_hr')
    year_filter = request.args.get('year', date.today().year, type=int)

    # Filtrer par entreprise
    query = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(User.company_id == current_user.company_id)

    if status_filter == 'pending_hr':
        query = query.filter(LeaveRequest.status == LeaveRequest.STATUS_PENDING_HR)
    elif status_filter != 'all':
        query = query.filter(LeaveRequest.status == status_filter)

    query = query.filter(
        db.extract('year', LeaveRequest.start_date) == year_filter
    )

    requests_list = query.order_by(LeaveRequest.created_at.desc()).all()

    return render_template('admin/requests.html',
                           requests=requests_list,
                           status_filter=status_filter,
                           year_filter=year_filter)


@bp.route('/requests/<int:request_id>')
@login_required
@hr_required
def view_request(request_id):
    # Vérifier que la demande appartient à un employé de la même entreprise
    leave_request = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        LeaveRequest.id == request_id,
        User.company_id == current_user.company_id
    ).first_or_404()
    settings = CompanyLeaveSettings.get_or_create_for_company(current_user.company_id)
    return render_template('admin/view_request.html', request=leave_request, settings=settings)


@bp.route('/requests/<int:request_id>/approve', methods=['POST'])
@login_required
@hr_required
def approve_request(request_id):
    # Vérifier que la demande appartient à un employé de la même entreprise
    leave_request = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        LeaveRequest.id == request_id,
        User.company_id == current_user.company_id
    ).first_or_404()
    settings = CompanyLeaveSettings.get_or_create_for_company(current_user.company_id)

    # Vérifier si les RH peuvent approuver selon le workflow
    can_approve = False
    if leave_request.status == LeaveRequest.STATUS_PENDING_HR:
        can_approve = True
    elif leave_request.status == LeaveRequest.STATUS_PENDING_MANAGER:
        # Les RH peuvent approuver si workflow = hr_only ou manager_or_hr
        if settings.approval_workflow in ['hr_only', 'manager_or_hr']:
            can_approve = True

    if not can_approve:
        flash('Cette demande ne peut pas être approuvée', 'error')
        return redirect(url_for('admin.view_request', request_id=request_id))

    leave_request.approve_by_hr(current_user)
    Notification.notify_leave_request_approved(leave_request, current_user)
    db.session.commit()

    # Notification Slack
    from app.services.slack_service import notify_slack_approved
    notify_slack_approved(leave_request, current_user)

    # Notification email à l'employé
    from app.services.email_service import send_leave_approved_notification
    send_leave_approved_notification(leave_request, current_user)

    flash('Demande approuvée', 'success')
    return redirect(url_for('admin.requests'))


@bp.route('/requests/<int:request_id>/reject', methods=['POST'])
@login_required
@hr_required
def reject_request(request_id):
    # Vérifier que la demande appartient à un employé de la même entreprise
    leave_request = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        LeaveRequest.id == request_id,
        User.company_id == current_user.company_id
    ).first_or_404()
    settings = CompanyLeaveSettings.get_or_create_for_company(current_user.company_id)

    # Vérifier si les RH peuvent refuser selon le workflow
    can_reject = False
    if leave_request.status == LeaveRequest.STATUS_PENDING_HR:
        can_reject = True
    elif leave_request.status == LeaveRequest.STATUS_PENDING_MANAGER:
        if settings.approval_workflow in ['hr_only', 'manager_or_hr']:
            can_reject = True

    if not can_reject:
        flash('Cette demande ne peut pas être refusée', 'error')
        return redirect(url_for('admin.view_request', request_id=request_id))

    reason = request.form.get('reason', '')
    leave_request.reject(current_user, reason)
    Notification.notify_leave_request_rejected(leave_request, current_user)
    db.session.commit()

    # Notification Slack
    from app.services.slack_service import notify_slack_rejected
    notify_slack_rejected(leave_request, current_user, reason)

    # Notification email à l'employé
    from app.services.email_service import send_leave_rejected_notification
    send_leave_rejected_notification(leave_request, current_user, reason)

    flash('Demande refusée', 'success')
    return redirect(url_for('admin.requests'))


# Gestion des utilisateurs
@bp.route('/users')
@login_required
@hr_required
def users():
    users_list = User.query.filter_by(company_id=current_user.company_id).order_by(User.last_name).all()
    teams = Team.query.filter_by(is_active=True, company_id=current_user.company_id).all()
    roles = Role.query.all()
    return render_template('admin/users.html',
                           users=users_list,
                           teams=teams,
                           roles=roles)


@bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_user():
    # Vérifier la limite du plan
    company = current_user.company
    if not company.can_add_employee:
        flash(f'Limite du plan {company.plan_label} atteinte ({company.max_employees} utilisateurs). '
              f'Passez à un plan supérieur pour ajouter plus d\'utilisateurs.', 'error')
        return redirect(url_for('admin.subscription'))

    if request.method == 'POST':
        email = request.form.get('email')
        first_name = request.form.get('first_name')
        last_name = request.form.get('last_name')
        role_id = request.form.get('role_id', type=int)
        team_id = request.form.get('team_id', type=int)
        manager_id = request.form.get('manager_id', type=int)
        contract_type_id = request.form.get('contract_type_id', type=int)

        # Revérifier la limite (en cas de concurrence)
        if not company.can_add_employee:
            flash('Limite du plan atteinte', 'error')
            return redirect(url_for('admin.users'))

        # Check for existing user with same email (globally unique)
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Un utilisateur avec cet email existe déjà', 'error')
            return redirect(url_for('admin.new_user'))

        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            role_id=role_id,
            team_id=team_id if team_id else None,
            manager_id=manager_id if manager_id else None,
            contract_type_id=contract_type_id if contract_type_id else None,
            company_id=current_user.company_id,
            email_verified=True  # Invitation = email vérifié
        )
        # Set a temporary random password - user will set their own via invitation
        import secrets
        user.set_password(secrets.token_urlsafe(32))

        # Generate invitation token
        token = user.generate_invitation_token()

        db.session.add(user)
        db.session.commit()

        # Créer les soldes de congés initiaux selon le type de contrat
        current_year = date.today().year
        contract_type = user.contract_type

        # Récupérer les types de congés de l'entreprise
        leave_types = LeaveType.query.filter_by(is_active=True, company_id=current_user.company_id).all()

        for lt in leave_types:
            initial_balance = lt.default_days

            # Adapter selon le type de contrat
            if contract_type:
                if lt.code == 'CP':
                    initial_balance = contract_type.cp_annual_allowance
                elif lt.code == 'RTT':
                    if not contract_type.has_rtt:
                        continue  # Pas de RTT pour ce type de contrat
                    initial_balance = contract_type.rtt_annual_allowance
                elif lt.code == 'EXA':  # Congés examens
                    if not contract_type.has_exam_leave:
                        continue
                    initial_balance = contract_type.exam_leave_days

            if initial_balance > 0:
                balance = LeaveBalance(
                    user_id=user.id,
                    leave_type_id=lt.id,
                    year=current_year,
                    initial_balance=initial_balance
                )
                db.session.add(balance)

        db.session.commit()

        # Send invitation email
        from app.services.email_service import send_invitation_email
        send_invitation_email(user, token, current_user)

        # Lier automatiquement le compte Slack si l'intégration est active
        from app.services.slack_service import link_user_to_slack
        slack_linked = link_user_to_slack(user)

        if slack_linked:
            flash(f'Utilisateur créé et lié à Slack. Un email d\'invitation a été envoyé à {email}.', 'success')
        else:
            flash(f'Utilisateur créé. Un email d\'invitation a été envoyé à {email}.', 'success')
        return redirect(url_for('admin.users'))

    teams = Team.query.filter_by(is_active=True, company_id=current_user.company_id).all()
    roles = Role.query.all()
    managers = User.query.filter(
        User.company_id == current_user.company_id,
        User.role_id.in_([r.id for r in Role.query.filter(Role.name.in_(['manager', 'hr', 'admin'])).all()])
    ).all()
    contract_types = ContractType.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).order_by(ContractType.name).all()

    return render_template('admin/new_user.html',
                           teams=teams,
                           roles=roles,
                           managers=managers,
                           contract_types=contract_types)


@bp.route('/users/<int:user_id>')
@login_required
@hr_required
def view_user(user_id):
    user = User.query.filter_by(id=user_id, company_id=current_user.company_id).first_or_404()
    current_year = date.today().year
    balances = LeaveBalance.query.filter_by(user_id=user.id, year=current_year).all()
    recent_requests = LeaveRequest.query.filter_by(
        employee_id=user.id
    ).order_by(LeaveRequest.created_at.desc()).limit(10).all()

    return render_template('admin/view_user.html',
                           user=user,
                           balances=balances,
                           requests=recent_requests)


@bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_user(user_id):
    user = User.query.filter_by(id=user_id, company_id=current_user.company_id).first_or_404()

    if request.method == 'POST':
        user.first_name = request.form.get('first_name')
        user.last_name = request.form.get('last_name')
        user.role_id = request.form.get('role_id', type=int)
        user.team_id = request.form.get('team_id', type=int) or None
        user.manager_id = request.form.get('manager_id', type=int) or None
        user.contract_type_id = request.form.get('contract_type_id', type=int) or None
        user.is_active = request.form.get('is_active') == 'on'

        new_password = request.form.get('password')
        if new_password:
            user.set_password(new_password)

        db.session.commit()
        flash('Utilisateur mis à jour', 'success')
        return redirect(url_for('admin.view_user', user_id=user_id))

    teams = Team.query.filter_by(is_active=True, company_id=current_user.company_id).all()
    roles = Role.query.all()
    managers = User.query.filter(
        User.company_id == current_user.company_id,
        User.role_id.in_([r.id for r in Role.query.filter(Role.name.in_(['manager', 'hr', 'admin'])).all()])
    ).all()
    contract_types = ContractType.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).order_by(ContractType.name).all()

    return render_template('admin/edit_user.html',
                           user=user,
                           teams=teams,
                           roles=roles,
                           managers=managers,
                           contract_types=contract_types)


# Gestion des équipes
@bp.route('/teams')
@login_required
@hr_required
def teams():
    teams_list = Team.query.filter_by(company_id=current_user.company_id).all()
    return render_template('admin/teams.html', teams=teams_list)


@bp.route('/teams/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_team():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        color = request.form.get('color', '#3B82F6')

        if Team.query.filter_by(name=name, company_id=current_user.company_id).first():
            flash('Une équipe avec ce nom existe déjà', 'error')
            return redirect(url_for('admin.new_team'))

        team = Team(name=name, description=description, color=color, company_id=current_user.company_id)
        db.session.add(team)
        db.session.commit()

        flash('Équipe créée avec succès', 'success')
        return redirect(url_for('admin.teams'))

    return render_template('admin/new_team.html')


# Gestion des types de congés
@bp.route('/leave-types')
@login_required
@hr_required
def leave_types():
    types = LeaveType.query.filter_by(company_id=current_user.company_id).all()
    return render_template('admin/leave_types.html', leave_types=types)


@bp.route('/leave-types/new', methods=['GET', 'POST'])
@login_required
@admin_required
def new_leave_type():
    if request.method == 'POST':
        name = request.form.get('name')
        code = request.form.get('code').upper()
        description = request.form.get('description')
        color = request.form.get('color', '#3B82F6')
        requires_justification = request.form.get('requires_justification') == 'on'
        max_days = request.form.get('max_consecutive_days', type=int)
        default_days = request.form.get('default_days', 0, type=float)
        is_paid = request.form.get('is_paid') == 'on'

        if LeaveType.query.filter_by(code=code, company_id=current_user.company_id).first():
            flash('Un type de congé avec ce code existe déjà', 'error')
            return redirect(url_for('admin.new_leave_type'))

        leave_type = LeaveType(
            name=name,
            code=code,
            description=description,
            color=color,
            requires_justification=requires_justification,
            max_consecutive_days=max_days,
            default_days=default_days,
            is_paid=is_paid,
            company_id=current_user.company_id
        )
        db.session.add(leave_type)
        db.session.commit()

        flash('Type de congé créé avec succès', 'success')
        return redirect(url_for('admin.leave_types'))

    return render_template('admin/new_leave_type.html')


@bp.route('/leave-types/<int:type_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_leave_type(type_id):
    """Modifier un type de congés."""
    leave_type = LeaveType.query.filter_by(
        id=type_id,
        company_id=current_user.company_id
    ).first_or_404()

    # Types protégés (code non modifiable)
    protected_codes = ['CP', 'RTT']
    is_protected = leave_type.code in protected_codes

    if request.method == 'POST':
        leave_type.name = request.form.get('name')
        leave_type.description = request.form.get('description')
        leave_type.color = request.form.get('color', '#3B82F6')
        leave_type.requires_justification = request.form.get('requires_justification') == 'on'
        leave_type.max_consecutive_days = request.form.get('max_consecutive_days', type=int)
        leave_type.default_days = request.form.get('default_days', 0, type=float)
        leave_type.is_paid = request.form.get('is_paid') == 'on'

        # Ne pas permettre la désactivation des types protégés
        if not is_protected:
            leave_type.is_active = request.form.get('is_active') == 'on'

        db.session.commit()
        flash('Type de congé mis à jour', 'success')
        return redirect(url_for('admin.leave_types'))

    return render_template('admin/edit_leave_type.html',
                           leave_type=leave_type,
                           is_protected=is_protected)


@bp.route('/leave-types/<int:type_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_leave_type(type_id):
    """Activer/désactiver un type de congés."""
    leave_type = LeaveType.query.filter_by(
        id=type_id,
        company_id=current_user.company_id
    ).first_or_404()

    # Types protégés ne peuvent pas être désactivés
    protected_codes = ['CP', 'RTT']
    if leave_type.code in protected_codes:
        flash(f'Le type {leave_type.code} ne peut pas être désactivé', 'error')
        return redirect(url_for('admin.leave_types'))

    leave_type.is_active = not leave_type.is_active
    db.session.commit()

    status = 'activé' if leave_type.is_active else 'désactivé'
    flash(f'Type "{leave_type.name}" {status}', 'success')
    return redirect(url_for('admin.leave_types'))


# Rapports
@bp.route('/reports')
@login_required
@hr_required
def reports():
    return render_template('admin/reports.html')


@bp.route('/reports/export')
@login_required
@hr_required
def export_report():
    report_type = request.args.get('type', 'absences')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # TODO: Implémenter l'export CSV/Excel
    flash('Export en cours de développement', 'info')
    return redirect(url_for('admin.reports'))


# Calendrier global
@bp.route('/calendar')
@login_required
@hr_required
def calendar():
    teams = Team.query.filter_by(is_active=True, company_id=current_user.company_id).all()
    return render_template('admin/calendar.html', teams=teams)


# Gestion des soldes
@bp.route('/balances')
@login_required
@hr_required
def balances():
    year = request.args.get('year', date.today().year, type=int)
    users = User.query.filter_by(is_active=True, company_id=current_user.company_id).order_by(User.last_name).all()
    leave_types = LeaveType.query.filter_by(is_active=True, company_id=current_user.company_id).all()

    return render_template('admin/balances.html',
                           users=users,
                           leave_types=leave_types,
                           year=year)


def parse_french_float(value):
    """Parse a French-formatted number (comma as decimal separator)."""
    if not value:
        return None
    # Replace comma with dot for parsing
    value = str(value).strip().replace(',', '.')
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


@bp.route('/balances/<int:user_id>/adjust', methods=['POST'])
@login_required
@hr_required
def adjust_balance(user_id):
    # Vérifier que l'utilisateur appartient à la même entreprise
    user = User.query.filter_by(id=user_id, company_id=current_user.company_id).first_or_404()

    leave_type_id = request.form.get('leave_type_id', type=int)
    year = request.form.get('year', date.today().year, type=int)
    reason = request.form.get('reason', '')

    # Récupérer les nouveaux soldes souhaités (format français avec virgule)
    new_balance = parse_french_float(request.form.get('new_balance'))
    new_balance_n1 = parse_french_float(request.form.get('new_balance_n1'))
    new_balance_n = parse_french_float(request.form.get('new_balance_n'))

    # Vérifier que le type de congé appartient à la même entreprise
    leave_type = LeaveType.query.filter_by(id=leave_type_id, company_id=current_user.company_id).first_or_404()

    balance = LeaveBalance.query.filter_by(
        user_id=user_id,
        leave_type_id=leave_type_id,
        year=year
    ).first()

    if not balance:
        balance = LeaveBalance(
            user_id=user_id,
            leave_type_id=leave_type_id,
            year=year,
            initial_balance=0
        )
        db.session.add(balance)

    # Appliquer les ajustements en calculant la différence
    messages = []

    if leave_type.code == 'CP' and (new_balance_n1 is not None or new_balance_n is not None):
        # Ajustement dual pour CP
        if new_balance_n1 is not None:
            current_n1 = balance.carried_over or 0
            adjustment_n1 = new_balance_n1 - current_n1
            if adjustment_n1 != 0:
                balance.carried_over = new_balance_n1
                messages.append(f'CP N-1 : {current_n1:.1f} → {new_balance_n1:.1f}j')
        if new_balance_n is not None:
            # Calculer le solde N actuel (initial + adjusted - used)
            current_n = balance.initial_balance + balance.adjusted - balance.used
            adjustment_n = new_balance_n - current_n
            if adjustment_n != 0:
                balance.adjusted += adjustment_n
                messages.append(f'CP N : {current_n:.1f} → {new_balance_n:.1f}j')
    elif new_balance is not None:
        # Ajustement standard - calculer le solde actuel total
        current_total = balance.initial_balance + (balance.carried_over or 0) + balance.adjusted - balance.used
        adjustment = new_balance - current_total
        if adjustment != 0:
            balance.adjusted += adjustment
            messages.append(f'{current_total:.1f} → {new_balance:.1f}j')

    db.session.commit()

    if messages:
        flash(f'Solde ajusté ({", ".join(messages)})', 'success')
    else:
        flash('Aucun ajustement effectué', 'info')

    return redirect(url_for('admin.balances', year=year))


# Intégration Slack
@bp.route('/slack')
@login_required
@admin_required
def slack_settings():
    from app.models.slack import SlackIntegration, SlackUserMapping
    from app.services.slack_service import SlackService

    integration = SlackIntegration.query.filter_by(
        company_id=current_user.company_id
    ).first()

    channels = []
    linked_users = []

    if integration and integration.is_active:
        service = SlackService(integration)
        channels = service.list_channels()

        # Récupérer les utilisateurs liés
        linked_users = SlackUserMapping.query.join(User).filter(
            User.company_id == current_user.company_id
        ).all()

    return render_template('admin/slack_settings.html',
                           integration=integration,
                           channels=channels,
                           linked_users=linked_users)


# Paramètres des congés (périodes, reports, etc.)
@bp.route('/leave-settings', methods=['GET', 'POST'])
@login_required
@hr_required
def leave_settings():
    from app.services.leave_period_service import LeavePeriodService

    settings = CompanyLeaveSettings.get_or_create_for_company(current_user.company_id)
    service = LeavePeriodService(current_user.company_id)

    if request.method == 'POST':
        # Période de référence
        settings.reference_period_type = request.form.get('reference_period_type', 'legal')
        if settings.reference_period_type == 'custom':
            settings.custom_period_start_day = request.form.get('custom_period_start_day', 1, type=int)
            settings.custom_period_start_month = request.form.get('custom_period_start_month', 6, type=int)

        # Règles de report CP
        settings.cp_carryover_enabled = request.form.get('cp_carryover_enabled') == 'on'
        settings.cp_carryover_max_days = request.form.get('cp_carryover_max_days', 5, type=float)
        settings.cp_carryover_deadline_months = request.form.get('cp_carryover_deadline_months', 3, type=int)

        # Règles de report RTT
        settings.rtt_carryover_enabled = request.form.get('rtt_carryover_enabled') == 'on'
        settings.rtt_carryover_max_days = request.form.get('rtt_carryover_max_days', 0, type=float)
        settings.rtt_carryover_deadline_months = request.form.get('rtt_carryover_deadline_months', 1, type=int)

        # Règles générales
        settings.allow_negative_balance = request.form.get('allow_negative_balance') == 'on'
        settings.max_negative_days = request.form.get('max_negative_days', 0, type=float)
        settings.monthly_acquisition_rate = request.form.get('monthly_acquisition_rate', 2.08, type=float)

        # Alertes
        settings.alert_days_before_expiry = request.form.get('alert_days_before_expiry', 30, type=int)
        settings.alert_low_balance_threshold = request.form.get('alert_low_balance_threshold', 5, type=float)

        # Workflow de validation
        settings.approval_workflow = request.form.get('approval_workflow', 'manager_then_hr')

        db.session.commit()
        flash('Paramètres des congés mis à jour', 'success')
        return redirect(url_for('admin.leave_settings'))

    # Calculer les dates de la période actuelle pour l'affichage
    current_period = service.get_current_period()
    period_label = service.get_period_label()

    # Vérifier les congés qui expirent bientôt
    expiring_soon = service.check_expiring_balances()

    return render_template('admin/leave_settings.html',
                           settings=settings,
                           current_period=current_period,
                           period_label=period_label,
                           expiring_soon=expiring_soon)


@bp.route('/leave-settings/process-rollover', methods=['POST'])
@login_required
@hr_required
def process_rollover():
    """Traite manuellement les reports de congés."""
    from app.services.leave_period_service import LeavePeriodService

    service = LeavePeriodService(current_user.company_id)
    results = service.process_all_rollovers_for_company()

    if results:
        flash(f'{len(results)} report(s) traité(s) avec succès', 'success')
    else:
        flash('Aucun report à traiter', 'info')

    return redirect(url_for('admin.leave_settings'))


@bp.route('/leave-settings/send-expiry-alerts', methods=['POST'])
@login_required
@hr_required
def send_expiry_alerts():
    """Envoie les alertes d'expiration manuellement."""
    from app.services.leave_period_service import LeavePeriodService

    service = LeavePeriodService(current_user.company_id)
    count = service.send_expiry_alerts()

    if count > 0:
        flash(f'{count} alerte(s) envoyée(s)', 'success')
    else:
        flash('Aucune alerte à envoyer', 'info')

    return redirect(url_for('admin.leave_settings'))


# Gestion des types de contrat
@bp.route('/contract-types')
@login_required
@hr_required
def contract_types():
    """Liste des types de contrat."""
    types = ContractType.query.filter_by(
        company_id=current_user.company_id
    ).order_by(ContractType.name).all()
    return render_template('admin/contract_types.html', contract_types=types)


@bp.route('/contract-types/new', methods=['GET', 'POST'])
@login_required
@hr_required
def new_contract_type():
    """Créer un nouveau type de contrat."""
    if request.method == 'POST':
        code = request.form.get('code', '').upper().strip()
        name = request.form.get('name', '').strip()

        # Vérifier unicité du code
        existing = ContractType.query.filter_by(
            company_id=current_user.company_id,
            code=code
        ).first()
        if existing:
            flash('Un type de contrat avec ce code existe déjà', 'error')
            return redirect(url_for('admin.new_contract_type'))

        contract_type = ContractType(
            company_id=current_user.company_id,
            code=code,
            name=name,
            description=request.form.get('description', ''),
            cp_acquisition_rate=request.form.get('cp_acquisition_rate', 2.08, type=float),
            cp_annual_allowance=request.form.get('cp_annual_allowance', 25.0, type=float),
            has_rtt=request.form.get('has_rtt') == 'on',
            rtt_annual_allowance=request.form.get('rtt_annual_allowance', 10.0, type=float),
            has_exam_leave=request.form.get('has_exam_leave') == 'on',
            exam_leave_days=request.form.get('exam_leave_days', 0, type=float),
            is_paid_leave=request.form.get('is_paid_leave') == 'on',
        )
        db.session.add(contract_type)
        db.session.commit()

        flash(f'Type de contrat "{name}" créé avec succès', 'success')
        return redirect(url_for('admin.contract_types'))

    return render_template('admin/new_contract_type.html')


@bp.route('/contract-types/<int:type_id>/edit', methods=['GET', 'POST'])
@login_required
@hr_required
def edit_contract_type(type_id):
    """Modifier un type de contrat."""
    contract_type = ContractType.query.filter_by(
        id=type_id,
        company_id=current_user.company_id
    ).first_or_404()

    if request.method == 'POST':
        contract_type.name = request.form.get('name', '').strip()
        contract_type.description = request.form.get('description', '')
        contract_type.cp_acquisition_rate = request.form.get('cp_acquisition_rate', 2.08, type=float)
        contract_type.cp_annual_allowance = request.form.get('cp_annual_allowance', 25.0, type=float)
        contract_type.has_rtt = request.form.get('has_rtt') == 'on'
        contract_type.rtt_annual_allowance = request.form.get('rtt_annual_allowance', 10.0, type=float)
        contract_type.has_exam_leave = request.form.get('has_exam_leave') == 'on'
        contract_type.exam_leave_days = request.form.get('exam_leave_days', 0, type=float)
        contract_type.is_paid_leave = request.form.get('is_paid_leave') == 'on'
        contract_type.is_active = request.form.get('is_active') == 'on'

        db.session.commit()
        flash('Type de contrat mis à jour', 'success')
        return redirect(url_for('admin.contract_types'))

    return render_template('admin/edit_contract_type.html', contract_type=contract_type)


@bp.route('/contract-types/init', methods=['POST'])
@login_required
@hr_required
def init_contract_types():
    """Initialiser les types de contrat par défaut."""
    ContractType.insert_default_types(current_user.company_id)
    flash('Types de contrat par défaut créés', 'success')
    return redirect(url_for('admin.contract_types'))


# Gestion de l'abonnement
@bp.route('/subscription')
@login_required
@admin_required
def subscription():
    """Page de gestion de l'abonnement."""
    from app.models.company import Company

    company = current_user.company
    plans = Company.get_plans_for_display()

    return render_template('admin/subscription.html',
                           company=company,
                           plans=plans)
