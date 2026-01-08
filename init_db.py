"""
Script pour initialiser la base de données distante.
Usage: DATABASE_URL=postgresql://... python init_db.py
"""
import os
from app import create_app, db
from app.models import User, Role, Company, LeaveType

def init_database():
    app = create_app()

    with app.app_context():
        # Créer toutes les tables
        db.create_all()
        print("Tables créées avec succès!")

        # Créer les rôles par défaut
        roles = [
            ('employee', 'Employé'),
            ('manager', 'Manager'),
            ('hr', 'RH'),
            ('admin', 'Administrateur')
        ]

        for role_name, role_label in roles:
            if not Role.query.filter_by(name=role_name).first():
                role = Role(name=role_name)
                db.session.add(role)
                print(f"Rôle créé: {role_name}")

        db.session.commit()

        # Créer une entreprise de démo si elle n'existe pas
        demo_company = Company.query.filter_by(slug='demo').first()
        if not demo_company:
            demo_company = Company(
                name='Demo Company',
                slug='demo',
                email='demo@timeoff.com',
                plan='trial',
                max_employees=50
            )
            db.session.add(demo_company)
            db.session.commit()
            print(f"Entreprise démo créée: {demo_company.name}")

            # Créer les types de congés par défaut
            LeaveType.insert_default_types(demo_company.id)
            print("Types de congés créés")

        # Créer un admin de démo
        admin_role = Role.query.filter_by(name='admin').first()
        admin_user = User.query.filter_by(email='admin@demo.timeoff.com').first()

        if not admin_user:
            admin_user = User(
                email='admin@demo.timeoff.com',
                first_name='Admin',
                last_name='Demo',
                role_id=admin_role.id,
                company_id=demo_company.id,
                is_active=True
            )
            admin_user.set_password('demo123')
            db.session.add(admin_user)
            db.session.commit()
            print(f"Admin créé: admin@demo.timeoff.com / demo123")

        print("\n✅ Base de données initialisée avec succès!")
        print(f"DATABASE_URL: {os.environ.get('DATABASE_URL', 'Non défini')[:50]}...")

if __name__ == '__main__':
    init_database()
