"""
Advanced admin routes for delegation, blocked periods, announcements, etc.
"""
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, send_file, Response
from flask_login import login_required, current_user
from datetime import datetime, date, timedelta
from functools import wraps
from app import db
from app.models.user import User, Role
from app.models.team import Team
from app.models.leave import LeaveRequest, LeaveType, LeaveBalance
from app.models.delegation import ApprovalDelegation
from app.models.blocked_period import BlockedPeriod
from app.models.announcement import Announcement
from app.models.auto_approval_rule import AutoApprovalRule
from app.models.site import Site, SiteHoliday, create_default_holidays_for_site

bp = Blueprint('admin_advanced', __name__, url_prefix='/admin')


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


# ============================================
# DELEGATIONS
# ============================================

@bp.route('/delegations')
@login_required
@hr_required
def delegations():
    """List all approval delegations."""
    delegations = ApprovalDelegation.query.filter_by(
        company_id=current_user.company_id
    ).order_by(ApprovalDelegation.start_date.desc()).all()

    managers = User.query.join(Role).filter(
        User.company_id == current_user.company_id,
        User.is_active == True,
        Role.name.in_([Role.MANAGER, Role.HR, Role.ADMIN])
    ).order_by(User.last_name).all()

    return render_template('admin/delegations.html',
        delegations=delegations,
        managers=managers,
        today=date.today()
    )


@bp.route('/delegations/create', methods=['POST'])
@login_required
@hr_required
def create_delegation():
    """Create a new delegation."""
    delegator_id = request.form.get('delegator_id', type=int)
    delegate_id = request.form.get('delegate_id', type=int)
    start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
    end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
    reason = request.form.get('reason', '')

    if delegator_id == delegate_id:
        flash('Le délégant et le délégué doivent être différents.', 'error')
        return redirect(url_for('admin_advanced.delegations'))

    if start_date > end_date:
        flash('La date de début doit être antérieure à la date de fin.', 'error')
        return redirect(url_for('admin_advanced.delegations'))

    delegation = ApprovalDelegation(
        company_id=current_user.company_id,
        delegator_id=delegator_id,
        delegate_id=delegate_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason
    )
    db.session.add(delegation)
    db.session.commit()

    flash('Délégation créée avec succès.', 'success')
    return redirect(url_for('admin_advanced.delegations'))


@bp.route('/delegations/<int:delegation_id>/delete', methods=['POST'])
@login_required
@hr_required
def delete_delegation(delegation_id):
    """Delete a delegation."""
    delegation = ApprovalDelegation.query.filter_by(
        id=delegation_id,
        company_id=current_user.company_id
    ).first_or_404()

    db.session.delete(delegation)
    db.session.commit()

    flash('Délégation supprimée.', 'success')
    return redirect(url_for('admin_advanced.delegations'))


# ============================================
# BLOCKED PERIODS
# ============================================

@bp.route('/blocked-periods')
@login_required
@hr_required
def blocked_periods():
    """List all blocked periods."""
    periods = BlockedPeriod.query.filter_by(
        company_id=current_user.company_id
    ).order_by(BlockedPeriod.start_date.desc()).all()

    teams = Team.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).order_by(Team.name).all()

    leave_types = LeaveType.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).all()

    return render_template('admin/blocked_periods.html',
        periods=periods,
        teams=teams,
        leave_types=leave_types
    )


@bp.route('/blocked-periods/create', methods=['POST'])
@login_required
@hr_required
def create_blocked_period():
    """Create a new blocked period."""
    name = request.form.get('name', '').strip()
    start_date = datetime.strptime(request.form.get('start_date'), '%Y-%m-%d').date()
    end_date = datetime.strptime(request.form.get('end_date'), '%Y-%m-%d').date()
    block_type = request.form.get('block_type', 'soft')
    reason = request.form.get('reason', '')

    # Get selected teams and leave types
    team_ids = request.form.getlist('team_ids')
    leave_type_ids = request.form.getlist('leave_type_ids')

    period = BlockedPeriod(
        company_id=current_user.company_id,
        name=name,
        start_date=start_date,
        end_date=end_date,
        block_type=block_type,
        reason=reason,
        team_ids=','.join(team_ids) if team_ids else '',
        leave_type_ids=','.join(leave_type_ids) if leave_type_ids else '',
        created_by_id=current_user.id
    )
    db.session.add(period)
    db.session.commit()

    flash(f'Période bloquée "{name}" créée.', 'success')
    return redirect(url_for('admin_advanced.blocked_periods'))


