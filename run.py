#!/usr/bin/env python3
"""
TimeOff - Leave Management SaaS
Run this file to start the application.
"""

from app import create_app, db
from app.models import (
    User, Role, LeaveType, LeaveBalance, Team, Company, CompanyInvitation,
    LeaveRequest, CompanyLeaveSettings, Notification, SlackIntegration, SlackUserMapping
)
from datetime import date, datetime, timedelta

app = create_app()


@app.shell_context_processor
def make_shell_context():
    return {
        'db': db,
        'User': User,
        'Role': Role,
        'LeaveType': LeaveType,
        'LeaveBalance': LeaveBalance,
        'Team': Team,
        'Company': Company,
        'CompanyInvitation': CompanyInvitation
    }


@app.cli.command('init-db')
def init_db():
    """Initialize the database with default data."""
    db.create_all()

    # Create roles
    Role.insert_roles()
    print('Roles created.')

    print('Database initialized successfully!')
    print('Note: Leave types are now created per-company when a company signs up.')


@app.cli.command('create-admin')
def create_admin():
    """Create an admin user."""
    admin_role = Role.query.filter_by(name='admin').first()
    if not admin_role:
        print('Please run init-db first.')
        return

    existing = User.query.filter_by(email='admin@timeoff.com').first()
    if existing:
        print('Admin user already exists.')
        return

    admin = User(
        email='admin@timeoff.com',
        first_name='Admin',
        last_name='System',
        role_id=admin_role.id
    )
    admin.set_password('admin123')
    db.session.add(admin)
    db.session.commit()

    print('Admin user created:')
    print('  Email: admin@timeoff.com')
    print('  Password: admin123')


@app.cli.command('create-demo-company')
def create_demo_company():
    """Create a demo company with sample data for testing."""
    # Ensure roles exist
    Role.insert_roles()

    # Get roles
    admin_role = Role.query.filter_by(name='admin').first()
    hr_role = Role.query.filter_by(name='hr').first()
    manager_role = Role.query.filter_by(name='manager').first()
    employee_role = Role.query.filter_by(name='employee').first()

    if not all([admin_role, hr_role, manager_role, employee_role]):
        print('Error: Could not create roles.')
        return

    # Check if demo company exists
    demo_company = Company.query.filter_by(slug='demo-company').first()
    if demo_company:
        print('Demo company already exists.')
        print('Use these accounts to login:')
        print('  - Admin: admin@demo.timeoff.com / demo123')
        return

    # Create demo company
    demo_company = Company(
        name='Demo Company',
        slug='demo-company',
        email='contact@demo.timeoff.com',
        plan=Company.PLAN_PRO,
        max_employees=100,
        trial_ends_at=datetime.utcnow() + timedelta(days=365)
    )
    db.session.add(demo_company)
    db.session.flush()

    # Create leave types for this company
    LeaveType.insert_default_types(company_id=demo_company.id)

    # Create teams
    teams_data = [
        {'name': 'Développement', 'description': 'Équipe de développement logiciel', 'color': '#3B82F6'},
        {'name': 'Marketing', 'description': 'Équipe marketing et communication', 'color': '#EC4899'},
        {'name': 'Commercial', 'description': 'Équipe commerciale', 'color': '#10B981'},
    ]

    teams = {}
    for team_data in teams_data:
        team = Team(company_id=demo_company.id, **team_data)
        db.session.add(team)
        db.session.flush()
        teams[team_data['name']] = team

    # Create users
    users_data = [
        {'email': 'admin@demo.timeoff.com', 'first_name': 'Admin', 'last_name': 'Demo', 'role': admin_role, 'team': None},
        {'email': 'rh@demo.timeoff.com', 'first_name': 'Marie', 'last_name': 'Dupont', 'role': hr_role, 'team': None},
        {'email': 'manager.dev@demo.timeoff.com', 'first_name': 'Pierre', 'last_name': 'Martin', 'role': manager_role, 'team': teams['Développement']},
        {'email': 'manager.mkt@demo.timeoff.com', 'first_name': 'Sophie', 'last_name': 'Bernard', 'role': manager_role, 'team': teams['Marketing']},
        {'email': 'dev1@demo.timeoff.com', 'first_name': 'Lucas', 'last_name': 'Petit', 'role': employee_role, 'team': teams['Développement']},
        {'email': 'dev2@demo.timeoff.com', 'first_name': 'Emma', 'last_name': 'Roux', 'role': employee_role, 'team': teams['Développement']},
        {'email': 'mkt1@demo.timeoff.com', 'first_name': 'Hugo', 'last_name': 'Moreau', 'role': employee_role, 'team': teams['Marketing']},
    ]

    users = {}
    for user_data in users_data:
        user = User(
            company_id=demo_company.id,
            email=user_data['email'],
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            role_id=user_data['role'].id,
            team_id=user_data['team'].id if user_data['team'] else None
        )
        user.set_password('demo123')
        db.session.add(user)
        db.session.flush()
        users[user_data['email']] = user

    # Set managers
    manager_dev = users['manager.dev@demo.timeoff.com']
    manager_mkt = users['manager.mkt@demo.timeoff.com']

    users['dev1@demo.timeoff.com'].manager_id = manager_dev.id
    users['dev2@demo.timeoff.com'].manager_id = manager_dev.id
    users['mkt1@demo.timeoff.com'].manager_id = manager_mkt.id

    # Create leave balances for all users
    current_year = date.today().year
    leave_types = LeaveType.query.filter_by(is_active=True, company_id=demo_company.id).all()

    for user in users.values():
        for lt in leave_types:
            initial = lt.default_days
            if initial > 0:
                balance = LeaveBalance(
                    user_id=user.id,
                    leave_type_id=lt.id,
                    year=current_year,
                    initial_balance=initial
                )
                db.session.add(balance)

    db.session.commit()

    print('Demo company created!')
    print('')
    print('Demo accounts (password: demo123):')
    print('  - Admin: admin@demo.timeoff.com')
    print('  - RH: rh@demo.timeoff.com')
    print('  - Manager Dev: manager.dev@demo.timeoff.com')
    print('  - Manager Mkt: manager.mkt@demo.timeoff.com')
    print('  - Dev 1: dev1@demo.timeoff.com')
    print('  - Dev 2: dev2@demo.timeoff.com')
    print('  - Marketing: mkt1@demo.timeoff.com')


if __name__ == '__main__':
    app.run(debug=True, port=5007)
