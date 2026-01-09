from datetime import datetime, date, timedelta
from app import db


class LeaveType(db.Model):
    __tablename__ = 'leave_types'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=True, index=True)
    name = db.Column(db.String(50), nullable=False)
    code = db.Column(db.String(10), nullable=False)
    description = db.Column(db.String(200))
    color = db.Column(db.String(7), default='#3B82F6')
    requires_justification = db.Column(db.Boolean, default=False)
    max_consecutive_days = db.Column(db.Integer)
    default_days = db.Column(db.Float, default=0)  # Default annual allocation
    is_paid = db.Column(db.Boolean, default=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('company_id', 'code', name='unique_leave_code_per_company'),
    )

    leave_requests = db.relationship('LeaveRequest', backref='leave_type', lazy='dynamic')
    leave_balances = db.relationship('LeaveBalance', backref='leave_type', lazy='dynamic')

    # Codes prédéfinis
    CONGES_PAYES = 'CP'
    RTT = 'RTT'
    MALADIE = 'MAL'
    SANS_SOLDE = 'CSS'
    MARIAGE = 'MAR'
    NAISSANCE = 'NAI'
    DECES = 'DEC'
    DEMENAGEMENT = 'DEM'

    @staticmethod
    def get_default_types():
        """Return default leave types configuration."""
        return [
            {'name': 'Congés payés', 'code': 'CP', 'color': '#10B981', 'description': 'Congés payés annuels', 'default_days': 25},
            {'name': 'RTT', 'code': 'RTT', 'color': '#3B82F6', 'description': 'Réduction du temps de travail', 'default_days': 10},
            {'name': 'Maladie', 'code': 'MAL', 'color': '#EF4444', 'requires_justification': True,
             'description': 'Arrêt maladie', 'default_days': 0},
            {'name': 'Sans solde', 'code': 'CSS', 'color': '#6B7280', 'is_paid': False,
             'description': 'Congés sans solde', 'default_days': 0},
            {'name': 'Mariage', 'code': 'MAR', 'color': '#EC4899', 'max_consecutive_days': 5,
             'description': 'Congé pour mariage', 'default_days': 5},
            {'name': 'Naissance', 'code': 'NAI', 'color': '#8B5CF6', 'max_consecutive_days': 3,
             'description': 'Congé pour naissance', 'default_days': 3},
            {'name': 'Décès', 'code': 'DEC', 'color': '#374151', 'max_consecutive_days': 5,
             'description': 'Congé pour décès', 'default_days': 5},
            {'name': 'Déménagement', 'code': 'DEM', 'color': '#F59E0B', 'max_consecutive_days': 1,
             'description': 'Congé pour déménagement', 'default_days': 1},
        ]

    @staticmethod
    def insert_default_types(company_id=None):
        """Insert default leave types for a company."""
        types = LeaveType.get_default_types()
        for type_data in types:
            type_data['company_id'] = company_id
            leave_type = LeaveType.query.filter_by(code=type_data['code'], company_id=company_id).first()
            if leave_type is None:
                leave_type = LeaveType(**type_data)
                db.session.add(leave_type)
        db.session.commit()

    def __repr__(self):
        return f'<LeaveType {self.code}>'