@bp.route('/blocked-periods/<int:period_id>/toggle', methods=['POST'])
@login_required
@hr_required
def toggle_blocked_period(period_id):
    """Toggle a blocked period active status."""
    period = BlockedPeriod.query.filter_by(
        id=period_id,
        company_id=current_user.company_id
    ).first_or_404()

    period.is_active = not period.is_active
    db.session.commit()

    status = 'activée' if period.is_active else 'désactivée'
    flash(f'Période "{period.name}" {status}.', 'success')
    return redirect(url_for('admin_advanced.blocked_periods'))


@bp.route('/blocked-periods/<int:period_id>/delete', methods=['POST'])
@login_required
@hr_required
def delete_blocked_period(period_id):
    """Delete a blocked period."""
    period = BlockedPeriod.query.filter_by(
        id=period_id,
        company_id=current_user.company_id
    ).first_or_404()

    db.session.delete(period)
    db.session.commit()

    flash('Période bloquée supprimée.', 'success')
    return redirect(url_for('admin_advanced.blocked_periods'))


# ============================================
# ANNOUNCEMENTS
# ============================================

@bp.route('/announcements')
@login_required
@hr_required
def announcements():
    """List all announcements."""
    all_announcements = Announcement.query.filter_by(
        company_id=current_user.company_id
    ).order_by(Announcement.is_pinned.desc(), Announcement.created_at.desc()).all()

    teams = Team.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).order_by(Team.name).all()

    return render_template('admin/announcements.html',
        announcements=all_announcements,
        teams=teams,
        announcement_types=Announcement.TYPE_LABELS
    )


@bp.route('/announcements/create', methods=['POST'])
@login_required
@hr_required
def create_announcement():
    """Create a new announcement."""
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    announcement_type = request.form.get('announcement_type', 'info')
    is_pinned = request.form.get('is_pinned') == 'on'

    # Parse dates
    publish_at = request.form.get('publish_at')
    expires_at = request.form.get('expires_at')

    # Get selected teams
    team_ids = request.form.getlist('team_ids')

    announcement = Announcement(
        company_id=current_user.company_id,
        title=title,
        content=content,
        announcement_type=announcement_type,
        is_pinned=is_pinned,
        author_id=current_user.id,
        team_ids=','.join(team_ids) if team_ids else ''
    )

    if publish_at:
        announcement.publish_at = datetime.strptime(publish_at, '%Y-%m-%dT%H:%M')
    if expires_at:
        announcement.expires_at = datetime.strptime(expires_at, '%Y-%m-%dT%H:%M')

    db.session.add(announcement)
    db.session.commit()

    flash(f'Annonce "{title}" créée.', 'success')
    return redirect(url_for('admin_advanced.announcements'))


@bp.route('/announcements/<int:announcement_id>/edit', methods=['GET', 'POST'])
@login_required
@hr_required
def edit_announcement(announcement_id):
    """Edit an announcement."""
    announcement = Announcement.query.filter_by(
        id=announcement_id,
        company_id=current_user.company_id
    ).first_or_404()

    teams = Team.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).order_by(Team.name).all()

    if request.method == 'POST':
        announcement.title = request.form.get('title', '').strip()
        announcement.content = request.form.get('content', '').strip()
        announcement.announcement_type = request.form.get('announcement_type', 'info')
        announcement.is_pinned = request.form.get('is_pinned') == 'on'
        announcement.is_active = request.form.get('is_active') == 'on'

        publish_at = request.form.get('publish_at')
        expires_at = request.form.get('expires_at')
        team_ids = request.form.getlist('team_ids')

        announcement.team_ids = ','.join(team_ids) if team_ids else ''

        if publish_at:
            announcement.publish_at = datetime.strptime(publish_at, '%Y-%m-%dT%H:%M')
        if expires_at:
            announcement.expires_at = datetime.strptime(expires_at, '%Y-%m-%dT%H:%M')
        else:
            announcement.expires_at = None

        db.session.commit()
        flash('Annonce mise à jour.', 'success')
        return redirect(url_for('admin_advanced.announcements'))

    return render_template('admin/edit_announcement.html',
        announcement=announcement,
        teams=teams,
        announcement_types=Announcement.TYPE_LABELS
    )


