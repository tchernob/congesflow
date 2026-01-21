"""
Root (Superadmin) routes for SaaS platform management.
These routes are only accessible to users with is_superadmin=True.
"""
from functools import wraps
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, Response
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy import func, desc
from app import db
from app.models.user import User, Role
from app.models.company import Company
from app.models.leave import LeaveRequest
from app.models.coupon import Coupon, CouponUsage
from app.models.company_note import CompanyNote
from app.models.activity_log import ActivityLog
from app.models.leave import LeaveBalance, LeaveType

bp = Blueprint('root', __name__, url_prefix='/root')


def superadmin_required(f):
    """Decorator to require superadmin access."""
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if not current_user.is_superadmin:
            flash('Accès réservé aux super-administrateurs.', 'error')
            return redirect(url_for('main.dashboard'))
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/')
@superadmin_required
def dashboard():
    """Root dashboard with global platform stats."""
    # Company stats
    total_companies = Company.query.count()
    active_companies = Company.query.filter_by(is_active=True).count()
    companies_by_plan = db.session.query(
        Company.plan, func.count(Company.id)
    ).group_by(Company.plan).all()
    companies_by_plan = {plan: count for plan, count in companies_by_plan}

    # User stats
    total_users = User.query.filter(User.is_superadmin == False).count()
    active_users = User.query.filter(
        User.is_superadmin == False,
        User.is_active == True
    ).count()

    # Recent activity
    recent_companies = Company.query.order_by(desc(Company.created_at)).limit(5).all()

    # MRR calculation
    mrr = 0
    paying_companies = 0
    for company in Company.query.filter(Company.plan != 'free', Company.is_active == True).all():
        price = Company.PLAN_PRICES.get(company.plan, {}).get('monthly', 0)
        if price:
            mrr += price
            paying_companies += 1

    # ARR (Annual Recurring Revenue)
    arr = mrr * 12

    # Companies near limit (80%+ usage)
    companies_near_limit = []
    for company in Company.query.filter_by(is_active=True).all():
        if company.usage_percent >= 80:
            companies_near_limit.append(company)

    # Leave requests stats (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_requests = LeaveRequest.query.filter(
        LeaveRequest.created_at >= thirty_days_ago
    ).count()

    # Trial stats
    trials_active = Company.query.filter(
        Company.is_active == True,
        Company.trial_ends_at != None,
        Company.trial_ends_at > datetime.utcnow()
    ).count()

    # Conversion rate (trial -> paid)
    total_past_trials = Company.query.filter(
        (Company.trial_ends_at != None) & (Company.trial_ends_at <= datetime.utcnow())
    ).count()
    converted_trials = Company.query.filter(
        Company.trial_ends_at != None,
        Company.trial_ends_at <= datetime.utcnow(),
        Company.plan != 'free'
    ).count()
    conversion_rate = round((converted_trials / total_past_trials * 100), 1) if total_past_trials > 0 else 0

    # Inscriptions par mois (12 derniers mois)
    signups_by_month = []
    for i in range(11, -1, -1):
        month_start = (datetime.utcnow().replace(day=1) - timedelta(days=i*30)).replace(day=1)
        if i > 0:
            month_end = (month_start + timedelta(days=32)).replace(day=1)
        else:
            month_end = datetime.utcnow()
        count = Company.query.filter(
            Company.created_at >= month_start,
            Company.created_at < month_end
        ).count()
        signups_by_month.append({
            'month': month_start.strftime('%b'),
            'count': count
        })

    # MRR évolution (6 derniers mois) - simplifié
    # Note: pour un vrai calcul, il faudrait stocker l'historique des plans
    mrr_history = []
    for i in range(5, -1, -1):
        month_start = (datetime.utcnow().replace(day=1) - timedelta(days=i*30)).replace(day=1)
        mrr_history.append({
            'month': month_start.strftime('%b'),
            'mrr': mrr  # Simplifié - même valeur pour tous les mois
        })

    # Entreprises en période d'essai qui expirent bientôt (7 jours)
    expiring_trials = Company.query.filter(
        Company.is_active == True,
        Company.trial_ends_at != None,
        Company.trial_ends_at > datetime.utcnow(),
        Company.trial_ends_at <= datetime.utcnow() + timedelta(days=7)
    ).order_by(Company.trial_ends_at).all()

    # Paiements échoués (placeholder - nécessite intégration Stripe webhooks)
    failed_payments = []

    return render_template('root/dashboard.html',
        total_companies=total_companies,
        active_companies=active_companies,
        companies_by_plan=companies_by_plan,
        total_users=total_users,
        active_users=active_users,
        recent_companies=recent_companies,
        mrr=mrr,
        arr=arr,
        paying_companies=paying_companies,
        companies_near_limit=companies_near_limit,
        recent_requests=recent_requests,
        trials_active=trials_active,
        conversion_rate=conversion_rate,
        signups_by_month=signups_by_month,
        mrr_history=mrr_history,
        expiring_trials=expiring_trials,
        failed_payments=failed_payments
    )


