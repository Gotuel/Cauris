from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db, mail
from app.models import Account, Category, ExchangeRate, RecurringRule, Transaction, User
from app.auth.services import hash_password, verify_password
from app.services.finance import (
    FinanceError,
    account_balance,
    create_transfer,
    get_exchange_rate,
    parse_amount,
)
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
                base_currency_code="XAF",
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


def test_finance_forms_use_compiled_english_translations():
    app = create_app("testing")
    client = app.test_client()
    _create_logged_in_user(app, client)
    response = client.post(
        "/auth/profile",
        data={
            "username": "Finance",
            "locale": "en",
            "base_currency": "XAF",
            "theme": "system",
        },
    )
    assert response.status_code == 302

    response = client.get("/transactions/new")
    assert response.status_code == 200
    assert b"Amount" in response.data
    assert b"Receipt (PNG, JPEG, WebP or PDF)" in response.data
    assert b"Income" in response.data


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


def _create_logged_in_user(app, client, email="finance@example.com", currency="XAF"):
    with app.app_context():
        user = User(
            email=email,
            username="Finance",
            password_hash=hash_password("FinancePassword12!"),
            base_currency=currency,
            email_confirmed=True,
        )
        db.session.add(user)
        db.session.commit()
        user_id = user.id
    response = client.post(
        "/auth/login",
        data={"email": email, "password": "FinancePassword12!"},
    )
    assert response.status_code == 302
    return user_id


def test_amounts_respect_currency_minor_units_and_xaf_euro_parity():
    app = create_app("testing")
    with app.app_context():
        assert parse_amount("1250", "XAF") == 1250
        assert parse_amount("12.50", "EUR") == 1250
        with pytest.raises(FinanceError, match="décimale"):
            parse_amount("12.5", "XAF")
        with pytest.raises(FinanceError, match="supérieur"):
            parse_amount("0", "EUR")
        assert get_exchange_rate("XAF", "XOF") == Decimal("1")
        assert get_exchange_rate("EUR", "XAF") == Decimal("655.957")
        assert get_exchange_rate("XAF", "EUR") == Decimal("1") / Decimal("655.957")