@bp.route('/announcements/<int:announcement_id>/delete', methods=['POST'])
@login_required
@hr_required
def delete_announcement(announcement_id):
    """Delete an announcement."""
    announcement = Announcement.query.filter_by(
        id=announcement_id,
        company_id=current_user.company_id
    ).first_or_404()

    db.session.delete(announcement)
    db.session.commit()

    flash('Annonce supprimée.', 'success')
    return redirect(url_for('admin_advanced.announcements'))


# ============================================
# AUTO-APPROVAL RULES
# ============================================

@bp.route('/auto-approval')
@login_required
@hr_required
def auto_approval_rules():
    """List all auto-approval rules."""
    rules = AutoApprovalRule.query.filter_by(
        company_id=current_user.company_id
    ).order_by(AutoApprovalRule.priority.desc()).all()

    leave_types = LeaveType.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).all()

    teams = Team.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).order_by(Team.name).all()

    roles = Role.query.all()

    return render_template('admin/auto_approval.html',
        rules=rules,
        leave_types=leave_types,
        teams=teams,
        roles=roles
    )


@bp.route('/auto-approval/create', methods=['POST'])
@login_required
@hr_required
def create_auto_approval_rule():
    """Create a new auto-approval rule."""
    name = request.form.get('name', '').strip()
    leave_type_id = request.form.get('leave_type_id', type=int) or None
    max_days = request.form.get('max_days', type=float) or None
    min_advance_days = request.form.get('min_advance_days', 0, type=int)
    priority = request.form.get('priority', 0, type=int)

    team_ids = request.form.getlist('team_ids')
    role_ids = request.form.getlist('role_ids')

    rule = AutoApprovalRule(
        company_id=current_user.company_id,
        name=name,
        leave_type_id=leave_type_id,
        max_days=max_days,
        min_advance_days=min_advance_days,
        priority=priority,
        applies_to_teams=','.join(team_ids) if team_ids else '',
        applies_to_roles=','.join(role_ids) if role_ids else '',
        created_by_id=current_user.id
    )
    db.session.add(rule)
    db.session.commit()

    flash(f'Règle "{name}" créée.', 'success')
    return redirect(url_for('admin_advanced.auto_approval_rules'))


@bp.route('/auto-approval/<int:rule_id>/toggle', methods=['POST'])
@login_required
@hr_required
def toggle_auto_approval_rule(rule_id):
    """Toggle an auto-approval rule."""
    rule = AutoApprovalRule.query.filter_by(
        id=rule_id,
        company_id=current_user.company_id
    ).first_or_404()

    rule.is_active = not rule.is_active
    db.session.commit()

    status = 'activée' if rule.is_active else 'désactivée'
    flash(f'Règle "{rule.name}" {status}.', 'success')
    return redirect(url_for('admin_advanced.auto_approval_rules'))


@bp.route('/auto-approval/<int:rule_id>/delete', methods=['POST'])
@login_required
@hr_required
def delete_auto_approval_rule(rule_id):
    """Delete an auto-approval rule."""
    rule = AutoApprovalRule.query.filter_by(
        id=rule_id,
        company_id=current_user.company_id
    ).first_or_404()

    db.session.delete(rule)
    db.session.commit()

    flash('Règle supprimée.', 'success')
    return redirect(url_for('admin_advanced.auto_approval_rules'))


