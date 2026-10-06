from datetime import datetime, timezone

from flask_login import UserMixin

from app.extensions import db


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    username = db.Column(db.String(80), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    locale = db.Column(db.String(10), nullable=False, default="fr")
    base_currency = db.Column(db.String(10), nullable=False, default="XAF")
    theme = db.Column(db.String(20), nullable=False, default="system")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    email_confirmed = db.Column(db.Boolean, nullable=False, default=False)
    totp_secret = db.Column(db.String(64), nullable=True)
    failed_login_attempts = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    login_locked_until = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=_utcnow_naive, nullable=False)

    accounts = db.relationship("Account", back_populates="user", cascade="all, delete-orphan")
    categories = db.relationship("Category", back_populates="user", cascade="all, delete-orphan")
    transactions = db.relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    recurring_rules = db.relationship("RecurringRule", back_populates="user", cascade="all, delete-orphan")
    budgets = db.relationship("Budget", back_populates="user", cascade="all, delete-orphan")
    goals = db.relationship("Goal", back_populates="user", cascade="all, delete-orphan")
    debts = db.relationship("Debt", back_populates="user", cascade="all, delete-orphan")
    audit_logs = db.relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")


class Currency(db.Model):
    __tablename__ = "currencies"

    code = db.Column(db.String(10), primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    minor_unit = db.Column(db.Integer, nullable=False, default=2)

    accounts = db.relationship("Account", back_populates="currency")
    exchange_rates_base = db.relationship("ExchangeRate", foreign_keys="ExchangeRate.base_currency", back_populates="base_currency_obj")
    exchange_rates_quote = db.relationship("ExchangeRate", foreign_keys="ExchangeRate.quote_currency", back_populates="quote_currency_obj")


class ExchangeRate(db.Model):
    __tablename__ = "exchange_rates"

    id = db.Column(db.Integer, primary_key=True)
    base_currency = db.Column(db.String(10), db.ForeignKey("currencies.code"), nullable=False)
    quote_currency = db.Column(db.String(10), db.ForeignKey("currencies.code"), nullable=False)
    rate = db.Column(db.Numeric(20, 10), nullable=False)
    date = db.Column(db.Date, nullable=False)
    source = db.Column(db.String(80), nullable=False, default="api")

    base_currency_obj = db.relationship("Currency", foreign_keys=[base_currency], back_populates="exchange_rates_base")
    quote_currency_obj = db.relationship("Currency", foreign_keys=[quote_currency], back_populates="exchange_rates_quote")


class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    type = db.Column(db.String(30), nullable=False, default="cash")
    currency_code = db.Column(db.String(10), db.ForeignKey("currencies.code"), nullable=False)
    initial_balance = db.Column(db.Integer, nullable=False, default=0)
    is_archived = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User", back_populates="accounts")
    currency = db.relationship("Currency", back_populates="accounts")
    transactions = db.relationship(
        "Transaction", back_populates="account", cascade="all, delete-orphan"
    )


class Category(db.Model):
    __tablename__ = "categories"
    __table_args__ = (
        db.UniqueConstraint("user_id", "key", name="uq_category_user_key"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    key = db.Column(db.String(80), nullable=False)
    custom_name = db.Column(db.String(120), nullable=True)
    type = db.Column(db.String(20), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    icon = db.Column(db.String(50), nullable=True)
    color = db.Column(db.String(20), nullable=True)
    is_archived = db.Column(db.Boolean, nullable=False, default=False, server_default="0")

    user = db.relationship("User", back_populates="categories")
    parent = db.relationship("Category", remote_side="Category.id", backref="children")
    transactions = db.relationship("Transaction", back_populates="category")
    budgets = db.relationship("Budget", back_populates="category")


class RecurringRule(db.Model):
    __tablename__ = "recurring_rules"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    frequency = db.Column(db.String(30), nullable=False)
    next_occurrence = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime, nullable=True)
    description = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="recurring_rules")
    transactions = db.relationship("Transaction", backref="recurring_rule")


class Transaction(db.Model):
    __tablename__ = "transactions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=True)
    type = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    currency_code = db.Column(
        db.String(10),
        db.ForeignKey("currencies.code", name="fk_transaction_currency"),
        nullable=False,
    )
    base_currency_code = db.Column(
        db.String(10),
        db.ForeignKey("currencies.code", name="fk_transaction_base_currency"),
        nullable=False,
    )
    fx_rate_to_base = db.Column(db.Numeric(20, 10), nullable=False)
    amount_in_base = db.Column(db.Integer, nullable=False)
    date = db.Column(db.DateTime, nullable=False, default=_utcnow_naive)
    note = db.Column(db.Text, nullable=True)
    tags = db.Column(db.Text, nullable=True)
    transfer_group_id = db.Column(db.String(80), nullable=True)
    recurring_rule_id = db.Column(db.Integer, db.ForeignKey("recurring_rules.id"), nullable=True)
    attachment_path = db.Column(db.String(255), nullable=True)

    user = db.relationship("User", back_populates="transactions")
    account = db.relationship("Account", back_populates="transactions")
    category = db.relationship("Category", back_populates="transactions")


class Budget(db.Model):
    __tablename__ = "budgets"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("categories.id"), nullable=False)
    month = db.Column(db.String(7), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    alert_80 = db.Column(db.Integer, nullable=False, default=0)
    alert_100 = db.Column(db.Integer, nullable=False, default=0)

    user = db.relationship("User", back_populates="budgets")
    category = db.relationship("Category", back_populates="budgets")


class Goal(db.Model):
    __tablename__ = "goals"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    target_amount = db.Column(db.Integer, nullable=False)
    current_amount = db.Column(db.Integer, nullable=False, default=0)
    due_date = db.Column(db.Date, nullable=True)
    linked_account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=True)

    user = db.relationship("User", back_populates="goals")
    linked_account = db.relationship("Account")


class Debt(db.Model):
    __tablename__ = "debts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    direction = db.Column(db.String(20), nullable=False)
    counterparty = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    schedule = db.Column(db.String(50), nullable=True)
    note = db.Column(db.Text, nullable=True)

    user = db.relationship("User", back_populates="debts")
    payments = db.relationship("DebtPayment", back_populates="debt", cascade="all, delete-orphan")


class DebtPayment(db.Model):
    __tablename__ = "debt_payments"

    id = db.Column(db.Integer, primary_key=True)
    debt_id = db.Column(db.Integer, db.ForeignKey("debts.id"), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    paid_at = db.Column(db.DateTime, nullable=False, default=_utcnow_naive)
    note = db.Column(db.Text, nullable=True)

    debt = db.relationship("Debt", back_populates="payments")


class AuditLog(db.Model):
    __tablename__ = "audit_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    action = db.Column(db.String(160), nullable=False)
    created_at = db.Column(db.DateTime, default=_utcnow_naive, nullable=False)
    ip_address = db.Column(db.String(45), nullable=True)

    user = db.relationship("User", back_populates="audit_logs")


__all__ = [
    "User",
    "Currency",
    "ExchangeRate",
    "Account",
    "Category",
    "RecurringRule",
    "Transaction",
    "Budget",
    "Goal",
    "Debt",
    "DebtPayment",
    "AuditLog",
]