def test_account_crud_listing_and_balance_calculation():
    app = create_app("testing")
    client = app.test_client()
    user_id = _create_logged_in_user(app, client)

    response = client.post(
        "/accounts/new",
        data={
            "name": "Wallet",
            "type": "cash",
            "currency_code": "XAF",
            "initial_balance": "10000",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        account = db.session.scalar(
            db.select(Account).where(Account.user_id == user_id, Account.name == "Wallet")
        )
        assert account.initial_balance == 10000
        db.session.add(
            Transaction(
                user_id=user_id,
                account_id=account.id,
                type="income",
                amount=5000,
                currency_code="XAF",
                base_currency_code="XAF",
                fx_rate_to_base=Decimal("1"),
                amount_in_base=5000,
            )
        )
        db.session.add(
            Transaction(
                user_id=user_id,
                account_id=account.id,
                type="expense",
                amount=1250,
                currency_code="XAF",
                base_currency_code="XAF",
                fx_rate_to_base=Decimal("1"),
                amount_in_base=1250,
            )
        )
        db.session.commit()
        assert account_balance(account) == 13750

    listing = client.get("/accounts/")
    assert listing.status_code == 200
    assert b"Wallet" in listing.data
    assert b"13" in listing.data

    account_id = account.id
    archive = client.post(f"/accounts/{account_id}/archive")
    assert archive.status_code == 302
    with app.app_context():
        assert db.session.get(Account, account_id).is_archived is True
    restore = client.post(f"/accounts/{account_id}/restore")
    assert restore.status_code == 302
    assert client.get(f"/accounts/{account_id + 1000}/edit").status_code == 404


def test_transaction_htmx_create_edit_delete_and_user_isolation():
    app = create_app("testing")
    client = app.test_client()
    user_id = _create_logged_in_user(app, client)
    with app.app_context():
        account = Account(
            user_id=user_id,
            name="Cash",
            type="cash",
            currency_code="XAF",
            initial_balance=10000,
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id
        other_user = User(
            email="other@example.com",
            username="Other",
            password_hash=hash_password("OtherPassword12!"),
            email_confirmed=True,
        )
        other_account = Account(
            name="Other cash", type="cash", currency_code="XAF"
        )
        other_user.accounts.append(other_account)
        other_user.transactions.append(
            Transaction(
                account=other_account,
                type="expense",
                amount=300,
                currency_code="XAF",
                base_currency_code="XAF",
                fx_rate_to_base=Decimal("1"),
                amount_in_base=300,
                note="PRIVATEWORD",
            )
        )
        db.session.add(other_user)
        db.session.commit()

    listing = client.get("/transactions/")
    assert listing.status_code == 200
    response = client.post(
        "/transactions/new",
        headers={"HX-Request": "true"},
        data={
            "account_id": str(account_id),
            "type": "expense",
            "amount": "2500",
            "category_id": "0",
            "occurred_on": "2026-10-06",
            "note": "Local market",
            "tags": "food, weekly",
        },
    )
    assert response.status_code == 200
    assert b"Local market" in response.data
    with app.app_context():
        transaction = db.session.scalar(
            db.select(Transaction).where(
                Transaction.user_id == user_id, Transaction.note == "Local market"
            )
        )
        assert transaction.amount == 2500
        transaction_id = transaction.id

    visible = client.get("/transactions/?search=Local")
    assert b"Local market" in visible.data
    assert b"PRIVATEWORD" not in visible.data
    assert client.get(f"/transactions/{transaction_id}/edit", headers={"HX-Request": "true"}).status_code == 200

    edit = client.post(
        f"/transactions/{transaction_id}/edit",
        headers={"HX-Request": "true"},
        data={
            "account_id": str(account_id),
            "type": "expense",
            "amount": "3000",
            "category_id": "0",
            "occurred_on": "2026-10-06",
            "note": "Edited market",
            "tags": "food",
        },
    )
    assert edit.status_code == 200
    assert b"Edited market" in edit.data
    deleted = client.post(
        f"/transactions/{transaction_id}/delete",
        headers={"HX-Request": "true"},
    )
    assert deleted.status_code == 200
    assert deleted.data == b""
    with app.app_context():
        assert db.session.get(Transaction, transaction_id) is None


def test_transfer_is_atomic_converts_currencies_and_deletes_both_legs():
    app = create_app("testing")
    client = app.test_client()
    user_id = _create_logged_in_user(app, client)
    with app.app_context():
        user = db.session.get(User, user_id)
        source = Account(
            user_id=user_id,
            name="XAF wallet",
            type="cash",
            currency_code="XAF",
            initial_balance=1_000_000,
        )
        destination = Account(
            user_id=user_id,
            name="Euro savings",
            type="savings",
            currency_code="EUR",
        )
        db.session.add_all([source, destination])
        db.session.commit()
        source_id = source.id
        destination_id = destination.id

        outgoing, incoming = create_transfer(
            user,
            source_id,
            destination_id,
            "655957",
            date(2026, 10, 6),
            "Savings move",
            "",
        )
        assert outgoing.transfer_group_id == incoming.transfer_group_id
        assert outgoing.amount == 655957
        assert incoming.amount == 100000
        assert outgoing.base_currency_code == "XAF"
        assert incoming.base_currency_code == "XAF"
        assert outgoing.amount_in_base == incoming.amount_in_base == 655957
        assert account_balance(source) == 344043
        assert account_balance(destination) == 100000
        group = outgoing.transfer_group_id
        assert db.session.scalar(
            db.select(db.func.count(Transaction.id)).where(
                Transaction.transfer_group_id == group
            )
        ) == 2
        user.base_currency = "EUR"
        db.session.commit()
        assert outgoing.base_currency_code == "XAF"
        assert outgoing.amount_in_base == 655957
        user.base_currency = "XAF"
        db.session.commit()

        with pytest.raises(FinanceError):
            create_transfer(
                user,
                source_id,
                source_id,
                "100",
                date(2026, 10, 6),
                "",
                "",
            )
        db.session.rollback()
        assert db.session.scalar(
            db.select(db.func.count(Transaction.id)).where(
                Transaction.transfer_group_id == group
            )
        ) == 2
        outgoing_id = outgoing.id

    removed = client.post(f"/transactions/{outgoing_id}/delete")
    assert removed.status_code == 302
    with app.app_context():
        assert db.session.scalar(
            db.select(db.func.count(Transaction.id)).where(
                Transaction.transfer_group_id == group
            )
        ) == 0

    created = client.post(
        "/transactions/transfer",
        headers={"HX-Request": "true"},
        data={
            "source_account_id": str(source_id),
            "destination_account_id": str(destination_id),
            "source_amount": "655957",
            "occurred_on": "2026-10-06",
            "note": "HTMX move",
        },
    )
    assert created.status_code == 200
    assert created.data.count(b"HTMX move") == 2
    with app.app_context():
        htmx_group = db.session.scalar(
            db.select(Transaction.transfer_group_id).where(
                Transaction.user_id == user_id,
                Transaction.note == "HTMX move",
            )
        )
        htmx_ids = list(
            db.session.scalars(
                db.select(Transaction.id).where(
                    Transaction.transfer_group_id == htmx_group
                )
            )
        )
    removed_htmx = client.post(
        f"/transactions/{htmx_ids[0]}/delete",
        headers={"HX-Request": "true"},
    )
    assert removed_htmx.status_code == 200
    assert b"caurisTransferDeleted" in removed_htmx.headers["HX-Trigger-After-Swap"].encode()
    with app.app_context():
        assert db.session.scalar(
            db.select(db.func.count(Transaction.id)).where(
                Transaction.transfer_group_id == htmx_group
            )
        ) == 0


def test_custom_subcategory_archiving_and_category_ownership():
    app = create_app("testing")
    client = app.test_client()
    user_id = _create_logged_in_user(app, client)
    with app.app_context():
        parent = db.session.scalar(
            db.select(Category).where(Category.user_id.is_(None), Category.key == "food")
        )
        parent_id = parent.id
    response = client.post(
        "/transactions/categories",
        data={
            "key": "market_food",
            "custom_name": "Marché",
            "type": "expense",
            "parent_id": str(parent_id),
            "icon": "🛒",
            "color": "#123456",
        },
    )
    assert response.status_code == 302
    with app.app_context():
        category = db.session.scalar(
            db.select(Category).where(Category.user_id == user_id, Category.key == "market_food")
        )
        assert category.parent_id == parent_id
        category_id = category.id
        account = Account(
            user_id=user_id, name="Category test", type="cash", currency_code="XAF"
        )
        db.session.add(account)
        db.session.flush()
        db.session.add_all(
            [
                Transaction(
                    user_id=user_id,
                    account_id=account.id,
                    category_id=category_id,
                    type="expense",
                    amount=100,
                    currency_code="XAF",
                    base_currency_code="XAF",
                    fx_rate_to_base=Decimal("1"),
                    amount_in_base=100,
                    note="Market transaction",
                ),
                Transaction(
                    user_id=user_id,
                    account_id=account.id,
                    type="expense",
                    amount=200,
                    currency_code="XAF",
                    base_currency_code="XAF",
                    fx_rate_to_base=Decimal("1"),
                    amount_in_base=200,
                    note="Unrelated transaction",
                ),
            ]
        )
        db.session.commit()
    assert client.post(f"/transactions/categories/{category_id}/archive").status_code == 302
    with app.app_context():
        assert db.session.get(Category, category_id).is_archived is True
        assert db.session.scalar(
            db.select(Category).where(
                Category.id == category_id, Category.is_archived.is_(False)
            )
        ) is None
    filtered = client.get(f"/transactions/?category_id={category_id}")
    assert b"Market transaction" in filtered.data
    assert b"Unrelated transaction" not in filtered.data

    with app.app_context():
        other = User(
            email="category-owner@example.com",
            username="Other",
            password_hash=hash_password("OtherPassword12!"),
            email_confirmed=True,
        )
        db.session.add(other)
        db.session.commit()
    other_client = app.test_client()
    other_client.post(
        "/auth/login",
        data={
            "email": "category-owner@example.com",
            "password": "OtherPassword12!",
        },
    )
    assert other_client.post(
        f"/transactions/categories/{category_id}/restore"
    ).status_code == 404


def test_attachment_upload_is_validated_and_private(tmp_path):
    app = create_app("testing")
    app.config["UPLOAD_FOLDER"] = str(tmp_path)
    client = app.test_client()
    user_id = _create_logged_in_user(app, client)
    with app.app_context():
        account = Account(
            user_id=user_id, name="Wallet", type="cash", currency_code="XAF"
        )
        db.session.add(account)
        db.session.commit()
        account_id = account.id

    import io

    response = client.post(
        "/transactions/new",
        headers={"HX-Request": "true"},
        data={
            "account_id": str(account_id),
            "type": "expense",
            "amount": "500",
            "occurred_on": "2026-10-06",
            "attachment": (io.BytesIO(b"not a pdf"), "receipt.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert b"ne correspond pas" in response.data
    with app.app_context():
        assert db.session.scalar(db.select(Transaction)) is None

    response = client.post(
        "/transactions/new",
        headers={"HX-Request": "true"},
        data={
            "account_id": str(account_id),
            "type": "expense",
            "amount": "500",
            "occurred_on": "2026-10-06",
            "attachment": (io.BytesIO(b"\x89PNG\r\n\x1a\nimage-data"), "receipt.png"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    with app.app_context():
        transaction = db.session.scalar(
            db.select(Transaction).where(Transaction.user_id == user_id)
        )
        transaction_id = transaction.id
        assert transaction.attachment_path
    download = client.get(f"/transactions/attachment/{transaction_id}")
    assert download.status_code == 200
    assert download.data.startswith(b"\x89PNG\r\n\x1a\n")

    with app.app_context():
        other = User(
            email="receipt-owner@example.com",
            username="Receipt",
            password_hash=hash_password("ReceiptPassword12!"),
            email_confirmed=True,
        )
        db.session.add(other)
        db.session.commit()
    other_client = app.test_client()
    other_client.post(
        "/auth/login",
        data={
            "email": "receipt-owner@example.com",
            "password": "ReceiptPassword12!",
        },
    )
    assert other_client.get(
        f"/transactions/attachment/{transaction_id}"
    ).status_code == 404


def test_exchange_rate_uses_cached_rate_when_provider_is_unavailable(monkeypatch):
    app = create_app("testing")
    with app.app_context():
        db.session.add(
            ExchangeRate(
                base_currency="USD",
                quote_currency="EUR",
                rate=Decimal("0.92"),
                date=date(2026, 10, 5),
                source="test",
            )
        )
        db.session.commit()

        def unavailable(base, quote):
            raise FinanceError("provider offline")

        monkeypatch.setattr("app.services.finance._fetch_rate", unavailable)
        assert get_exchange_rate("USD", "EUR") == Decimal("0.92")