# ============================================
# SITES & HOLIDAYS
# ============================================

@bp.route('/sites')
@login_required
@admin_required
def sites():
    """List all company sites."""
    all_sites = Site.query.filter_by(
        company_id=current_user.company_id
    ).order_by(Site.is_main.desc(), Site.name).all()

    return render_template('admin/sites.html', sites=all_sites)


@bp.route('/sites/create', methods=['POST'])
@login_required
@admin_required
def create_site():
    """Create a new site."""
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').upper().strip()
    address = request.form.get('address', '')
    country = request.form.get('country', 'FR')
    is_main = request.form.get('is_main') == 'on'

    # If this is the main site, unset others
    if is_main:
        Site.query.filter_by(company_id=current_user.company_id, is_main=True).update({'is_main': False})

    site = Site(
        company_id=current_user.company_id,
        name=name,
        code=code,
        address=address,
        country=country,
        is_main=is_main
    )
    db.session.add(site)
    db.session.commit()

    # Create default holidays
    current_year = date.today().year
    create_default_holidays_for_site(site, current_year)
    create_default_holidays_for_site(site, current_year + 1)

    flash(f'Site "{name}" créé avec les jours fériés par défaut.', 'success')
    return redirect(url_for('admin_advanced.sites'))


@bp.route('/sites/<int:site_id>')
@login_required
@admin_required
def view_site(site_id):
    """View site details and holidays."""
    site = Site.query.filter_by(
        id=site_id,
        company_id=current_user.company_id
    ).first_or_404()

    year = request.args.get('year', date.today().year, type=int)
    holidays = site.get_holidays_for_year(year)

    # Get users assigned to this site
    users = User.query.filter_by(
        company_id=current_user.company_id,
        site_id=site_id,
        is_active=True
    ).order_by(User.last_name).all()

    return render_template('admin/view_site.html',
        site=site,
        holidays=holidays,
        users=users,
        year=year
    )


@bp.route('/sites/<int:site_id>/holidays/add', methods=['POST'])
@login_required
@admin_required
def add_site_holiday(site_id):
    """Add a holiday to a site."""
    site = Site.query.filter_by(
        id=site_id,
        company_id=current_user.company_id
    ).first_or_404()

    holiday_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
    name = request.form.get('name', '').strip()
    is_recurring = request.form.get('is_recurring') == 'on'

    # Check if already exists
    existing = SiteHoliday.query.filter_by(site_id=site_id, date=holiday_date).first()
    if existing:
        flash('Un jour férié existe déjà à cette date.', 'error')
        return redirect(url_for('admin_advanced.view_site', site_id=site_id))

    holiday = SiteHoliday(
        site_id=site_id,
        date=holiday_date,
        name=name,
        is_recurring=is_recurring
    )
    db.session.add(holiday)
    db.session.commit()

    flash(f'Jour férié "{name}" ajouté.', 'success')
    return redirect(url_for('admin_advanced.view_site', site_id=site_id, year=holiday_date.year))


