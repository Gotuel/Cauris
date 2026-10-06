from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db, mail
from app.models import Account, RecurringRule, Transaction, User
from app.auth.services import hash_password, verify_password
from config import config_by_name


def test_app_factory_creates_app():
    app = create_app("testing")
    assert app is not None
    assert app.config["TESTING"] is True


def test_home_route_works():
    app = create_app("testing")
    client = app.test_client()
    response = client.get("/")
    assert response.status_code == 200


def test_register_confirm_and_login():
    app = create_app("testing")
    client = app.test_client()

    with mail.record_messages() as outbox:
        response = client.post(
            "/auth/register",
            data={
                "username": "Awa",
                "email": "Awa@example.com",
                "password": "CorrectHorse12!",
                "confirm_password": "CorrectHorse12!",
                "locale": "fr",
                "base_currency": "XAF",
            },
        )
        assert response.status_code == 302
        assert len(outbox) == 1
        confirm_url = outbox[0].body.splitlines()[3]
        confirmation = client.get(confirm_url)

    assert confirmation.status_code == 302
    login = client.post(
        "/auth/login",
        data={"email": "awa@example.com", "password": "CorrectHorse12!"},
    )
    assert login.status_code == 302
    assert client.get("/auth/profile").status_code == 200

    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "awa@example.com"))
        assert user is not None
        assert user.email_confirmed is True
        assert user.base_currency == "XAF"
        assert user.locale == "fr"


def test_profile_change_password_and_delete_account():
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        user = User(
            email="profile@example.com",
            username="Profile",
            password_hash=hash_password("OriginalPassword12!"),
            email_confirmed=True,
        )
        account = Account(name="Wallet", type="cash", currency_code="XAF")
        user.accounts.append(account)
        user.transactions.append(
            Transaction(
                account=account,
                type="expense",
                amount=100,
                currency_code="XAF",
                fx_rate_to_base=Decimal("1"),
                amount_in_base=100,
            )
        )
        user.recurring_rules.append(
            RecurringRule(
                name="Rent",
                frequency="monthly",
                next_occurrence=datetime.now(timezone.utc).replace(tzinfo=None)
                + timedelta(days=30),
            )
        )
        db.session.add(user)
        db.session.commit()

    client.post(
        "/auth/login",
        data={"email": "profile@example.com", "password": "OriginalPassword12!"},
    )
    response = client.post(
        "/auth/profile",
        data={
            "username": "Profil mis à jour",
            "locale": "en",
            "base_currency": "EUR",
            "theme": "dark",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "profile@example.com"))
        assert (user.username, user.locale, user.base_currency, user.theme) == (
            "Profil mis à jour",
            "en",
            "EUR",
            "dark",
        )
    profile_page = client.get("/auth/profile")
    assert b"Profile preferences" in profile_page.data
    assert b'lang="en"' in profile_page.data

    response = client.post(
        "/auth/change-password",
        data={
            "current_password": "OriginalPassword12!",
            "password": "NewPassword123!",
            "confirm_password": "NewPassword123!",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "profile@example.com"))
        assert verify_password(user.password_hash, "NewPassword123!")

    response = client.post(
        "/auth/delete-account",
        data={"password": "NewPassword123!"},
    )
    assert response.status_code == 302
    with app.app_context():
        assert db.session.scalar(
            db.select(User).where(User.email == "profile@example.com")
        ) is None
        assert db.session.scalar(db.select(Account).where(Account.name == "Wallet")) is None
        assert db.session.scalar(
            db.select(Transaction).where(Transaction.type == "expense")
        ) is None
        assert db.session.scalar(
            db.select(RecurringRule).where(RecurringRule.name == "Rent")
        ) is None


def test_password_reset_token_is_single_use():
    app = create_app("testing")
    client = app.test_client()
    with app.app_context():
        user = User(
            email="reset@example.com",
            username="Reset",
            password_hash=hash_password("OriginalPassword12!"),
            email_confirmed=True,
        )
        db.session.add(user)
        db.session.commit()

    with mail.record_messages() as outbox:
        response = client.post(
            "/auth/password-reset",
            data={"email": "reset@example.com"},
        )
        assert response.status_code == 302
        reset_url = outbox[0].body.splitlines()[3]
        reset = client.post(
            reset_url,
            data={
                "password": "ReplacementPassword12!",
                "confirm_password": "ReplacementPassword12!",
            },
        )
    assert reset.status_code == 302
    assert client.get(reset_url).status_code == 302


def test_login_locks_account_after_configured_failures():
    app = create_app("testing")
    app.config["LOGIN_MAX_ATTEMPTS"] = 2
    client = app.test_client()
    with app.app_context():
        user = User(
            email="lock@example.com",
            username="Lock",
            password_hash=hash_password("CorrectPassword12!"),
            email_confirmed=True,
        )
        db.session.add(user)
        db.session.commit()

    for _ in range(2):
        response = client.post(
            "/auth/login",
            data={"email": "lock@example.com", "password": "wrong password"},
        )
        assert response.status_code == 200
    with app.app_context():
        user = db.session.scalar(db.select(User).where(User.email == "lock@example.com"))
        assert user.login_locked_until is not None


def test_csrf_protection_rejects_post_without_a_token():
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    response = app.test_client().post(
        "/auth/login",
        data={"email": "user@example.com", "password": "some password"},
    )
    assert response.status_code == 400


def test_english_locale_translates_public_error_pages():
    app = create_app("testing")
    client = app.test_client()
    with client.session_transaction() as client_session:
        client_session["locale"] = "en"

    response = client.get("/missing-page")
    assert response.status_code == 404
    assert b"Page not found" in response.data
    assert b'This page does not exist.' in response.data


def test_production_requires_an_explicit_secret_key(monkeypatch):
    monkeypatch.setattr(config_by_name["production"], "SECRET_KEY", None)
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")
