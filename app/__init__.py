from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
mail = Mail()
migrate = Migrate()
csrf = CSRFProtect()

login_manager.login_view = 'auth.login'
login_manager.login_message = 'Veuillez vous connecter pour accéder à cette page.'
login_manager.login_message_category = 'info'


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from app.routes import auth, main, employee, manager, admin, admin_advanced, api, marketing, slack, root, billing
    app.register_blueprint(marketing.bp)  # Marketing pages (homepage, signup, etc.)
    app.register_blueprint(auth.bp)
    app.register_blueprint(main.bp)
    app.register_blueprint(employee.bp)
    app.register_blueprint(manager.bp)
    app.register_blueprint(admin.bp)
    app.register_blueprint(admin_advanced.bp)  # Advanced admin features
    app.register_blueprint(api.bp)
    app.register_blueprint(slack.bp)
    app.register_blueprint(root.bp)  # Superadmin platform management
    app.register_blueprint(billing.bp)  # Stripe billing

    # Exempt webhooks from CSRF
    csrf.exempt(slack.bp)  # Slack uses signature verification
    csrf.exempt(billing.bp)  # Stripe uses signature verification

    return app
