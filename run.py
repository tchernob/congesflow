#!/usr/bin/env python3
"""
TimeOff - Leave Management SaaS
Run this file to start the application.
"""

from app import create_app, db
from app.models import (
    User, Role, LeaveType, LeaveBalance, Team, Company, CompanyInvitation,
    LeaveRequest, CompanyLeaveSettings, Notification, SlackIntegration, SlackUserMapping,
    ContractType
)
from datetime import date, datetime, timedelta
import click

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


@app.cli.command('accrue-leave')
@click.option('--dry-run', is_flag=True, help='Simuler sans modifier la base de données')
@click.option('--company-id', type=int, help='Traiter uniquement une entreprise spécifique')
def accrue_leave(dry_run, company_id):
    """
    Acquisition mensuelle des congés.

    Cette commande doit être exécutée le 1er de chaque mois via CRON.
    Elle crédite les jours acquis selon le type de contrat de chaque employé.

    Exemple CRON (1er de chaque mois à 6h00):
        0 6 1 * * cd /home/tcher/timeoff && source venv/bin/activate && flask accrue-leave
    """
    current_month = date.today().replace(day=1)
    current_year = current_month.year

    print(f"=== Acquisition mensuelle des congés - {current_month.strftime('%B %Y')} ===")
    if dry_run:
        print("MODE SIMULATION - Aucune modification ne sera effectuée")
    print()

    # Statistiques
    stats = {
        'users_processed': 0,
        'balances_updated': 0,
        'days_accrued_cp': 0,
        'days_accrued_rtt': 0,
        'skipped_no_contract': 0,
        'skipped_already_processed': 0,
        'errors': []
    }

    # Récupérer les entreprises à traiter
    if company_id:
        companies = Company.query.filter_by(id=company_id).all()
    else:
        companies = Company.query.filter_by(is_active=True).all()

    for company in companies:
        print(f"\n--- {company.name} ---")

        # Récupérer les utilisateurs actifs de cette entreprise
        users = User.query.filter_by(
            company_id=company.id,
            is_active=True
        ).all()

        # Récupérer les types de congés
        cp_type = LeaveType.query.filter_by(company_id=company.id, code='CP').first()
        rtt_type = LeaveType.query.filter_by(company_id=company.id, code='RTT').first()

        for user in users:
            stats['users_processed'] += 1

            # Vérifier le type de contrat
            if not user.contract_type:
                stats['skipped_no_contract'] += 1
                print(f"  {user.full_name}: pas de type de contrat défini, ignoré")
                continue

            contract = user.contract_type

            # Traiter les CP
            if cp_type and contract.cp_acquisition_rate > 0:
                balance = LeaveBalance.query.filter_by(
                    user_id=user.id,
                    leave_type_id=cp_type.id,
                    year=current_year
                ).first()

                # Créer le solde s'il n'existe pas
                if not balance:
                    balance = LeaveBalance(
                        user_id=user.id,
                        leave_type_id=cp_type.id,
                        year=current_year,
                        initial_balance=0,
                        accrued=0,
                        last_accrual_date=None
                    )
                    if not dry_run:
                        db.session.add(balance)

                # Vérifier si déjà traité ce mois
                if balance.last_accrual_date and balance.last_accrual_date >= current_month:
                    stats['skipped_already_processed'] += 1
                else:
                    # Créditer les jours
                    days_to_add = contract.cp_acquisition_rate

                    # Ne pas dépasser le plafond annuel
                    max_annual = contract.cp_annual_allowance
                    current_accrued = balance.accrued or 0
                    if current_accrued + days_to_add > max_annual:
                        days_to_add = max(0, max_annual - current_accrued)

                    if days_to_add > 0:
                        if not dry_run:
                            balance.accrued = (balance.accrued or 0) + days_to_add
                            balance.initial_balance = balance.accrued
                            balance.last_accrual_date = current_month

                        stats['balances_updated'] += 1
                        stats['days_accrued_cp'] += days_to_add
                        print(f"  {user.full_name}: +{days_to_add:.2f}j CP (total: {(balance.accrued or 0) + days_to_add:.2f}j)")

            # Traiter les RTT
            if rtt_type and contract.has_rtt and contract.rtt_annual_allowance > 0:
                balance = LeaveBalance.query.filter_by(
                    user_id=user.id,
                    leave_type_id=rtt_type.id,
                    year=current_year
                ).first()

                # Créer le solde s'il n'existe pas
                if not balance:
                    balance = LeaveBalance(
                        user_id=user.id,
                        leave_type_id=rtt_type.id,
                        year=current_year,
                        initial_balance=0,
                        accrued=0,
                        last_accrual_date=None
                    )
                    if not dry_run:
                        db.session.add(balance)

                # Vérifier si déjà traité ce mois
                if balance.last_accrual_date and balance.last_accrual_date >= current_month:
                    pass  # Déjà compté dans skipped
                else:
                    # RTT = allocation annuelle / 12
                    monthly_rtt = contract.rtt_annual_allowance / 12

                    # Ne pas dépasser le plafond annuel
                    max_annual = contract.rtt_annual_allowance
                    current_accrued = balance.accrued or 0
                    if current_accrued + monthly_rtt > max_annual:
                        monthly_rtt = max(0, max_annual - current_accrued)

                    if monthly_rtt > 0:
                        if not dry_run:
                            balance.accrued = (balance.accrued or 0) + monthly_rtt
                            balance.initial_balance = balance.accrued
                            balance.last_accrual_date = current_month

                        stats['balances_updated'] += 1
                        stats['days_accrued_rtt'] += monthly_rtt
                        print(f"  {user.full_name}: +{monthly_rtt:.2f}j RTT (total: {(balance.accrued or 0) + monthly_rtt:.2f}j)")

    if not dry_run:
        db.session.commit()

    # Afficher le résumé
    print("\n" + "=" * 50)
    print("RÉSUMÉ")
    print("=" * 50)
    print(f"Utilisateurs traités:      {stats['users_processed']}")
    print(f"Soldes mis à jour:         {stats['balances_updated']}")
    print(f"Jours CP acquis:           {stats['days_accrued_cp']:.2f}")
    print(f"Jours RTT acquis:          {stats['days_accrued_rtt']:.2f}")
    print(f"Ignorés (pas de contrat):  {stats['skipped_no_contract']}")
    print(f"Ignorés (déjà traités):    {stats['skipped_already_processed']}")

    if dry_run:
        print("\n⚠️  MODE SIMULATION - Relancez sans --dry-run pour appliquer les modifications")