@bp.route('/companies')
@superadmin_required
def companies():
    """List all companies with filters."""
    # Filters
    plan_filter = request.args.get('plan', '')
    search = request.args.get('search', '')
    status = request.args.get('status', '')
    sort = request.args.get('sort', 'created_at')
    order = request.args.get('order', 'desc')

    query = Company.query

    if plan_filter:
        query = query.filter(Company.plan == plan_filter)

    if search:
        query = query.filter(Company.name.ilike(f'%{search}%'))

    if status == 'active':
        query = query.filter(Company.is_active == True)
    elif status == 'inactive':
        query = query.filter(Company.is_active == False)

    # Sorting
    if sort == 'name':
        sort_col = Company.name
    elif sort == 'users':
        sort_col = Company.employee_count
    elif sort == 'plan':
        sort_col = Company.plan
    else:
        sort_col = Company.created_at

    if order == 'asc':
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    companies = query.all()

    return render_template('root/companies.html',
        companies=companies,
        plan_filter=plan_filter,
        search=search,
        status=status,
        sort=sort,
        order=order,
        plans=Company.PLAN_LABELS
    )


@bp.route('/companies/<int:company_id>')
@superadmin_required
def view_company(company_id):
    """View company details."""
    company = Company.query.get_or_404(company_id)

    # Get company users
    users = User.query.filter_by(company_id=company_id).order_by(User.created_at.desc()).all()

    # Get admin users
    admin_role = Role.query.filter_by(name=Role.ADMIN).first()
    admins = User.query.filter_by(company_id=company_id, role_id=admin_role.id).all() if admin_role else []

    # Leave stats
    total_requests = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(User.company_id == company_id).count()
    pending_requests = LeaveRequest.query.join(User, LeaveRequest.employee_id == User.id).filter(
        User.company_id == company_id,
        LeaveRequest.status.in_(['pending_manager', 'pending_hr'])
    ).count()

    # Company notes
    notes = company.notes.order_by(CompanyNote.is_pinned.desc(), CompanyNote.created_at.desc()).all()

    return render_template('root/view_company.html',
        company=company,
        users=users,
        admins=admins,
        total_requests=total_requests,
        pending_requests=pending_requests,
        plans=Company.PLAN_LABELS,
        plan_limits=Company.PLAN_LIMITS,
        notes=notes,
        note_types=CompanyNote.TYPE_LABELS
    )


@bp.route('/companies/<int:company_id>/edit', methods=['GET', 'POST'])
@superadmin_required
def edit_company(company_id):
    """Edit company details and subscription."""
    company = Company.query.get_or_404(company_id)

    if request.method == 'POST':
        # Update basic info
        company.name = request.form.get('name', company.name)

        # Update plan
        new_plan = request.form.get('plan')
        if new_plan and new_plan in Company.PLAN_LABELS:
            old_plan = company.plan
            company.plan = new_plan
            company.max_employees = Company.PLAN_LIMITS.get(new_plan, 5)

            if old_plan != new_plan:
                flash(f'Plan changé de {Company.PLAN_LABELS[old_plan]} à {Company.PLAN_LABELS[new_plan]}.', 'success')

        # Update subscription dates
        subscription_ends = request.form.get('subscription_ends_at')
        if subscription_ends:
            try:
                company.subscription_ends_at = datetime.strptime(subscription_ends, '%Y-%m-%d')
            except ValueError:
                pass

        # Custom max employees override
        max_employees_override = request.form.get('max_employees_override')
        if max_employees_override:
            try:
                company.max_employees = int(max_employees_override)
            except ValueError:
                pass

        # Active status
        company.is_active = request.form.get('is_active') == 'on'

        # Internal company (no billing, all features)
        was_internal = company.is_internal
        company.is_internal = request.form.get('is_internal') == 'on'

        # If marked as internal, auto-set enterprise plan
        if company.is_internal and not was_internal:
            company.plan = Company.PLAN_ENTERPRISE
            company.max_employees = 9999
            flash('Entreprise marquée comme interne avec plan Enterprise illimité.', 'info')

        db.session.commit()
        flash('Entreprise mise à jour avec succès.', 'success')
        return redirect(url_for('root.view_company', company_id=company_id))

    return render_template('root/edit_company.html',
        company=company,
        plans=Company.PLAN_LABELS,
        plan_limits=Company.PLAN_LIMITS
    )


