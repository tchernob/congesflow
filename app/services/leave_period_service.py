"""
Service de gestion des périodes de congés et des reports.
Gère la réglementation française des congés payés.
"""
from datetime import date, timedelta
from app import db
from app.models.leave import LeaveBalance, LeaveType, CompanyLeaveSettings
from app.models.notification import Notification
from app.models.user import User


class LeavePeriodService:
    """Service pour gérer les périodes de congés et les reports."""

    def __init__(self, company_id):
        self.company_id = company_id
        self.settings = CompanyLeaveSettings.get_or_create_for_company(company_id)

    def get_current_period(self):
        """Retourne les dates de la période de référence actuelle."""
        year = self.settings.get_current_period_year()
        return {
            'year': year,
            'start': self.settings.get_period_start(year),
            'end': self.settings.get_period_end(year)
        }

    def get_period_label(self, year=None):
        """Retourne un label lisible pour la période."""
        if year is None:
            year = self.settings.get_current_period_year()

        start = self.settings.get_period_start(year)
        end = self.settings.get_period_end(year)

        if self.settings.reference_period_type == CompanyLeaveSettings.PERIOD_CALENDAR:
            return f"Année {year}"
        else:
            return f"Juin {start.year} - Mai {end.year}"

    def process_period_rollover(self, user_id, leave_type_id):
        """
        Traite le changement de période pour un utilisateur et un type de congé.
        Calcule et applique les reports de l'ancienne période vers la nouvelle.
        """
        leave_type = LeaveType.query.get(leave_type_id)
        if not leave_type:
            return None

        current_year = self.settings.get_current_period_year()
        previous_year = current_year - 1

        # Récupérer le solde de l'année précédente
        old_balance = LeaveBalance.query.filter_by(
            user_id=user_id,
            leave_type_id=leave_type_id,
            year=previous_year
        ).first()

        if not old_balance:
            return None

        # Calculer les jours restants (non utilisés, non pending)
        remaining = old_balance.initial_balance + old_balance.adjusted - old_balance.used
        if remaining <= 0:
            return None

        # Déterminer le maximum reportable
        max_carryover = self.settings.get_max_carryover(leave_type.code)
        carryover_amount = min(remaining, max_carryover)

        if carryover_amount <= 0:
            return None

        # Récupérer ou créer le solde de l'année courante
        new_balance = LeaveBalance.query.filter_by(
            user_id=user_id,
            leave_type_id=leave_type_id,
            year=current_year
        ).first()

        if not new_balance:
            new_balance = LeaveBalance(
                user_id=user_id,
                leave_type_id=leave_type_id,
                year=current_year,
                initial_balance=leave_type.default_days or 0
            )
            db.session.add(new_balance)

        # Appliquer le report
        new_balance.carried_over = carryover_amount
        new_balance.carried_over_expires_at = self.settings.get_carryover_expiry_date(
            previous_year, leave_type.code
        )
        new_balance.carried_over_used = 0

        db.session.commit()

        return {
            'carried_over': carryover_amount,
            'expires_at': new_balance.carried_over_expires_at,
            'lost': max(0, remaining - max_carryover)
        }

    def process_all_rollovers_for_company(self):
        """
        Traite les reports pour tous les utilisateurs de l'entreprise.
        À exécuter au changement de période (via cron ou manuellement).
        """
        from app.models.company import Company
        company = Company.query.get(self.company_id)
        if not company:
            return []

        results = []
        users = User.query.filter_by(company_id=self.company_id, is_active=True).all()
        leave_types = LeaveType.query.filter_by(company_id=self.company_id, is_active=True).all()

        for user in users:
            for leave_type in leave_types:
                result = self.process_period_rollover(user.id, leave_type.id)
                if result:
                    results.append({
                        'user_id': user.id,
                        'user_name': user.full_name,
                        'leave_type': leave_type.code,
                        **result
                    })

        return results

    def check_expiring_balances(self, days_ahead=None):
        """
        Vérifie les soldes qui vont expirer prochainement.
        Retourne la liste des utilisateurs concernés.
        """
        if days_ahead is None:
            days_ahead = self.settings.alert_days_before_expiry

        expiry_threshold = date.today() + timedelta(days=days_ahead)

        expiring = db.session.query(LeaveBalance, User, LeaveType).join(
            User, LeaveBalance.user_id == User.id
        ).join(
            LeaveType, LeaveBalance.leave_type_id == LeaveType.id
        ).filter(
            User.company_id == self.company_id,
            User.is_active == True,
            LeaveBalance.carried_over > LeaveBalance.carried_over_used,
            LeaveBalance.carried_over_expires_at != None,
            LeaveBalance.carried_over_expires_at <= expiry_threshold,
            LeaveBalance.carried_over_expires_at > date.today()
        ).all()

        results = []
        for balance, user, leave_type in expiring:
            days_remaining = balance.carried_over_available
            days_until_expiry = (balance.carried_over_expires_at - date.today()).days

            results.append({
                'user_id': user.id,
                'user_name': user.full_name,
                'user_email': user.email,
                'leave_type': leave_type.code,
                'leave_type_name': leave_type.name,
                'days_expiring': days_remaining,
                'expires_at': balance.carried_over_expires_at,
                'days_until_expiry': days_until_expiry
            })

        return results

    def send_expiry_alerts(self):
        """Envoie des notifications pour les congés qui vont expirer."""
        expiring = self.check_expiring_balances()

        for item in expiring:
            # Créer une notification
            notification = Notification(
                user_id=item['user_id'],
                title="Congés en cours d'expiration",
                message=f"Vous avez {item['days_expiring']} jour(s) de {item['leave_type_name']} "
                        f"qui expireront le {item['expires_at'].strftime('%d/%m/%Y')}. "
                        f"Pensez à les poser avant cette date !",
                notification_type='warning',
                link='/employee/requests/new'
            )
            db.session.add(notification)

        db.session.commit()
        return len(expiring)

    def get_user_balance_details(self, user_id, leave_type_id, year=None):
        """
        Retourne le détail complet du solde d'un utilisateur.
        Inclut les informations sur les reports et expirations.
        """
        if year is None:
            year = self.settings.get_current_period_year()

        balance = LeaveBalance.query.filter_by(
            user_id=user_id,
            leave_type_id=leave_type_id,
            year=year
        ).first()

        if not balance:
            return None

        leave_type = LeaveType.query.get(leave_type_id)

        details = {
            'year': year,
            'period_label': self.get_period_label(year),
            'leave_type': leave_type.code if leave_type else None,
            'leave_type_name': leave_type.name if leave_type else None,

            # Solde de base
            'initial_balance': balance.initial_balance,
            'adjusted': balance.adjusted,
            'used': balance.used,
            'pending': balance.pending,

            # Reports
            'carried_over': balance.carried_over,
            'carried_over_used': balance.carried_over_used,
            'carried_over_available': balance.carried_over_available,
            'carried_over_expires_at': balance.carried_over_expires_at,
            'carried_over_expired': balance.carried_over_expired,

            # Totaux
            'total_available': balance.available,
            'total_current_year': balance.available_current_year,

            # Alertes
            'days_expiring_soon': balance.days_expiring_soon,
            'is_low_balance': balance.available < self.settings.alert_low_balance_threshold
        }

        # Calculer les jours jusqu'à expiration
        if balance.carried_over_expires_at and balance.carried_over_available > 0:
            days_until = (balance.carried_over_expires_at - date.today()).days
            details['days_until_expiry'] = max(0, days_until)
        else:
            details['days_until_expiry'] = None

        return details

    def initialize_balances_for_user(self, user_id, start_date=None):
        """
        Initialise les soldes de congés pour un nouvel utilisateur.
        Calcule au prorata si l'utilisateur arrive en cours de période.
        """
        if start_date is None:
            start_date = date.today()

        current_year = self.settings.get_current_period_year()
        period_start = self.settings.get_period_start(current_year)
        period_end = self.settings.get_period_end(current_year)

        # Calculer les mois restants dans la période
        if start_date <= period_start:
            months_in_period = 12
        elif start_date > period_end:
            # L'utilisateur arrive après la fin de la période, créer pour la suivante
            current_year += 1
            months_in_period = 12
        else:
            # Calcul au prorata
            total_days = (period_end - period_start).days
            remaining_days = (period_end - start_date).days
            months_in_period = (remaining_days / total_days) * 12

        # Récupérer les types de congés de l'entreprise
        user = User.query.get(user_id)
        if not user:
            return []

        leave_types = LeaveType.query.filter_by(
            company_id=user.company_id,
            is_active=True
        ).all()

        created_balances = []
        for leave_type in leave_types:
            # Vérifier si le solde existe déjà
            existing = LeaveBalance.query.filter_by(
                user_id=user_id,
                leave_type_id=leave_type.id,
                year=current_year
            ).first()

            if existing:
                continue

            # Calculer le solde initial au prorata
            if leave_type.code in ['CP', 'RTT']:
                # Congés acquis progressivement
                if leave_type.code == 'CP':
                    initial = round(self.settings.monthly_acquisition_rate * months_in_period, 1)
                else:
                    initial = round((leave_type.default_days or 0) * months_in_period / 12, 1)
            else:
                # Congés exceptionnels - solde complet
                initial = leave_type.default_days or 0

            balance = LeaveBalance(
                user_id=user_id,
                leave_type_id=leave_type.id,
                year=current_year,
                initial_balance=initial,
                acquisition_start_date=start_date,
                months_worked=months_in_period
            )
            db.session.add(balance)
            created_balances.append({
                'leave_type': leave_type.code,
                'initial_balance': initial
            })

        db.session.commit()
        return created_balances

    def recalculate_acquisition(self, user_id, leave_type_id):
        """
        Recalcule l'acquisition progressive pour un utilisateur.
        Utile pour mettre à jour le solde en cours d'année.
        """
        current_year = self.settings.get_current_period_year()
        balance = LeaveBalance.query.filter_by(
            user_id=user_id,
            leave_type_id=leave_type_id,
            year=current_year
        ).first()

        if not balance or not balance.acquisition_start_date:
            return None

        leave_type = LeaveType.query.get(leave_type_id)
        if not leave_type:
            return None

        period_start = self.settings.get_period_start(current_year)
        today = date.today()

        # Calculer les mois travaillés jusqu'à aujourd'hui
        start_date = max(balance.acquisition_start_date, period_start)
        months_worked = ((today.year - start_date.year) * 12 + today.month - start_date.month)
        months_worked = max(0, min(12, months_worked))

        # Recalculer le solde
        if leave_type.code == 'CP':
            new_balance = round(self.settings.monthly_acquisition_rate * months_worked, 1)
        else:
            new_balance = round((leave_type.default_days or 0) * months_worked / 12, 1)

        balance.initial_balance = new_balance
        balance.months_worked = months_worked
        db.session.commit()

        return {
            'months_worked': months_worked,
            'new_balance': new_balance
        }


def run_daily_leave_tasks():
    """
    Tâche quotidienne à exécuter via un cron ou scheduler.
    - Vérifie les reports qui expirent
    - Envoie les alertes
    """
    from app.models.company import Company

    companies = Company.query.filter_by(is_active=True).all()
    total_alerts = 0

    for company in companies:
        service = LeavePeriodService(company.id)
        alerts_sent = service.send_expiry_alerts()
        total_alerts += alerts_sent

    return total_alerts


def run_period_rollover():
    """
    Tâche à exécuter au changement de période (1er juin ou 1er janvier selon config).
    Traite les reports pour toutes les entreprises.
    """
    from app.models.company import Company

    companies = Company.query.filter_by(is_active=True).all()
    all_results = []

    for company in companies:
        service = LeavePeriodService(company.id)
        results = service.process_all_rollovers_for_company()
        all_results.extend(results)

    return all_results