@bp.route('/sites/<int:site_id>/holidays/<int:holiday_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_site_holiday(site_id, holiday_id):
    """Delete a site holiday."""
    holiday = SiteHoliday.query.filter_by(id=holiday_id, site_id=site_id).first_or_404()

    # Verify site belongs to company
    site = Site.query.filter_by(id=site_id, company_id=current_user.company_id).first_or_404()

    db.session.delete(holiday)
    db.session.commit()

    flash('Jour férié supprimé.', 'success')
    return redirect(url_for('admin_advanced.view_site', site_id=site_id))


# ============================================
# ANALYTICS & REPORTS
# ============================================

@bp.route('/analytics')
@login_required
@hr_required
def analytics():
    """Analytics dashboard."""
    company_id = current_user.company_id
    today = date.today()
    year = request.args.get('year', today.year, type=int)

    # Taux d'absentéisme par mois
    absenteeism_by_month = []
    for month in range(1, 13):
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)

        # Count approved leave days in this month
        leaves = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
            User.company_id == company_id,
            LeaveRequest.status == 'approved',
            LeaveRequest.start_date <= month_end,
            LeaveRequest.end_date >= month_start
        ).all()

        total_days = sum(l.days_count for l in leaves)
        absenteeism_by_month.append({
            'month': month_start.strftime('%b'),
            'days': total_days
        })

    # Absences par type de congé
    leave_by_type = db.session.query(
        LeaveType.name,
        LeaveType.color,
        db.func.sum(LeaveRequest.days_count)
    ).join(LeaveRequest).join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.status == 'approved',
        db.extract('year', LeaveRequest.start_date) == year
    ).group_by(LeaveType.id).all()

    # Absences par équipe
    leave_by_team = db.session.query(
        Team.name,
        db.func.sum(LeaveRequest.days_count)
    ).join(User, Team.id == User.team_id).join(
        LeaveRequest, LeaveRequest.employee_id == User.id
    ).filter(
        User.company_id == company_id,
        LeaveRequest.status == 'approved',
        db.extract('year', LeaveRequest.start_date) == year
    ).group_by(Team.id).all()

    # Top 5 employés avec le plus de jours posés
    top_employees = db.session.query(
        User.first_name,
        User.last_name,
        db.func.sum(LeaveRequest.days_count).label('total_days')
    ).join(LeaveRequest, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.status == 'approved',
        db.extract('year', LeaveRequest.start_date) == year
    ).group_by(User.id).order_by(db.desc('total_days')).limit(5).all()

    # Stats globales
    total_employees = User.query.filter_by(company_id=company_id, is_active=True).count()
    total_requests = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        db.extract('year', LeaveRequest.created_at) == year
    ).count()
    approved_requests = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.status == 'approved',
        db.extract('year', LeaveRequest.created_at) == year
    ).count()
    rejected_requests = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.status == 'rejected',
        db.extract('year', LeaveRequest.created_at) == year
    ).count()

    approval_rate = round((approved_requests / total_requests * 100), 1) if total_requests > 0 else 0

    return render_template('admin/analytics.html',
        year=year,
        absenteeism_by_month=absenteeism_by_month,
        leave_by_type=leave_by_type,
        leave_by_team=leave_by_team,
        top_employees=top_employees,
        total_employees=total_employees,
        total_requests=total_requests,
        approved_requests=approved_requests,
        rejected_requests=rejected_requests,
        approval_rate=approval_rate
    )


@bp.route('/exports')
@login_required
@hr_required
def exports():
    """Export page."""
    teams = Team.query.filter_by(company_id=current_user.company_id, is_active=True).all()
    leave_types = LeaveType.query.filter_by(company_id=current_user.company_id, is_active=True).all()

    return render_template('admin/exports.html', teams=teams, leave_types=leave_types, now=datetime.now())