class LeaveBalance(db.Model):
    __tablename__ = 'leave_balances'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False)
    year = db.Column(db.Integer, nullable=False)  # Année de la période de référence

    # Soldes de base
    initial_balance = db.Column(db.Float, default=0)  # Allocation annuelle
    used = db.Column(db.Float, default=0)  # Jours utilisés (approuvés)
    pending = db.Column(db.Float, default=0)  # Jours en attente de validation
    adjusted = db.Column(db.Float, default=0)  # Ajustements manuels RH

    # Gestion des reports (réglementation française)
    carried_over = db.Column(db.Float, default=0)  # Jours reportés de l'année précédente
    carried_over_expires_at = db.Column(db.Date, nullable=True)  # Date d'expiration du report
    carried_over_used = db.Column(db.Float, default=0)  # Jours reportés déjà utilisés

    # Acquisition progressive (2.08 jours/mois)
    acquisition_start_date = db.Column(db.Date, nullable=True)  # Date de début d'acquisition
    months_worked = db.Column(db.Float, default=12)  # Mois travaillés dans la période
    last_accrual_date = db.Column(db.Date, nullable=True)  # Date de la dernière acquisition mensuelle
    accrued = db.Column(db.Float, default=0)  # Total des jours acquis progressivement

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'leave_type_id', 'year', name='unique_balance_per_type_year'),
    )

    @property
    def carried_over_available(self):
        """Jours reportés encore disponibles (non expirés, non utilisés)."""
        if self.carried_over_expires_at and date.today() > self.carried_over_expires_at:
            return 0  # Reports expirés
        return max(0, self.carried_over - self.carried_over_used)

    @property
    def carried_over_expired(self):
        """Jours reportés qui ont expiré sans être utilisés."""
        if self.carried_over_expires_at and date.today() > self.carried_over_expires_at:
            return max(0, self.carried_over - self.carried_over_used)
        return 0

    @property
    def available(self):
        """Total des jours disponibles (solde + reports non expirés - utilisés - pending)."""
        base = self.initial_balance + self.adjusted - self.used - self.pending
        return base + self.carried_over_available

    @property
    def available_current_year(self):
        """Jours disponibles de l'année en cours uniquement (sans les reports)."""
        return max(0, self.initial_balance + self.adjusted - self.used - self.pending)

    @property
    def total(self):
        """Total des jours acquis (base + ajustements + reports valides)."""
        return self.initial_balance + self.adjusted + self.carried_over_available

    @property
    def days_expiring_soon(self):
        """Jours qui vont expirer dans les 30 prochains jours."""
        if not self.carried_over_expires_at:
            return 0
        days_until_expiry = (self.carried_over_expires_at - date.today()).days
        if 0 < days_until_expiry <= 30:
            return self.carried_over_available
        return 0

    def use_days(self, days_count):
        """
        Utilise des jours en respectant la règle FIFO (reports d'abord).
        Retourne un tuple (jours_reports_utilisés, jours_courants_utilisés).
        """
        remaining = days_count
        carried_used = 0
        current_used = 0

        # D'abord utiliser les reports (FIFO - First In First Out)
        if self.carried_over_available > 0 and remaining > 0:
            carried_used = min(self.carried_over_available, remaining)
            self.carried_over_used += carried_used
            remaining -= carried_used

        # Ensuite utiliser le solde courant
        if remaining > 0:
            current_used = remaining
            self.used += current_used

        return (carried_used, current_used)

    def __repr__(self):
        return f'<LeaveBalance {self.user_id} - {self.leave_type_id} - {self.year}>'