@bp.route('/companies/<int:company_id>/toggle', methods=['POST'])
@superadmin_required
def toggle_company(company_id):
    """Activate or deactivate a company."""
    company = Company.query.get_or_404(company_id)
    company.is_active = not company.is_active
    db.session.commit()

    status = 'activée' if company.is_active else 'désactivée'
    flash(f'Entreprise {company.name} {status}.', 'success')
    return redirect(url_for('root.view_company', company_id=company_id))


@bp.route('/impersonate/<int:company_id>')
@superadmin_required
def impersonate(company_id):
    """Login as the admin of a company."""
    company = Company.query.get_or_404(company_id)

    # Find company admin
    admin_role = Role.query.filter_by(name=Role.ADMIN).first()
    admin_user = User.query.filter_by(
        company_id=company_id,
        role_id=admin_role.id,
        is_active=True
    ).first()

    if not admin_user:
        flash('Aucun administrateur actif trouvé pour cette entreprise.', 'error')
        return redirect(url_for('root.view_company', company_id=company_id))

    # Store original user id to allow returning
    session['impersonating_from'] = current_user.id
    session['impersonating_company'] = company.name

    # Login as admin
    logout_user()
    login_user(admin_user)

    flash(f'Vous êtes maintenant connecté comme {admin_user.full_name} ({company.name}). '
          f'Cliquez sur "Retour Root" pour revenir.', 'info')
    return redirect(url_for('admin.dashboard'))


@bp.route('/stop-impersonation')
@login_required
def stop_impersonation():
    """Return to superadmin account after impersonation."""
    original_user_id = session.pop('impersonating_from', None)
    session.pop('impersonating_company', None)

    if not original_user_id:
        flash('Pas de session d\'impersonation active.', 'error')
        return redirect(url_for('main.dashboard'))

    original_user = User.query.get(original_user_id)
    if not original_user or not original_user.is_superadmin:
        flash('Utilisateur original introuvable.', 'error')
        return redirect(url_for('main.dashboard'))

    logout_user()
    login_user(original_user)

    flash('Retour au compte super-administrateur.', 'success')
    return redirect(url_for('root.dashboard'))


@bp.route('/users')
@superadmin_required
def users():
    """Search users across all companies."""
    search = request.args.get('search', '')
    company_id = request.args.get('company_id', '')

    query = User.query.filter(User.is_superadmin == False)

    if search:
        query = query.filter(
            db.or_(
                User.email.ilike(f'%{search}%'),
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%')
            )
        )

    if company_id:
        query = query.filter(User.company_id == int(company_id))

    users = query.order_by(User.created_at.desc()).limit(100).all()
    companies = Company.query.order_by(Company.name).all()

    return render_template('root/users.html',
        users=users,
        companies=companies,
        search=search,
        company_id=company_id
    )


@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@superadmin_required
def reset_user_password(user_id):
    """Generate a new invitation token for a user to reset their password."""
    user = User.query.get_or_404(user_id)

    if user.is_superadmin:
        flash('Impossible de réinitialiser le mot de passe d\'un super-admin.', 'error')
        return redirect(url_for('root.users'))

    user.generate_invitation_token()
    db.session.commit()

    # TODO: Send email with reset link
    reset_url = url_for('auth.setup_password', token=user.invitation_token, _external=True)

    flash(f'Token de réinitialisation généré. Lien: {reset_url}', 'success')
    return redirect(url_for('root.users', search=user.email))


# ============================================
# COUPONS MANAGEMENT
# ============================================

