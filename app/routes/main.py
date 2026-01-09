from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from app.models.user import Role
from app.models.company import Company

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return render_template('public/landing.html')


@bp.route('/pricing')
def pricing():
    plans = Company.get_plans_for_display()
    return render_template('public/pricing.html', plans=plans)


@bp.route('/dashboard')
@login_required
def dashboard():
    # Superadmin goes to root dashboard
    if current_user.is_superadmin:
        return redirect(url_for('root.dashboard'))
    elif current_user.is_admin():
        return redirect(url_for('admin.dashboard'))
    elif current_user.is_hr():
        return redirect(url_for('admin.dashboard'))
    elif current_user.is_manager():
        return redirect(url_for('manager.dashboard'))
    else:
        return redirect(url_for('employee.dashboard'))
