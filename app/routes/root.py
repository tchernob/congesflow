"""
Root (Superadmin) routes for SaaS platform management.
These routes are only accessible to users with is_superadmin=True.
"""
from functools import wraps
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, flash, request, session
from flask_login import login_required, current_user, login_user, logout_user
from sqlalchemy import func, desc
from app import db
from app.models.user import User, Role
from app.models.company import Company
from app.models.leave import LeaveRequest

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
    for company in Company.query.filter(Company.plan != 'free').all():
        price = Company.PLAN_PRICES.get(company.plan, {}).get('monthly', 0)
        if price:
            mrr += price

    # Companies near limit (80%+ usage)
    companies_near_limit = []
    for company in Company.query.all():
        if company.usage_percent >= 80:
            companies_near_limit.append(company)

    # Leave requests stats (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_requests = LeaveRequest.query.filter(
        LeaveRequest.created_at >= thirty_days_ago
    ).count()

    return render_template('root/dashboard.html',
        total_companies=total_companies,
        companies_by_plan=companies_by_plan,
        total_users=total_users,
        active_users=active_users,
        recent_companies=recent_companies,
        mrr=mrr,
        companies_near_limit=companies_near_limit,
        recent_requests=recent_requests
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

    return render_template('root/view_company.html',
        company=company,
        users=users,
        admins=admins,
        total_requests=total_requests,
        pending_requests=pending_requests,
        plans=Company.PLAN_LABELS,
        plan_limits=Company.PLAN_LIMITS
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