class CompanyLeaveSettings(db.Model):
    """Configuration des règles de congés par entreprise."""
    __tablename__ = 'company_leave_settings'

    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False, unique=True)

    # Période de référence pour les CP
    # 'legal' = 1er juin N au 31 mai N+1 (légal)
    # 'calendar' = Année civile (1er janvier au 31 décembre)
    reference_period_type = db.Column(db.String(20), default='legal')

    # Date de début personnalisée (si reference_period_type = 'custom')
    # Format: jour et mois (ex: 1er juin = 1, 6)
    custom_period_start_day = db.Column(db.Integer, default=1)
    custom_period_start_month = db.Column(db.Integer, default=6)  # Juin par défaut

    # Règles de report des CP
    cp_carryover_enabled = db.Column(db.Boolean, default=True)  # Autoriser le report
    cp_carryover_max_days = db.Column(db.Float, default=5)  # Maximum de jours reportables
    cp_carryover_deadline_months = db.Column(db.Integer, default=3)  # Délai d'utilisation en mois après fin de période

    # Règles de report des RTT
    rtt_carryover_enabled = db.Column(db.Boolean, default=False)  # Par défaut pas de report RTT
    rtt_carryover_max_days = db.Column(db.Float, default=0)
    rtt_carryover_deadline_months = db.Column(db.Integer, default=1)

    # Règles générales
    allow_negative_balance = db.Column(db.Boolean, default=False)  # Autoriser solde négatif
    max_negative_days = db.Column(db.Float, default=0)  # Maximum de jours en négatif

    # Acquisition progressive
    monthly_acquisition_rate = db.Column(db.Float, default=2.08)  # Jours acquis par mois (25/12)

    # Alertes
    alert_days_before_expiry = db.Column(db.Integer, default=30)  # Alerte X jours avant expiration
    alert_low_balance_threshold = db.Column(db.Float, default=5)  # Alerte si solde < X jours

    # Workflow de validation
    # 'manager_then_hr' = Manager approuve, puis RH approuve (défaut)
    # 'manager_only' = Manager approuve directement
    # 'hr_only' = RH approuve directement (pas de validation manager)
    # 'manager_or_hr' = Manager OU RH peut approuver
    approval_workflow = db.Column(db.String(20), default='manager_then_hr')

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    company = db.relationship('Company', backref=db.backref('leave_settings', uselist=False))

    # Constantes - Périodes
    PERIOD_LEGAL = 'legal'  # 1er juin - 31 mai
    PERIOD_CALENDAR = 'calendar'  # Année civile
    PERIOD_CUSTOM = 'custom'  # Personnalisé

    # Constantes - Workflows
    WORKFLOW_MANAGER_THEN_HR = 'manager_then_hr'
    WORKFLOW_MANAGER_ONLY = 'manager_only'
    WORKFLOW_HR_ONLY = 'hr_only'
    WORKFLOW_MANAGER_OR_HR = 'manager_or_hr'

    WORKFLOW_LABELS = {
        'manager_then_hr': 'Manager puis RH',
        'manager_only': 'Manager seul',
        'hr_only': 'RH seul',
        'manager_or_hr': 'Manager ou RH'
    }

    WORKFLOW_DESCRIPTIONS = {
        'manager_then_hr': 'La demande doit être approuvée par le manager, puis par les RH',
        'manager_only': 'Seule l\'approbation du manager est requise',
        'hr_only': 'Seule l\'approbation des RH est requise',
        'manager_or_hr': 'Le manager ou les RH peuvent approuver la demande'
    }

    def get_initial_status(self):
        """Retourne le statut initial d'une demande selon le workflow."""
        if self.approval_workflow == self.WORKFLOW_HR_ONLY:
            return 'pending_hr'
        return 'pending_manager'

    def requires_hr_approval(self):
        """Indique si le workflow nécessite une validation RH."""
        return self.approval_workflow in [self.WORKFLOW_MANAGER_THEN_HR, self.WORKFLOW_HR_ONLY]

    def requires_manager_approval(self):
        """Indique si le workflow nécessite une validation manager."""
        return self.approval_workflow in [self.WORKFLOW_MANAGER_THEN_HR, self.WORKFLOW_MANAGER_ONLY, self.WORKFLOW_MANAGER_OR_HR]

    def get_period_start(self, year):
        """Retourne la date de début de la période de référence pour une année donnée."""
        if self.reference_period_type == self.PERIOD_CALENDAR:
            return date(year, 1, 1)
        elif self.reference_period_type == self.PERIOD_LEGAL:
            return date(year, 6, 1)  # 1er juin
        else:  # custom
            return date(year, self.custom_period_start_month, self.custom_period_start_day)

    def get_period_end(self, year):
        """Retourne la date de fin de la période de référence pour une année donnée."""
        if self.reference_period_type == self.PERIOD_CALENDAR:
            return date(year, 12, 31)
        elif self.reference_period_type == self.PERIOD_LEGAL:
            return date(year + 1, 5, 31)  # 31 mai de l'année suivante
        else:  # custom
            # Un an après le début, moins un jour
            start = self.get_period_start(year)
            return date(start.year + 1, start.month, start.day) - timedelta(days=1)

    def get_carryover_expiry_date(self, period_year, leave_type_code):
        """Calcule la date d'expiration des reports pour une période donnée."""
        period_end = self.get_period_end(period_year)

        if leave_type_code == 'RTT':
            months = self.rtt_carryover_deadline_months
        else:  # CP et autres
            months = self.cp_carryover_deadline_months

        # Ajouter les mois de délai
        expiry_month = period_end.month + months
        expiry_year = period_end.year
        while expiry_month > 12:
            expiry_month -= 12
            expiry_year += 1

        # Gérer les fins de mois
        import calendar
        last_day = calendar.monthrange(expiry_year, expiry_month)[1]
        expiry_day = min(period_end.day, last_day)

        return date(expiry_year, expiry_month, expiry_day)

    def get_max_carryover(self, leave_type_code):
        """Retourne le maximum de jours reportables pour un type de congé."""
        if leave_type_code == 'RTT':
            if not self.rtt_carryover_enabled:
                return 0
            return self.rtt_carryover_max_days
        else:  # CP et autres
            if not self.cp_carryover_enabled:
                return 0
            return self.cp_carryover_max_days

    def get_current_period_year(self):
        """Retourne l'année de la période de référence actuelle."""
        today = date.today()
        if self.reference_period_type == self.PERIOD_CALENDAR:
            return today.year
        elif self.reference_period_type == self.PERIOD_LEGAL:
            # Si on est entre le 1er juin et le 31 décembre, c'est l'année en cours
            # Si on est entre le 1er janvier et le 31 mai, c'est l'année précédente
            if today.month >= 6:
                return today.year
            else:
                return today.year - 1
        else:  # custom
            period_start = self.get_period_start(today.year)
            if today >= period_start:
                return today.year
            else:
                return today.year - 1

    @staticmethod
    def get_or_create_for_company(company_id):
        """Récupère ou crée les paramètres de congés pour une entreprise."""
        settings = CompanyLeaveSettings.query.filter_by(company_id=company_id).first()
        if not settings:
            settings = CompanyLeaveSettings(company_id=company_id)
            db.session.add(settings)
            db.session.commit()
        return settings

    def __repr__(self):
        return f'<CompanyLeaveSettings {self.company_id}>'


