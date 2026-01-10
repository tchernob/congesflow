"""
Coupon model for promotional codes and discounts.
"""
from datetime import datetime
import secrets
from app import db


class Coupon(db.Model):
    """Promotional coupon codes."""
    __tablename__ = 'coupons'

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(200))

    # Discount type: 'percent' or 'fixed'
    discount_type = db.Column(db.String(20), default='percent')
    discount_value = db.Column(db.Float, nullable=False)  # Percentage (0-100) or fixed amount

    # Restrictions
    max_uses = db.Column(db.Integer, default=None)  # None = unlimited
    uses_count = db.Column(db.Integer, default=0)
    valid_from = db.Column(db.DateTime, default=datetime.utcnow)
    valid_until = db.Column(db.DateTime, default=None)  # None = no expiration

    # Plan restrictions (comma-separated list of plan names, empty = all plans)
    valid_plans = db.Column(db.String(200), default='')

    # Duration: number of months the discount applies (None = forever)
    duration_months = db.Column(db.Integer, default=None)

    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # Relations
    usages = db.relationship('CouponUsage', backref='coupon', lazy='dynamic')

    # Constants
    TYPE_PERCENT = 'percent'
    TYPE_FIXED = 'fixed'

    @staticmethod
    def generate_code(prefix='', length=8):
        """Generate a unique coupon code."""
        code = prefix.upper() + secrets.token_hex(length // 2).upper()
        while Coupon.query.filter_by(code=code).first():
            code = prefix.upper() + secrets.token_hex(length // 2).upper()
        return code

    @property
    def is_valid(self):
        """Check if coupon is currently valid."""
        if not self.is_active:
            return False
        if self.max_uses and self.uses_count >= self.max_uses:
            return False
        now = datetime.utcnow()
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True

    @property
    def remaining_uses(self):
        """Get remaining uses, or None if unlimited."""
        if self.max_uses is None:
            return None
        return max(0, self.max_uses - self.uses_count)

    @property
    def discount_display(self):
        """Get human-readable discount."""
        if self.discount_type == self.TYPE_PERCENT:
            return f"{int(self.discount_value)}%"
        else:
            return f"{self.discount_value}€"

    @property
    def valid_plans_list(self):
        """Get list of valid plans."""
        if not self.valid_plans:
            return []
        return [p.strip() for p in self.valid_plans.split(',') if p.strip()]

    def is_valid_for_plan(self, plan):
        """Check if coupon is valid for a specific plan."""
        if not self.valid_plans:
            return True  # All plans allowed
        return plan in self.valid_plans_list

    def apply_discount(self, price):
        """Apply discount to a price."""
        if self.discount_type == self.TYPE_PERCENT:
            return round(price * (1 - self.discount_value / 100), 2)
        else:
            return max(0, price - self.discount_value)

    def use(self, company_id):
        """Record a coupon usage."""
        self.uses_count += 1
        usage = CouponUsage(
            coupon_id=self.id,
            company_id=company_id
        )
        db.session.add(usage)
        return usage

    def __repr__(self):
        return f'<Coupon {self.code}>'


class CouponUsage(db.Model):
    """Track coupon usage by companies."""
    __tablename__ = 'coupon_usages'

    id = db.Column(db.Integer, primary_key=True)
    coupon_id = db.Column(db.Integer, db.ForeignKey('coupons.id'), nullable=False)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    used_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Store the discount applied at time of use
    discount_type = db.Column(db.String(20))
    discount_value = db.Column(db.Float)
    original_price = db.Column(db.Float)
    discounted_price = db.Column(db.Float)

    # Relations
    company = db.relationship('Company', backref='coupon_usages')

    def __repr__(self):
        return f'<CouponUsage {self.coupon_id} by {self.company_id}>'
