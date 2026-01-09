"""
Script pour initialiser la base de données distante.
Usage: DATABASE_URL=postgresql://... python init_db.py
"""
import os
from app import create_app, db
from app.models import Role

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

        print("\n✅ Base de données initialisée avec succès!")
        print(f"DATABASE_URL: {os.environ.get('DATABASE_URL', 'Non défini')[:50]}...")

if __name__ == '__main__':
    init_database()