@bp.route('/exports/leaves.csv')
@login_required
@hr_required
def export_leaves_csv():
    """Export leave requests as CSV."""
    import csv
    import io

    year = request.args.get('year', date.today().year, type=int)
    team_id = request.args.get('team_id', type=int)
    leave_type_id = request.args.get('leave_type_id', type=int)

    query = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == current_user.company_id,
        db.extract('year', LeaveRequest.start_date) == year
    )

    if team_id:
        query = query.filter(User.team_id == team_id)
    if leave_type_id:
        query = query.filter(LeaveRequest.leave_type_id == leave_type_id)

    leaves = query.order_by(LeaveRequest.start_date).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # Header
    writer.writerow([
        'Employé', 'Email', 'Équipe', 'Type de congé',
        'Date début', 'Date fin', 'Jours', 'Statut', 'Créée le'
    ])

    for leave in leaves:
        writer.writerow([
            leave.employee.full_name,
            leave.employee.email,
            leave.employee.team.name if leave.employee.team else '',
            leave.leave_type.name if leave.leave_type else '',
            leave.start_date.strftime('%d/%m/%Y'),
            leave.end_date.strftime('%d/%m/%Y'),
            leave.days_count,
            leave.status_label,
            leave.created_at.strftime('%d/%m/%Y %H:%M')
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=conges_{year}.csv'}
    )


@bp.route('/exports/balances.csv')
@login_required
@hr_required
def export_balances_csv():
    """Export leave balances as CSV."""
    import csv
    import io

    year = request.args.get('year', date.today().year, type=int)

    users = User.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).order_by(User.last_name).all()

    leave_types = LeaveType.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # Header
    header = ['Employé', 'Email', 'Équipe']
    for lt in leave_types:
        header.extend([f'{lt.code} Initial', f'{lt.code} Utilisé', f'{lt.code} Restant'])
    writer.writerow(header)

    for user in users:
        row = [user.full_name, user.email, user.team.name if user.team else '']

        for lt in leave_types:
            balance = LeaveBalance.query.filter_by(
                user_id=user.id,
                leave_type_id=lt.id,
                year=year
            ).first()

            if balance:
                initial = balance.initial_balance + (balance.carried_over or 0) + balance.adjusted
                used = balance.used
                remaining = initial - used
                row.extend([f'{initial:.1f}', f'{used:.1f}', f'{remaining:.1f}'])
            else:
                row.extend(['0', '0', '0'])

        writer.writerow(row)

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=soldes_{year}.csv'}
    )


@bp.route('/exports/payroll.csv')
@login_required
@hr_required
def export_payroll_csv():
    """Export payroll-formatted CSV (for Silae, PayFit, etc.)."""
    import csv
    import io

    month = request.args.get('month', date.today().month, type=int)
    year = request.args.get('year', date.today().year, type=int)

    month_start = date(year, month, 1)
    if month == 12:
        month_end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        month_end = date(year, month + 1, 1) - timedelta(days=1)

    # Get approved leaves for this month
    leaves = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == current_user.company_id,
        LeaveRequest.status == 'approved',
        LeaveRequest.start_date <= month_end,
        LeaveRequest.end_date >= month_start
    ).order_by(User.last_name, LeaveRequest.start_date).all()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')

    # Payroll format header
    writer.writerow([
        'Matricule', 'Nom', 'Prénom', 'Code absence',
        'Date début', 'Date fin', 'Nombre de jours', 'Commentaire'
    ])

    for leave in leaves:
        writer.writerow([
            leave.employee.employee_id or '',
            leave.employee.last_name,
            leave.employee.first_name,
            leave.leave_type.code if leave.leave_type else '',
            leave.start_date.strftime('%d/%m/%Y'),
            leave.end_date.strftime('%d/%m/%Y'),
            f'{leave.days_count:.2f}'.replace('.', ','),
            leave.reason or ''
        ])

    output.seek(0)
    month_name = month_start.strftime('%Y-%m')
    return Response(
        output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=paie_{month_name}.csv'}
    )


# ============================================
# ORGCHART
# ============================================

@bp.route('/orgchart')
@login_required
@hr_required
def orgchart():
    """Visual organization chart."""
    users = User.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).all()

    teams = Team.query.filter_by(
        company_id=current_user.company_id,
        is_active=True
    ).all()

    # Build hierarchy
    def build_tree(manager_id=None):
        children = []
        for user in users:
            if user.manager_id == manager_id:
                children.append({
                    'id': user.id,
                    'name': user.full_name,
                    'role': user.role.description if user.role else '',
                    'team': user.team.name if user.team else '',
                    'avatar': user.initials,
                    'children': build_tree(user.id)
                })
        return children

    # Find root users (no manager or manager not in company)
    company_user_ids = {u.id for u in users}
    roots = []
    for user in users:
        if user.manager_id is None or user.manager_id not in company_user_ids:
            roots.append({
                'id': user.id,
                'name': user.full_name,
                'role': user.role.description if user.role else '',
                'team': user.team.name if user.team else '',
                'avatar': user.initials,
                'children': build_tree(user.id)
            })

    return render_template('admin/orgchart.html', roots=roots, teams=teams)
