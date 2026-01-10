# TimeOff - Leave Management SaaS

## Description
Application SaaS de gestion des congés pour les entreprises françaises. Multi-tenant avec système d'abonnement Stripe.

## Stack technique
- **Backend**: Flask (Python)
- **Base de données**: PostgreSQL (production), SQLite (dev)
- **ORM**: SQLAlchemy avec Flask-Migrate
- **Auth**: Flask-Login
- **Paiements**: Stripe (abonnements)
- **Emails**: Flask-Mail
- **Frontend**: Jinja2 templates + CSS custom (variables CSS)

## Structure du projet
```
app/
├── models/          # Modèles SQLAlchemy
│   ├── user.py      # User, Role
│   ├── company.py   # Company (multi-tenant)
│   ├── leave.py     # LeaveType, LeaveBalance, LeaveRequest
│   └── ...
├── routes/          # Blueprints Flask
│   ├── admin.py     # Routes admin entreprise (/admin/*)
│   ├── employee.py  # Routes employé
│   ├── auth.py      # Login, logout, signup
│   ├── marketing.py # Pages publiques (/, /pricing, /signup)
│   └── root.py      # Superadmin plateforme (/root/*)
├── services/        # Logique métier
│   ├── trial_service.py      # Gestion période d'essai
│   ├── leave_period_service.py
│   └── ...
├── templates/       # Templates Jinja2
│   ├── admin/       # Pages admin
│   ├── employee/    # Pages employé
│   ├── marketing/   # Pages publiques
│   └── base.html    # Layout principal
└── static/
    └── css/style.css  # Styles globaux
```

## Commandes CLI importantes
```bash
flask init-db              # Initialiser la base + rôles
flask create-superadmin EMAIL PASSWORD  # Créer superadmin plateforme
flask sync-leave-types     # Ajouter types de congés manquants (EXA, etc.)
flask accrue-leave         # Acquisition mensuelle des congés (CRON)
flask init-year-balances   # Initialiser soldes nouvelle année
flask process-trials       # Traiter fins de période d'essai (CRON)
```

## Modèle économique
- **Free**: 5 employés max, gratuit
- **Starter**: 25 employés, 29€/mois
- **Pro**: 100 employés, 79€/mois
- **Enterprise**: Illimité, 199€/mois
- **Période d'essai**: 14 jours sur plan Pro

## Types de congés par défaut
- CP (Congés payés) - 25j
- RTT - 10j
- MAL (Maladie) - justificatif requis
- CSS (Sans solde)
- MAR (Mariage) - 5j
- NAI (Naissance) - 3j
- DEC (Décès) - 5j
- DEM (Déménagement) - 1j
- EXA (Congés examens) - 5j (alternants)

## Rôles utilisateurs
- `employee`: Employé standard
- `manager`: Gestionnaire d'équipe
- `hr`: Ressources humaines
- `admin`: Administrateur entreprise
- `is_superadmin=True`: Admin plateforme (accès /root/)

## Points d'attention
- Les congés payés (CP) peuvent avoir un report N-1 (carried_over)
- Acquisition progressive: 2.08j CP/mois selon type de contrat
- Format français: virgule comme séparateur décimal (12,5 jours)
- Période d'essai: bannière affichée + emails de rappel J-7, J-3, J-1, J0
- Variables CSS: --color-ink, --color-accent, --color-border, etc.

## Déploiement
- Serveur: Ubuntu avec nginx
- CRON jobs:
  - `0 6 1 * * flask accrue-leave` (1er du mois)
  - `0 9 * * * flask process-trials` (tous les jours)

## Git
- Repo: github.com:tchernob/congesflow.git
- Branche principale: main
