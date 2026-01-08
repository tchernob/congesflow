from flask import Blueprint, render_template, redirect, url_for
from flask_login import login_required, current_user
from app.models.user import Role

bp = Blueprint('main', __name__)


@bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    return redirect(url_for('auth.login'))


@bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.is_admin():
        return redirect(url_for('admin.dashboard'))
    elif current_user.is_hr():
        return redirect(url_for('admin.dashboard'))
    elif current_user.is_manager():
        return redirect(url_for('manager.dashboard'))
    else:
        return redirect(url_for('employee.dashboard'))
