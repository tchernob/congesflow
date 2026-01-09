"""
Stripe billing routes for subscription management.
"""
import stripe
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, jsonify
from flask_login import login_required, current_user
from app import db, csrf
from app.models.company import Company
from app.routes.admin import admin_required

bp = Blueprint('billing', __name__, url_prefix='/billing')


def get_stripe():
    """Initialize and return stripe with API key."""
    stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
    return stripe


def get_price_id(plan, billing_cycle):
    """Get Stripe price ID for a plan and billing cycle."""
    price_map = {
        ('pro', 'monthly'): current_app.config.get('STRIPE_PRICE_PRO_MONTHLY'),
        ('pro', 'yearly'): current_app.config.get('STRIPE_PRICE_PRO_YEARLY'),
        ('business', 'monthly'): current_app.config.get('STRIPE_PRICE_BUSINESS_MONTHLY'),
        ('business', 'yearly'): current_app.config.get('STRIPE_PRICE_BUSINESS_YEARLY'),
    }
    return price_map.get((plan, billing_cycle))


def get_or_create_stripe_customer(company):
    """Get or create a Stripe customer for a company."""
    s = get_stripe()

    if company.stripe_customer_id:
        try:
            customer = s.Customer.retrieve(company.stripe_customer_id)
            if not customer.get('deleted'):
                return customer
        except s.error.InvalidRequestError:
            pass

    # Create new customer
    customer = s.Customer.create(
        email=company.email,
        name=company.name,
        metadata={
            'company_id': company.id,
            'company_slug': company.slug,
        }
    )

    company.stripe_customer_id = customer.id
    db.session.commit()

    return customer