@bp.route('/coupons')
@superadmin_required
def coupons():
    """List all coupons."""
    status_filter = request.args.get('status', '')

    query = Coupon.query.order_by(desc(Coupon.created_at))

    if status_filter == 'active':
        query = query.filter(Coupon.is_active == True)
    elif status_filter == 'inactive':
        query = query.filter(Coupon.is_active == False)

    coupons_list = query.all()

    # Stats
    total_coupons = Coupon.query.count()
    active_coupons = Coupon.query.filter_by(is_active=True).count()
    total_uses = db.session.query(func.sum(Coupon.uses_count)).scalar() or 0

    return render_template('root/coupons.html',
        coupons=coupons_list,
        status_filter=status_filter,
        total_coupons=total_coupons,
        active_coupons=active_coupons,
        total_uses=total_uses,
        plans=Company.PLAN_LABELS
    )


@bp.route('/coupons/create', methods=['GET', 'POST'])
@superadmin_required
def create_coupon():
    """Create a new coupon."""
    if request.method == 'POST':
        code = request.form.get('code', '').strip().upper()
        if not code:
            code = Coupon.generate_code()

        # Check if code already exists
        if Coupon.query.filter_by(code=code).first():
            flash('Ce code existe déjà.', 'error')
            return redirect(url_for('root.create_coupon'))

        coupon = Coupon(
            code=code,
            description=request.form.get('description', ''),
            discount_type=request.form.get('discount_type', 'percent'),
            discount_value=float(request.form.get('discount_value', 0)),
            max_uses=int(request.form.get('max_uses')) if request.form.get('max_uses') else None,
            valid_plans=request.form.get('valid_plans', ''),
            duration_months=int(request.form.get('duration_months')) if request.form.get('duration_months') else None,
            created_by_id=current_user.id
        )

        # Date de validité
        valid_from = request.form.get('valid_from')
        if valid_from:
            try:
                coupon.valid_from = datetime.strptime(valid_from, '%Y-%m-%d')
            except ValueError:
                pass

        valid_until = request.form.get('valid_until')
        if valid_until:
            try:
                coupon.valid_until = datetime.strptime(valid_until, '%Y-%m-%d')
            except ValueError:
                pass

        db.session.add(coupon)
        db.session.commit()

        flash(f'Coupon {code} créé avec succès.', 'success')
        return redirect(url_for('root.coupons'))

    return render_template('root/create_coupon.html',
        plans=Company.PLAN_LABELS
    )


@bp.route('/coupons/<int:coupon_id>')
@superadmin_required
def view_coupon(coupon_id):
    """View coupon details and usage history."""
    coupon = Coupon.query.get_or_404(coupon_id)
    usages = CouponUsage.query.filter_by(coupon_id=coupon_id).order_by(desc(CouponUsage.used_at)).all()

    return render_template('root/view_coupon.html',
        coupon=coupon,
        usages=usages,
        plans=Company.PLAN_LABELS
    )


@bp.route('/coupons/<int:coupon_id>/edit', methods=['GET', 'POST'])
@superadmin_required
def edit_coupon(coupon_id):
    """Edit a coupon."""
    coupon = Coupon.query.get_or_404(coupon_id)

    if request.method == 'POST':
        coupon.description = request.form.get('description', '')
        coupon.discount_type = request.form.get('discount_type', 'percent')
        coupon.discount_value = float(request.form.get('discount_value', 0))
        coupon.max_uses = int(request.form.get('max_uses')) if request.form.get('max_uses') else None
        coupon.valid_plans = request.form.get('valid_plans', '')
        coupon.duration_months = int(request.form.get('duration_months')) if request.form.get('duration_months') else None
        coupon.is_active = request.form.get('is_active') == 'on'

        valid_until = request.form.get('valid_until')
        if valid_until:
            try:
                coupon.valid_until = datetime.strptime(valid_until, '%Y-%m-%d')
            except ValueError:
                pass
        else:
            coupon.valid_until = None

        db.session.commit()
        flash('Coupon mis à jour avec succès.', 'success')
        return redirect(url_for('root.view_coupon', coupon_id=coupon_id))

    return render_template('root/edit_coupon.html',
        coupon=coupon,
        plans=Company.PLAN_LABELS
    )