class LeaveRequest(db.Model):
    __tablename__ = 'leave_requests'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    leave_type_id = db.Column(db.Integer, db.ForeignKey('leave_types.id'), nullable=False)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    start_half_day = db.Column(db.Boolean, default=False)
    end_half_day = db.Column(db.Boolean, default=False)

    days_count = db.Column(db.Float, nullable=False)
    reason = db.Column(db.Text)
    attachment_url = db.Column(db.String(200))

    status = db.Column(db.String(20), default='pending_manager')
    rejection_reason = db.Column(db.Text)

    manager_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    manager_decision_date = db.Column(db.DateTime)
    hr_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    hr_decision_date = db.Column(db.DateTime)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relations
    manager_reviewer = db.relationship('User', foreign_keys=[manager_id], backref='manager_reviews')
    hr_reviewer = db.relationship('User', foreign_keys=[hr_id], backref='hr_reviews')

    # Status constants
    STATUS_PENDING_MANAGER = 'pending_manager'
    STATUS_PENDING_HR = 'pending_hr'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CANCELLED = 'cancelled'

    STATUS_LABELS = {
        'pending_manager': 'En attente (Manager)',
        'pending_hr': 'En attente (RH)',
        'approved': 'Approuvé',
        'rejected': 'Refusé',
        'cancelled': 'Annulé'
    }

    STATUS_COLORS = {
        'pending_manager': 'warning',
        'pending_hr': 'info',
        'approved': 'success',
        'rejected': 'danger',
        'cancelled': 'secondary'
    }

    @property
    def status_label(self):
        return self.STATUS_LABELS.get(self.status, self.status)

    @property
    def status_color(self):
        return self.STATUS_COLORS.get(self.status, 'secondary')

    @property
    def is_pending(self):
        return self.status in [self.STATUS_PENDING_MANAGER, self.STATUS_PENDING_HR]

    @property
    def can_cancel(self):
        return self.status in [self.STATUS_PENDING_MANAGER, self.STATUS_PENDING_HR] or \
               (self.status == self.STATUS_APPROVED and self.start_date > date.today())

    def calculate_days(self):
        if self.start_date and self.end_date:
            delta = (self.end_date - self.start_date).days + 1
            # Exclure les weekends
            business_days = 0
            current = self.start_date
            from datetime import timedelta
            while current <= self.end_date:
                if current.weekday() < 5:
                    business_days += 1
                current += timedelta(days=1)

            if self.start_half_day:
                business_days -= 0.5
            if self.end_half_day:
                business_days -= 0.5

            return max(0, business_days)
        return 0

    def get_company_settings(self):
        """Récupère les paramètres de congés de l'entreprise."""
        return CompanyLeaveSettings.get_or_create_for_company(self.employee.company_id)

    def approve_by_manager(self, manager):
        """Approuve la demande par le manager."""
        settings = self.get_company_settings()
        self.manager_id = manager.id
        self.manager_decision_date = datetime.utcnow()

        # Selon le workflow, soit on passe aux RH, soit c'est fini
        if settings.approval_workflow == CompanyLeaveSettings.WORKFLOW_MANAGER_ONLY:
            # Manager seul : approbation finale
            self.status = self.STATUS_APPROVED
            self._update_balance_on_approval()
        elif settings.approval_workflow == CompanyLeaveSettings.WORKFLOW_MANAGER_OR_HR:
            # Manager OU RH : le manager peut approuver directement
            self.status = self.STATUS_APPROVED
            self._update_balance_on_approval()
        else:
            # Manager puis RH : on passe aux RH
            self.status = self.STATUS_PENDING_HR

    def approve_by_hr(self, hr_user):
        """Approuve la demande par les RH."""
        settings = self.get_company_settings()
        self.hr_id = hr_user.id
        self.hr_decision_date = datetime.utcnow()

        # Si workflow HR_ONLY ou MANAGER_OR_HR, les RH peuvent approuver directement
        # Si workflow MANAGER_THEN_HR, on vérifie que le manager a déjà approuvé (sauf si HR a plus de pouvoir)
        self.status = self.STATUS_APPROVED
        self._update_balance_on_approval()

    def reject(self, reviewer, reason=None):
        self.status = self.STATUS_REJECTED
        self.rejection_reason = reason
        if reviewer.is_hr():
            self.hr_id = reviewer.id
            self.hr_decision_date = datetime.utcnow()
        else:
            self.manager_id = reviewer.id
            self.manager_decision_date = datetime.utcnow()
        self._update_balance_on_rejection()

    def cancel(self):
        was_approved = self.status == self.STATUS_APPROVED
        self.status = self.STATUS_CANCELLED
        if was_approved:
            self._restore_balance()

    def _update_balance_on_approval(self):
        balance = LeaveBalance.query.filter_by(
            user_id=self.employee_id,
            leave_type_id=self.leave_type_id,
            year=self.start_date.year
        ).first()
        if balance:
            balance.pending -= self.days_count
            # Utiliser la méthode FIFO qui décompte d'abord les reports N-1
            balance.use_days(self.days_count)

    def _update_balance_on_rejection(self):
        balance = LeaveBalance.query.filter_by(
            user_id=self.employee_id,
            leave_type_id=self.leave_type_id,
            year=self.start_date.year
        ).first()
        if balance:
            balance.pending -= self.days_count

    def _restore_balance(self):
        """Restaure les jours lors d'une annulation (inverse de use_days)."""
        balance = LeaveBalance.query.filter_by(
            user_id=self.employee_id,
            leave_type_id=self.leave_type_id,
            year=self.start_date.year
        ).first()
        if balance:
            # Restaurer en priorité dans le compteur courant, puis dans carried_over
            remaining = self.days_count

            # D'abord restaurer dans 'used' (compteur année N)
            if balance.used > 0 and remaining > 0:
                restore_used = min(balance.used, remaining)
                balance.used -= restore_used
                remaining -= restore_used

            # Ensuite restaurer dans 'carried_over_used' (compteur N-1)
            if balance.carried_over_used > 0 and remaining > 0:
                restore_carried = min(balance.carried_over_used, remaining)
                balance.carried_over_used -= restore_carried
                remaining -= restore_carried

    def __repr__(self):
        return f'<LeaveRequest {self.id} - {self.employee_id}>'
