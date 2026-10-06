import os

from flask import Flask, current_app, render_template, request, session
from flask_login import current_user
from flask_babel import get_locale, gettext, ngettext

from config import config_by_name
from .extensions import babel, csrf, db, login_manager, mail, migrate, scheduler


def select_locale() -> str:
    if current_user.is_authenticated:
        return current_user.locale
    return (
        session.get("locale")
        or request.accept_languages.best_match(current_app.config["LANGUAGES"])
        or current_app.config["DEFAULT_LOCALE"]
    )


def _register_blueprints(app: Flask) -> None:
    from .accounts import accounts_bp
    from .auth import auth_bp
    from .budgets import budgets_bp
    from .dashboard import dashboard_bp
    from .debts import debts_bp
    from .goals import goals_bp
    from .main import main_bp
    from .reports import reports_bp
    from .transactions import transactions_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(accounts_bp, url_prefix="/accounts")
    app.register_blueprint(transactions_bp, url_prefix="/transactions")
    app.register_blueprint(budgets_bp, url_prefix="/budgets")
    app.register_blueprint(goals_bp, url_prefix="/goals")
    app.register_blueprint(debts_bp, url_prefix="/debts")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(reports_bp, url_prefix="/reports")


def _seed_initial_data() -> None:
    from .models import Category, Currency

    default_currencies = [
        ("XAF", "CFA Franc BEAC", "FCFA", 0),
        ("XOF", "CFA Franc BCEAO", "CFA", 0),
        ("EUR", "Euro", "€", 2),
        ("USD", "US Dollar", "$", 2),
        ("GBP", "Pound Sterling", "£", 2),
        ("MAD", "Moroccan Dirham", "MAD", 2),
        ("DZD", "Algerian Dinar", "DZD", 2),
        ("TND", "Tunisian Dinar", "TND", 3),
        ("NGN", "Nigerian Naira", "₦", 2),
        ("GHS", "Ghanaian Cedi", "₵", 2),
        ("CDF", "Congolese Franc", "FC", 2),
        ("RWF", "Rwandan Franc", "FRw", 0),
        ("KES", "Kenyan Shilling", "KSh", 2),
        ("ZAR", "South African Rand", "R", 2),
        ("CAD", "Canadian Dollar", "C$", 2),
        ("CHF", "Swiss Franc", "CHF", 2),
    ]

    for code, name, symbol, minor_unit in default_currencies:
        if not Currency.query.filter_by(code=code).first():
            db.session.add(Currency(code=code, name=name, symbol=symbol, minor_unit=minor_unit))

    system_categories = [
        ("food", "expense", "Alimentation", "🍲", "#f59e0b"),
        ("housing", "expense", "Logement", "🏠", "#3b82f6"),
        ("transport", "expense", "Transport", "🚗", "#8b5cf6"),
        ("health", "expense", "Santé", "💊", "#10b981"),
        ("education", "expense", "Éducation", "📚", "#f97316"),
        ("salary", "income", "Salaire", "💰", "#14b8a6"),
        ("freelance", "income", "Freelance", "💼", "#22c55e"),
        ("gifts", "income", "Cadeaux", "🎁", "#ec4899"),
    ]

    for key, category_type, fallback_name, icon, color in system_categories:
        if not Category.query.filter_by(key=key, user_id=None).first():
            db.session.add(
                Category(
                    user_id=None,
                    key=key,
                    custom_name=fallback_name,
                    type=category_type,
                    icon=icon,
                    color=color,
                )
            )

    db.session.commit()


def create_app(config_name: str | None = None) -> Flask:
    app = Flask(__name__)
    config_name = config_name or os.getenv("FLASK_ENV", "development")
    app.config.from_object(config_by_name[config_name])
    if config_name == "production" and not app.config.get("SECRET_KEY"):
        raise RuntimeError("Set SECRET_KEY in the production environment before starting Cauris.")

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    babel.init_app(app, locale_selector=select_locale)
    app.jinja_env.globals.update(
        {"get_locale": get_locale, "gettext": gettext, "ngettext": ngettext, "_": gettext}
    )
    mail.init_app(app)
    csrf.init_app(app)
    if not scheduler.running:
        scheduler.init_app(app)
        scheduler.start()

    _register_blueprints(app)

    from .models import Account, AuditLog, Budget, Category, Currency, Debt, DebtPayment, ExchangeRate, Goal, RecurringRule, Transaction, User

    @app.errorhandler(404)
    def page_not_found(error):
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(error):
        return render_template("errors/500.html"), 500

    with app.app_context():
        db.create_all()
        _seed_initial_data()

    return app