@bp.route('/coupons/<int:coupon_id>/toggle', methods=['POST'])
@superadmin_required
def toggle_coupon(coupon_id):
    """Activate or deactivate a coupon."""
    coupon = Coupon.query.get_or_404(coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()

    status = 'activé' if coupon.is_active else 'désactivé'
    flash(f'Coupon {coupon.code} {status}.', 'success')
    return redirect(url_for('root.coupons'))


# ============================================
# COMPANY NOTES
# ============================================

@bp.route('/companies/<int:company_id>/notes', methods=['POST'])
@superadmin_required
def add_company_note(company_id):
    """Add a note to a company."""
    company = Company.query.get_or_404(company_id)

    content = request.form.get('content', '').strip()
    if not content:
        flash('Le contenu de la note est requis.', 'error')
        return redirect(url_for('root.view_company', company_id=company_id))

    note = CompanyNote(
        company_id=company_id,
        author_id=current_user.id,
        content=content,
        note_type=request.form.get('note_type', 'general')
    )

    db.session.add(note)
    db.session.commit()

    flash('Note ajoutée.', 'success')
    return redirect(url_for('root.view_company', company_id=company_id))


@bp.route('/notes/<int:note_id>/delete', methods=['POST'])
@superadmin_required
def delete_company_note(note_id):
    """Delete a company note."""
    note = CompanyNote.query.get_or_404(note_id)
    company_id = note.company_id

    db.session.delete(note)
    db.session.commit()

    flash('Note supprimée.', 'success')
    return redirect(url_for('root.view_company', company_id=company_id))


@bp.route('/notes/<int:note_id>/pin', methods=['POST'])
@superadmin_required
def toggle_note_pin(note_id):
    """Pin or unpin a note."""
    note = CompanyNote.query.get_or_404(note_id)
    note.is_pinned = not note.is_pinned
    db.session.commit()

    return redirect(url_for('root.view_company', company_id=note.company_id))


# ============================================
# ACTIVITY LOGS
# ============================================

@bp.route('/activity')
@superadmin_required
def activity_logs():
    """View platform activity logs."""
    # Filters
    category_filter = request.args.get('category', '')
    action_filter = request.args.get('action', '')
    company_filter = request.args.get('company_id', '')
    page = request.args.get('page', 1, type=int)
    per_page = 50

    query = ActivityLog.query.order_by(desc(ActivityLog.created_at))

    if category_filter:
        query = query.filter(ActivityLog.category == category_filter)

    if action_filter:
        query = query.filter(ActivityLog.action == action_filter)

    if company_filter:
        query = query.filter(ActivityLog.company_id == int(company_filter))

    # Pagination
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    logs = pagination.items

    # Get filter options
    companies = Company.query.order_by(Company.name).all()

    return render_template('root/activity_logs.html',
        logs=logs,
        pagination=pagination,
        category_filter=category_filter,
        action_filter=action_filter,
        company_filter=company_filter,
        companies=companies,
        categories=ActivityLog.CATEGORY_LABELS,
        actions=ActivityLog.ACTION_LABELS
    )


# ============================================
# TOOLS - CORRECTION & MAINTENANCE
# ============================================

@bp.route('/tools')
@superadmin_required
def tools():
    """Root tools and maintenance page."""
    companies = Company.query.order_by(Company.name).all()
    return render_template('root/tools.html', companies=companies)


@bp.route('/tools/recalculate-balances', methods=['POST'])
@superadmin_required
def recalculate_balances():
    """Recalculate leave balances for a company."""
    company_id = request.form.get('company_id')

    if not company_id:
        flash('Veuillez sélectionner une entreprise.', 'error')
        return redirect(url_for('root.tools'))

    company = Company.query.get_or_404(int(company_id))

    # Get all active users in the company
    users = User.query.filter_by(company_id=company.id, is_active=True).all()
    leave_types = LeaveType.query.filter_by(company_id=company.id).all()

    balances_updated = 0
    balances_created = 0

    for user in users:
        for lt in leave_types:
            balance = LeaveBalance.query.filter_by(
                employee_id=user.id,
                leave_type_id=lt.id
            ).first()

            if not balance:
                # Create missing balance
                balance = LeaveBalance(
                    employee_id=user.id,
                    leave_type_id=lt.id,
                    annual_allowance=lt.default_days,
                    used_days=0,
                    pending_days=0,
                    year=datetime.utcnow().year
                )
                db.session.add(balance)
                balances_created += 1
            else:
                # Recalculate used and pending days from leave requests
                from app.models.leave import LeaveRequest

                # Used days (approved requests)
                used_requests = LeaveRequest.query.filter(
                    LeaveRequest.employee_id == user.id,
                    LeaveRequest.leave_type_id == lt.id,
                    LeaveRequest.status == 'approved'
                ).all()
                used_days = sum(r.days_count for r in used_requests)

                # Pending days
                pending_requests = LeaveRequest.query.filter(
                    LeaveRequest.employee_id == user.id,
                    LeaveRequest.leave_type_id == lt.id,
                    LeaveRequest.status.in_(['pending_manager', 'pending_hr'])
                ).all()
                pending_days = sum(r.days_count for r in pending_requests)

                if balance.used_days != used_days or balance.pending_days != pending_days:
                    balance.used_days = used_days
                    balance.pending_days = pending_days
                    balances_updated += 1

    db.session.commit()

    flash(f'Soldes recalculés pour {company.name}: {balances_created} créés, {balances_updated} mis à jour.', 'success')
    return redirect(url_for('root.tools'))


@bp.route('/tools/reset-all-passwords', methods=['POST'])
@superadmin_required
def reset_all_passwords():
    """Generate reset tokens for all users of a company."""
    company_id = request.form.get('company_id')

    if not company_id:
        flash('Veuillez sélectionner une entreprise.', 'error')
        return redirect(url_for('root.tools'))

    company = Company.query.get_or_404(int(company_id))

    # Get all active users in the company
    users = User.query.filter_by(company_id=company.id, is_active=True).all()

    reset_count = 0
    for user in users:
        user.generate_invitation_token()
        reset_count += 1

    db.session.commit()

    flash(f'Tokens de réinitialisation générés pour {reset_count} utilisateur(s) de {company.name}.', 'success')
    return redirect(url_for('root.tools'))


@bp.route('/tools/sync-leave-types', methods=['POST'])
@superadmin_required
def sync_leave_types():
    """Sync default leave types to a company."""
    company_id = request.form.get('company_id')

    if not company_id:
        flash('Veuillez sélectionner une entreprise.', 'error')
        return redirect(url_for('root.tools'))

    company = Company.query.get_or_404(int(company_id))

    # Default leave types
    default_types = [
        {'code': 'CP', 'name': 'Congés payés', 'default_days': 25, 'color': '#10B981', 'requires_approval': True},
        {'code': 'RTT', 'name': 'RTT', 'default_days': 10, 'color': '#3B82F6', 'requires_approval': True},
        {'code': 'MAL', 'name': 'Maladie', 'default_days': 0, 'color': '#EF4444', 'requires_approval': True, 'requires_justification': True},
        {'code': 'EXA', 'name': 'Congés examens', 'default_days': 5, 'color': '#8B5CF6', 'requires_approval': True},
        {'code': 'FAM', 'name': 'Événements familiaux', 'default_days': 0, 'color': '#F59E0B', 'requires_approval': True},
        {'code': 'SSP', 'name': 'Sans solde', 'default_days': 0, 'color': '#6B7280', 'requires_approval': True},
    ]

    types_added = 0
    for lt_data in default_types:
        existing = LeaveType.query.filter_by(company_id=company.id, code=lt_data['code']).first()
        if not existing:
            lt = LeaveType(
                company_id=company.id,
                code=lt_data['code'],
                name=lt_data['name'],
                default_days=lt_data['default_days'],
                color=lt_data.get('color', '#6B7280'),
                requires_approval=lt_data.get('requires_approval', True),
                requires_justification=lt_data.get('requires_justification', False)
            )
            db.session.add(lt)
            types_added += 1

    db.session.commit()

    if types_added > 0:
        flash(f'{types_added} type(s) de congé ajouté(s) à {company.name}.', 'success')
    else:
        flash(f'Tous les types de congé existent déjà pour {company.name}.', 'info')

    return redirect(url_for('root.tools'))


@bp.route('/tools/extend-trial', methods=['POST'])
@superadmin_required
def extend_trial():
    """Extend trial period for a company."""
    company_id = request.form.get('company_id')
    days = request.form.get('days', 14, type=int)

    if not company_id:
        flash('Veuillez sélectionner une entreprise.', 'error')
        return redirect(url_for('root.tools'))

    company = Company.query.get_or_404(int(company_id))

    if company.trial_ends_at:
        # Extend from current end date
        company.trial_ends_at = company.trial_ends_at + timedelta(days=days)
    else:
        # Start new trial from now
        company.trial_ends_at = datetime.utcnow() + timedelta(days=days)

    db.session.commit()

    flash(f'Période d\'essai de {company.name} prolongée de {days} jours.', 'success')
    return redirect(url_for('root.tools'))


# ============================================
# EXPORTS
# ============================================

@bp.route('/exports')
@superadmin_required
def exports():
    """Export data page."""
    companies = Company.query.order_by(Company.name).all()
    return render_template('root/exports.html', companies=companies)


@bp.route('/exports/companies.csv')
@superadmin_required
def export_companies_csv():
    """Export all companies as CSV."""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'ID', 'Nom', 'Plan', 'Utilisateurs', 'Max utilisateurs',
        'Actif', 'Email', 'Stripe Customer ID', 'Créé le'
    ])

    # Data
    companies = Company.query.order_by(Company.created_at.desc()).all()
    for c in companies:
        writer.writerow([
            c.id, c.name, c.plan, c.employee_count, c.max_employees,
            'Oui' if c.is_active else 'Non', c.email,
            c.stripe_customer_id or '', c.created_at.strftime('%Y-%m-%d %H:%M')
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=companies_export.csv'}
    )


@bp.route('/exports/users.csv')
@superadmin_required
def export_users_csv():
    """Export all users as CSV."""
    import csv
    import io

    company_id = request.args.get('company_id')

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'ID', 'Prénom', 'Nom', 'Email', 'Entreprise', 'Rôle',
        'Actif', 'Créé le'
    ])

    # Data
    query = User.query.filter(User.is_superadmin == False).order_by(User.created_at.desc())
    if company_id:
        query = query.filter(User.company_id == int(company_id))

    users = query.all()
    for u in users:
        writer.writerow([
            u.id, u.first_name, u.last_name, u.email,
            u.company.name if u.company else '', u.role.name if u.role else '',
            'Oui' if u.is_active else 'Non', u.created_at.strftime('%Y-%m-%d %H:%M')
        ])

    output.seek(0)

    filename = 'users_export.csv'
    if company_id:
        company = Company.query.get(int(company_id))
        if company:
            filename = f'users_{company.slug}_export.csv'

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@bp.route('/exports/mrr.csv')
@superadmin_required
def export_mrr_csv():
    """Export MRR data as CSV."""
    import csv
    import io

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'Entreprise', 'Plan', 'Prix mensuel', 'Cycle de facturation',
        'Stripe Status', 'Utilisateurs actifs'
    ])

    # Only paying companies
    companies = Company.query.filter(
        Company.plan != 'free',
        Company.is_active == True
    ).order_by(Company.plan, Company.name).all()

    total_mrr = 0
    for c in companies:
        price = Company.PLAN_PRICES.get(c.plan, {}).get('monthly', 0) or 0
        total_mrr += price
        writer.writerow([
            c.name, c.plan_label, f'{price}€',
            c.billing_cycle or 'monthly',
            c.stripe_subscription_status or 'N/A',
            c.employee_count
        ])

    # Total row
    writer.writerow([])
    writer.writerow(['TOTAL MRR', '', f'{total_mrr}€', '', '', ''])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=mrr_export.csv'}
    )


@bp.route('/exports/activity.csv')
@superadmin_required
def export_activity_csv():
    """Export activity logs as CSV."""
    import csv
    import io

    days = request.args.get('days', 30, type=int)
    since = datetime.utcnow() - timedelta(days=days)

    output = io.StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'Date', 'Catégorie', 'Action', 'Utilisateur', 'Entreprise',
        'Description', 'IP'
    ])

    logs = ActivityLog.query.filter(
        ActivityLog.created_at >= since
    ).order_by(ActivityLog.created_at.desc()).all()

    for log in logs:
        writer.writerow([
            log.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            log.category_label, log.action_label,
            log.user.full_name if log.user else 'Système',
            log.company.name if log.company else '',
            log.description or '',
            log.ip_address or ''
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=activity_{days}days_export.csv'}
    )