@app.cli.command('init-year-balances')
@click.option('--year', type=int, default=None, help='Année à initialiser (défaut: année en cours)')
@click.option('--company-id', type=int, help='Traiter uniquement une entreprise spécifique')
def init_year_balances(year, company_id):
    """
    Initialise les soldes de congés pour une nouvelle année.

    À exécuter en janvier pour créer les soldes de la nouvelle année.
    Les reports de l'année précédente sont automatiquement calculés.
    """
    if year is None:
        year = date.today().year

    print(f"=== Initialisation des soldes {year} ===")

    # Récupérer les entreprises
    if company_id:
        companies = Company.query.filter_by(id=company_id).all()
    else:
        companies = Company.query.filter_by(is_active=True).all()

    created_count = 0

    for company in companies:
        print(f"\n--- {company.name} ---")

        users = User.query.filter_by(company_id=company.id, is_active=True).all()
        leave_types = LeaveType.query.filter_by(company_id=company.id, is_active=True).all()

        for user in users:
            for lt in leave_types:
                # Vérifier si le solde existe déjà
                existing = LeaveBalance.query.filter_by(
                    user_id=user.id,
                    leave_type_id=lt.id,
                    year=year
                ).first()

                if existing:
                    continue

                # Créer le nouveau solde
                balance = LeaveBalance(
                    user_id=user.id,
                    leave_type_id=lt.id,
                    year=year,
                    initial_balance=0,
                    accrued=0,
                    last_accrual_date=None
                )

                # Calculer le report de l'année précédente (pour CP uniquement)
                if lt.code == 'CP':
                    prev_balance = LeaveBalance.query.filter_by(
                        user_id=user.id,
                        leave_type_id=lt.id,
                        year=year - 1
                    ).first()

                    if prev_balance and prev_balance.available > 0:
                        # Reporter les jours non utilisés (max 5 jours selon la loi)
                        carryover = min(prev_balance.available, 5)
                        balance.carried_over = carryover
                        # Expiration au 31 mai de l'année en cours
                        balance.carried_over_expires_at = date(year, 5, 31)
                        print(f"  {user.full_name}: {carryover:.1f}j CP reportés de {year-1}")

                db.session.add(balance)
                created_count += 1

    db.session.commit()
    print(f"\n{created_count} solde(s) créé(s) pour {year}")