@bp.route('/checkout/<plan>/<billing_cycle>')
@login_required
@admin_required
def checkout(plan, billing_cycle):
    """Create a Stripe Checkout session and redirect."""
    if plan not in ['pro', 'business']:
        flash('Plan invalide.', 'error')
        return redirect(url_for('admin.subscription'))

    if billing_cycle not in ['monthly', 'yearly']:
        flash('Cycle de facturation invalide.', 'error')
        return redirect(url_for('admin.subscription'))

    price_id = get_price_id(plan, billing_cycle)
    if not price_id:
        flash('Configuration de prix manquante. Contactez le support.', 'error')
        return redirect(url_for('admin.subscription'))

    company = current_user.company
    s = get_stripe()

    try:
        # Get or create customer
        customer = get_or_create_stripe_customer(company)

        # Create checkout session
        checkout_session = s.checkout.Session.create(
            customer=customer.id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=url_for('billing.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('admin.subscription', _external=True),
            metadata={
                'company_id': company.id,
                'plan': plan,
                'billing_cycle': billing_cycle,
            },
            subscription_data={
                'metadata': {
                    'company_id': company.id,
                    'plan': plan,
                }
            },
            allow_promotion_codes=True,
        )

        return redirect(checkout_session.url, code=303)

    except Exception as e:
        current_app.logger.error(f'Stripe checkout error: {e}')
        flash('Erreur lors de la création du paiement. Veuillez réessayer.', 'error')
        return redirect(url_for('admin.subscription'))


@bp.route('/success')
@login_required
def success():
    """Handle successful checkout."""
    session_id = request.args.get('session_id')

    if session_id:
        s = get_stripe()
        try:
            session = s.checkout.Session.retrieve(session_id)
            # The webhook will handle the actual plan update
            flash('Paiement réussi ! Votre abonnement est maintenant actif.', 'success')
        except Exception as e:
            current_app.logger.error(f'Error retrieving session: {e}')

    return redirect(url_for('admin.subscription'))


@bp.route('/portal')
@login_required
@admin_required
def portal():
    """Redirect to Stripe Customer Portal for subscription management."""
    company = current_user.company

    if not company.stripe_customer_id:
        flash('Aucun abonnement actif.', 'error')
        return redirect(url_for('admin.subscription'))

    s = get_stripe()

    try:
        portal_session = s.billing_portal.Session.create(
            customer=company.stripe_customer_id,
            return_url=url_for('admin.subscription', _external=True),
        )
        return redirect(portal_session.url, code=303)

    except Exception as e:
        current_app.logger.error(f'Stripe portal error: {e}')
        flash('Erreur lors de l\'accès au portail de facturation.', 'error')
        return redirect(url_for('admin.subscription'))


@bp.route('/webhook', methods=['POST'])
@csrf.exempt
def webhook():
    """Handle Stripe webhooks."""
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')

    s = get_stripe()

    try:
        event = s.Webhook.construct_event(payload, sig_header, webhook_secret)
    except ValueError:
        current_app.logger.error('Invalid webhook payload')
        return jsonify({'error': 'Invalid payload'}), 400
    except s.error.SignatureVerificationError:
        current_app.logger.error('Invalid webhook signature')
        return jsonify({'error': 'Invalid signature'}), 400

    # Handle events
    event_type = event['type']
    data = event['data']['object']

    current_app.logger.info(f'Stripe webhook received: {event_type}')

    if event_type == 'checkout.session.completed':
        handle_checkout_completed(data)

    elif event_type == 'customer.subscription.created':
        handle_subscription_created(data)

    elif event_type == 'customer.subscription.updated':
        handle_subscription_updated(data)

    elif event_type == 'customer.subscription.deleted':
        handle_subscription_deleted(data)

    elif event_type == 'invoice.payment_succeeded':
        handle_invoice_paid(data)

    elif event_type == 'invoice.payment_failed':
        handle_invoice_failed(data)

    return jsonify({'status': 'success'}), 200


def handle_checkout_completed(session):
    """Handle successful checkout session."""
    company_id = session.get('metadata', {}).get('company_id')
    if not company_id:
        return

    company = Company.query.get(int(company_id))
    if not company:
        return

    plan = session.get('metadata', {}).get('plan')
    billing_cycle = session.get('metadata', {}).get('billing_cycle', 'monthly')
    subscription_id = session.get('subscription')

    if plan and plan in ['pro', 'business']:
        company.plan = plan
        company.max_employees = Company.PLAN_LIMITS.get(plan, 5)
        company.billing_cycle = billing_cycle

    if subscription_id:
        company.stripe_subscription_id = subscription_id
        company.stripe_subscription_status = 'active'

    db.session.commit()
    current_app.logger.info(f'Company {company.id} upgraded to {plan}')


def handle_subscription_created(subscription):
    """Handle new subscription."""
    customer_id = subscription.get('customer')
    company = Company.query.filter_by(stripe_customer_id=customer_id).first()

    if not company:
        return

    company.stripe_subscription_id = subscription['id']
    company.stripe_subscription_status = subscription['status']

    # Get plan from metadata
    plan = subscription.get('metadata', {}).get('plan')
    if plan and plan in ['pro', 'business']:
        company.plan = plan
        company.max_employees = Company.PLAN_LIMITS.get(plan, 5)

    # Set subscription end date
    current_period_end = subscription.get('current_period_end')
    if current_period_end:
        company.subscription_ends_at = datetime.fromtimestamp(current_period_end)

    db.session.commit()


def handle_subscription_updated(subscription):
    """Handle subscription updates (plan change, renewal, etc.)."""
    customer_id = subscription.get('customer')
    company = Company.query.filter_by(stripe_customer_id=customer_id).first()

    if not company:
        return

    company.stripe_subscription_status = subscription['status']

    # Update subscription end date
    current_period_end = subscription.get('current_period_end')
    if current_period_end:
        company.subscription_ends_at = datetime.fromtimestamp(current_period_end)

    # Check if plan changed
    items = subscription.get('items', {}).get('data', [])
    if items:
        price_id = items[0].get('price', {}).get('id')
        # Map price ID back to plan
        new_plan = get_plan_from_price_id(price_id)
        if new_plan and new_plan != company.plan:
            company.plan = new_plan
            company.max_employees = Company.PLAN_LIMITS.get(new_plan, 5)
            current_app.logger.info(f'Company {company.id} plan changed to {new_plan}')

    db.session.commit()


def handle_subscription_deleted(subscription):
    """Handle subscription cancellation."""
    customer_id = subscription.get('customer')
    company = Company.query.filter_by(stripe_customer_id=customer_id).first()

    if not company:
        return

    company.stripe_subscription_status = 'canceled'
    company.stripe_subscription_id = None

    # Downgrade to free plan
    company.plan = 'free'
    company.max_employees = Company.PLAN_LIMITS.get('free', 5)

    db.session.commit()
    current_app.logger.info(f'Company {company.id} subscription canceled, downgraded to free')


def handle_invoice_paid(invoice):
    """Handle successful invoice payment."""
    customer_id = invoice.get('customer')
    company = Company.query.filter_by(stripe_customer_id=customer_id).first()

    if not company:
        return

    # Subscription is in good standing
    if company.stripe_subscription_status == 'past_due':
        company.stripe_subscription_status = 'active'
        db.session.commit()


def handle_invoice_failed(invoice):
    """Handle failed invoice payment."""
    customer_id = invoice.get('customer')
    company = Company.query.filter_by(stripe_customer_id=customer_id).first()

    if not company:
        return

    company.stripe_subscription_status = 'past_due'
    db.session.commit()

    # TODO: Send email notification about failed payment
    current_app.logger.warning(f'Payment failed for company {company.id}')


def get_plan_from_price_id(price_id):
    """Map Stripe price ID back to plan name."""
    if not price_id:
        return None

    config = current_app.config
    price_to_plan = {
        config.get('STRIPE_PRICE_PRO_MONTHLY'): 'pro',
        config.get('STRIPE_PRICE_PRO_YEARLY'): 'pro',
        config.get('STRIPE_PRICE_BUSINESS_MONTHLY'): 'business',
        config.get('STRIPE_PRICE_BUSINESS_YEARLY'): 'business',
    }
    return price_to_plan.get(price_id)