@app.cli.command('process-trials')
@click.option('--dry-run', is_flag=True, help='Simuler sans envoyer d\'emails ni modifier la base')
def process_trials(dry_run):
    """
    Traite les rappels d'essai et expire les essais terminés.

    Cette commande doit être exécutée quotidiennement via CRON.
    Elle envoie les rappels à J-7, J-3, J-1, J0 et passe les comptes
    expirés en plan Free.

    Exemple CRON (tous les jours à 9h00):
        0 9 * * * cd /home/tcher/timeoff && source venv/bin/activate && flask process-trials
    """
    from app.services.trial_service import process_trial_reminders, REMINDER_DAYS

    print("=== Traitement des périodes d'essai ===")
    if dry_run:
        print("MODE SIMULATION - Aucune modification ne sera effectuée\n")

    if dry_run:
        # En mode dry-run, juste afficher ce qui serait fait
        from app.services.trial_service import get_companies_needing_reminder, get_expired_trials

        for days in REMINDER_DAYS:
            companies = get_companies_needing_reminder(days)
            if companies:
                print(f"\nRappels à envoyer (J-{days}):")
                for company in companies:
                    print(f"  - {company.name} ({company.email})")

        expired = get_expired_trials()
        if expired:
            print(f"\nEssais à expirer:")
            for company in expired:
                print(f"  - {company.name} -> passage en plan Free")

        if not any([get_companies_needing_reminder(d) for d in REMINDER_DAYS]) and not expired:
            print("Aucune action à effectuer aujourd'hui.")
    else:
        stats = process_trial_reminders()

        print(f"\nRésumé:")
        print(f"  Rappels envoyés: {stats['reminders_sent']}")
        print(f"  Essais expirés:  {stats['trials_expired']}")

        if stats['errors']:
            print(f"\nErreurs ({len(stats['errors'])}):")
            for error in stats['errors']:
                print(f"  - {error}")


@app.cli.command('create-superadmin')
@click.argument('email')
@click.argument('password')
@click.option('--first-name', default='Super', help='First name')
@click.option('--last-name', default='Admin', help='Last name')
def create_superadmin(email, password, first_name, last_name):
    """Create a superadmin user for platform management.

    Usage: flask create-superadmin email@example.com mypassword
    """
    # Ensure roles exist
    Role.insert_roles()

    # Check if email already exists
    existing = User.query.filter_by(email=email).first()
    if existing:
        if existing.is_superadmin:
            print(f'Superadmin {email} already exists.')
        else:
            # Upgrade existing user to superadmin
            existing.is_superadmin = True
            db.session.commit()
            print(f'User {email} upgraded to superadmin.')
        return

    # Get admin role (required for role_id)
    admin_role = Role.query.filter_by(name='admin').first()
    if not admin_role:
        print('Error: Admin role not found. Run flask init-db first.')
        return

    # Create superadmin (no company_id)
    superadmin = User(
        email=email,
        first_name=first_name,
        last_name=last_name,
        role_id=admin_role.id,
        company_id=None,
        is_superadmin=True,
        is_active=True,
        email_verified=True
    )
    superadmin.set_password(password)
    db.session.add(superadmin)
    db.session.commit()

    print(f'Superadmin created successfully!')
    print(f'  Email: {email}')
    print(f'  Password: {password}')
    print(f'  Access: /root/')


if __name__ == '__main__':
    app.run(debug=True, port=5007)
