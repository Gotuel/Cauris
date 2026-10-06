import json
import logging
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

from flask_babel import get_locale, gettext
from sqlalchemy import func
from babel.numbers import format_currency

from app.extensions import db
from app.models import Account, Category, Currency, ExchangeRate, Transaction, User
from .money import convert_minor_units

logger = logging.getLogger(__name__)
MAX_MINOR_AMOUNT = 9_000_000_000_000_000_000
FIXED_EUR_PARITY = Decimal("655.957")


class FinanceError(ValueError):
    """A validation or business-rule error safe to show to the user."""

    def __init__(self, message: str):
        super().__init__(gettext(message))


def parse_amount(value: str, currency_code: str, *, allow_negative: bool = False) -> int:
    """Parse a major-unit input into an exact integer count of minor units."""
    currency = db.session.get(Currency, currency_code)
    if currency is None:
        raise FinanceError("La devise sélectionnée n’existe pas.")
    try:
        amount = Decimal(value.strip())
    except (AttributeError, InvalidOperation):
        raise FinanceError("Saisissez un montant valide.") from None
    if not amount.is_finite():
        raise FinanceError("Saisissez un montant valide.")
    if not allow_negative and amount <= 0:
        raise FinanceError("Le montant doit être supérieur à zéro.")

    scaled = amount * (Decimal(10) ** currency.minor_unit)
    if scaled != scaled.to_integral_value():
        raise FinanceError(
            gettext(
                "La devise %(currency)s accepte au maximum %(digits)s décimale(s).",
                currency=currency.code,
                digits=currency.minor_unit,
            )
        )
    minor_amount = int(scaled)
    if abs(minor_amount) > MAX_MINOR_AMOUNT:
        raise FinanceError("Le montant dépasse la limite autorisée.")
    return minor_amount


def format_minor_amount(amount: int, currency_code: str, locale: str | None = None) -> str:
    """Format stored minor units for display without converting through float."""
    currency = db.session.get(Currency, currency_code)
    if currency is None:
        raise FinanceError("La devise sélectionnée n’existe pas.")
    major_amount = Decimal(amount) / (Decimal(10) ** currency.minor_unit)
    language = locale or str(get_locale())
    return format_currency(
        major_amount, currency_code, locale=language, currency_digits=True
    )


def amount_input_value(amount: int, currency_code: str) -> str:
    """Return a locale-neutral decimal suitable for pre-filling an amount input."""
    currency = db.session.get(Currency, currency_code)
    if currency is None:
        raise FinanceError("La devise sélectionnée n’existe pas.")
    return format(Decimal(amount).scaleb(-currency.minor_unit), "f")


def _fixed_rate(base: str, quote: str) -> Decimal | None:
    if base == quote:
        return Decimal("1")
    fixed = {"XAF", "XOF"}
    if base in fixed and quote in fixed:
        return Decimal("1")
    if base in fixed and quote == "EUR":
        return Decimal("1") / FIXED_EUR_PARITY
    if base == "EUR" and quote in fixed:
        return FIXED_EUR_PARITY
    return None


def _cached_rate_record(base: str, quote: str) -> tuple[Decimal, date] | None:
    row = db.session.scalar(
        db.select(ExchangeRate)
        .where(
            ExchangeRate.base_currency == base,
            ExchangeRate.quote_currency == quote,
        )
        .order_by(ExchangeRate.date.desc(), ExchangeRate.id.desc())
        .limit(1)
    )
    if row and row.rate > 0:
        return Decimal(row.rate), row.date

    inverse = db.session.scalar(
        db.select(ExchangeRate)
        .where(
            ExchangeRate.base_currency == quote,
            ExchangeRate.quote_currency == base,
        )
        .order_by(ExchangeRate.date.desc(), ExchangeRate.id.desc())
        .limit(1)
    )
    if inverse and inverse.rate > 0:
        return Decimal("1") / Decimal(inverse.rate), inverse.date
    return None


def _fetch_rate(base: str, quote: str) -> Decimal:
    url = f"https://open.er-api.com/v6/latest/{base}"
    try:
        with urlopen(url, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, ValueError) as error:
        raise FinanceError(
            gettext(
                "Aucun taux de change disponible pour %(base)s/%(quote)s. Réessayez plus tard.",
                base=base,
                quote=quote,
            )
        ) from error
    if not isinstance(payload, dict) or payload.get("result") != "success":
        raise FinanceError(
            gettext(
                "Le service de change n’a pas fourni le taux %(base)s/%(quote)s.",
                base=base,
                quote=quote,
            )
        )
    rates = payload.get("rates")
    if not isinstance(rates, dict):
        raise FinanceError(
            gettext(
                "Le service de change n’a pas fourni le taux %(base)s/%(quote)s.",
                base=base,
                quote=quote,
            )
        )
    raw_rate = rates.get(quote)
    try:
        rate = Decimal(str(raw_rate))
    except (InvalidOperation, TypeError):
        raise FinanceError(
            gettext(
                "Le service de change n’a pas fourni le taux %(base)s/%(quote)s.",
                base=base,
                quote=quote,
            )
        ) from None
    if not rate.is_finite() or rate <= 0:
        raise FinanceError(
            gettext(
                "Le service de change a fourni un taux invalide pour %(base)s/%(quote)s.",
                base=base,
                quote=quote,
            )
        )

    rate_date = date.today()
    if payload.get("time_last_update_utc"):
        try:
            rate_date = datetime.strptime(
                payload["time_last_update_utc"], "%a, %d %b %Y %H:%M:%S %z"
            ).date()
        except ValueError:
            logger.warning("Exchange-rate provider returned an unrecognized update date")
    db.session.add(
        ExchangeRate(
            base_currency=base,
            quote_currency=quote,
            rate=rate,
            date=rate_date,
            source="open.er-api.com",
        )
    )
    return rate


def _direct_rate(base: str, quote: str) -> Decimal:
    fixed = _fixed_rate(base, quote)
    if fixed is not None:
        return fixed
    cached = _cached_rate_record(base, quote)
    if cached and cached[1] >= date.today():
        return cached[0]
    try:
        return _fetch_rate(base, quote)
    except FinanceError:
        if cached is not None:
            logger.warning("Using cached exchange rate for %s/%s after provider failure", base, quote)
            return cached[0]
        raise


def get_exchange_rate(base: str, quote: str) -> Decimal:
    """Return quote major units per base major unit, persisting fetched rates."""
    if db.session.get(Currency, base) is None or db.session.get(Currency, quote) is None:
        raise FinanceError("La devise de conversion sélectionnée n’existe pas.")
    if base == quote:
        return Decimal("1")
    fixed = _fixed_rate(base, quote)
    if fixed is not None:
        return fixed
    try:
        return _direct_rate(base, quote)
    except FinanceError as direct_error:
        if base == "EUR" or quote == "EUR":
            raise direct_error
        try:
            return _direct_rate(base, "EUR") * _direct_rate("EUR", quote)
        except FinanceError as cross_error:
            raise FinanceError(
                f"Impossible de convertir {base} vers {quote} : {cross_error}"
            ) from direct_error


def _user_account(user_id: int, account_id: int, *, allow_archived: bool = False) -> Account:
    account = db.session.scalar(
        db.select(Account).where(Account.id == account_id, Account.user_id == user_id)
    )
    if account is None or (account.is_archived and not allow_archived):
        raise FinanceError("Le compte sélectionné est introuvable ou archivé.")
    return account


def _user_category(
    user_id: int,
    category_id: int | None,
    transaction_type: str | None = None,
    *,
    include_archived: bool = False,
) -> Category | None:
    if category_id is None:
        return None
    conditions = [
        Category.id == category_id,
        db.or_(Category.user_id == user_id, Category.user_id.is_(None)),
    ]
    if not include_archived:
        conditions.append(Category.is_archived.is_(False))
    category = db.session.scalar(db.select(Category).where(*conditions))
    if category is None or (transaction_type and category.type != transaction_type):
        raise FinanceError("La catégorie sélectionnée est invalide.")
    return category


def create_account(
    user: User, name: str, account_type: str, currency_code: str, initial_balance: str
) -> Account:
    name = name.strip()
    if not name or len(name) > 120:
        raise FinanceError("Le nom du compte est obligatoire et limité à 120 caractères.")
    if account_type not in {"cash", "bank", "mobile_money", "savings", "card"}:
        raise FinanceError("Le type de compte sélectionné est invalide.")
    if db.session.get(Currency, currency_code) is None:
        raise FinanceError("La devise sélectionnée n’existe pas.")
    account = Account(
        user_id=user.id,
        name=name,
        type=account_type,
        currency_code=currency_code,
        initial_balance=parse_amount(initial_balance, currency_code, allow_negative=True),
    )
    db.session.add(account)
    db.session.commit()
    return account


def update_account(
    user_id: int,
    account_id: int,
    name: str,
    account_type: str,
    currency_code: str,
    initial_balance: str,
) -> Account:
    account = _user_account(user_id, account_id, allow_archived=True)
    name = name.strip()
    if not name or len(name) > 120:
        raise FinanceError("Le nom du compte est obligatoire et limité à 120 caractères.")
    if account_type not in {"cash", "bank", "mobile_money", "savings", "card"}:
        raise FinanceError("Le type de compte sélectionné est invalide.")
    if db.session.get(Currency, currency_code) is None:
        raise FinanceError("La devise sélectionnée n’existe pas.")
    if currency_code != account.currency_code and account.transactions:
        raise FinanceError("La devise ne peut plus être modifiée après l’ajout de transactions.")
    account.name = name
    account.type = account_type
    account.currency_code = currency_code
    account.initial_balance = parse_amount(initial_balance, currency_code, allow_negative=True)
    db.session.commit()
    return account


def set_account_archived(user_id: int, account_id: int, archived: bool) -> Account:
    account = _user_account(user_id, account_id, allow_archived=True)
    account.is_archived = archived
    db.session.commit()
    return account


def account_balance(account: Account) -> int:
    """Calculate a native-currency balance from its opening balance and ledger."""
    total = db.session.scalar(
        db.select(
            func.coalesce(
                func.sum(
                    db.case(
                        (Transaction.type == "income", Transaction.amount),
                        (Transaction.type == "expense", -Transaction.amount),
                        else_=0,
                    )
                ),
                0,
            )
        ).where(
            Transaction.user_id == account.user_id,
            Transaction.account_id == account.id,
        )
    )
    return account.initial_balance + int(total or 0)


def list_categories(user_id: int, *, include_archived: bool = False) -> list[Category]:
    query = db.select(Category).where(
        db.or_(Category.user_id == user_id, Category.user_id.is_(None))
    )
    if not include_archived:
        query = query.where(Category.is_archived.is_(False))
    return list(db.session.scalars(query.order_by(Category.type, Category.key)))


def category_display_name(category: Category) -> str:
    """Return a localized label for built-in categories and the owner label for custom ones."""
    if category.user_id is not None:
        return category.custom_name or category.key
    labels = {
        "food": "Alimentation",
        "housing": "Logement",
        "transport": "Transport",
        "health": "Santé",
        "education": "Éducation",
        "salary": "Salaire",
        "freelance": "Freelance",
        "gifts": "Cadeaux",
    }
    return gettext(labels.get(category.key, category.custom_name or category.key))


def create_category(
    user_id: int,
    key: str,
    name: str,
    category_type: str,
    parent_id: int | None,
    icon: str,
    color: str,
) -> Category:
    key = key.strip().lower()
    name = name.strip()
    if not key or not re.fullmatch(r"[a-z0-9_-]{1,80}", key):
        raise FinanceError("Utilisez une clé de catégorie courte composée de lettres, chiffres, tirets ou tirets bas.")
    if not name or len(name) > 120:
        raise FinanceError("Le nom de la catégorie est obligatoire et limité à 120 caractères.")
    if category_type not in {"income", "expense"}:
        raise FinanceError("Le type de catégorie est invalide.")
    if db.session.scalar(
        db.select(Category).where(Category.user_id == user_id, Category.key == key)
    ):
        raise FinanceError("Vous avez déjà une catégorie avec cette clé.")

    parent = _user_category(user_id, parent_id)
    if parent and parent.type != category_type:
        raise FinanceError("Une sous-catégorie doit avoir le même type que sa catégorie parente.")
    category = Category(
        user_id=user_id,
        key=key,
        custom_name=name,
        type=category_type,
        parent_id=parent.id if parent else None,
        icon=icon.strip()[:50] or None,
        color=color if re.fullmatch(r"#[0-9A-Fa-f]{6}", color) else "#64748b",
    )
    db.session.add(category)
    db.session.commit()
    return category


def set_category_archived(user_id: int, category_id: int, archived: bool) -> Category:
    category = db.session.scalar(
        db.select(Category).where(Category.id == category_id, Category.user_id == user_id)
    )
    if category is None:
        raise FinanceError("La catégorie est introuvable ou ne vous appartient pas.")
    category.is_archived = archived
    db.session.commit()
    return category


def update_category(
    user_id: int,
    category_id: int,
    name: str,
    category_type: str,
    parent_id: int | None,
    icon: str,
    color: str,
) -> Category:
    category = db.session.scalar(
        db.select(Category).where(
            Category.id == category_id,
            Category.user_id == user_id,
        )
    )
    if category is None:
        raise FinanceError("La catégorie est introuvable ou ne vous appartient pas.")
    name = name.strip()
    if not name or len(name) > 120:
        raise FinanceError("Le nom de la catégorie est obligatoire et limité à 120 caractères.")
    if category_type not in {"income", "expense"}:
        raise FinanceError("Le type de catégorie est invalide.")
    parent = _user_category(user_id, parent_id)
    if parent and (parent.id == category.id or parent.type != category_type):
        raise FinanceError("La catégorie parente est invalide.")
    if category_type != category.type and (category.transactions or category.budgets):
        raise FinanceError("Le type ne peut pas changer après l’utilisation de cette catégorie.")
    category.custom_name = name
    category.type = category_type
    category.parent_id = parent.id if parent else None
    category.icon = icon.strip()[:50] or None
    category.color = color if re.fullmatch(r"#[0-9A-Fa-f]{6}", color) else "#64748b"
    db.session.commit()
    return category


def _new_transaction(
    user: User,
    account: Account,
    transaction_type: str,
    amount: int,
    category: Category | None,
    occurred_on: date,
    note: str,
    tags: str,
    transfer_group_id: str | None = None,
) -> Transaction:
    rate = get_exchange_rate(account.currency_code, user.base_currency)
    base_currency = db.session.get(Currency, user.base_currency)
    amount_in_base = convert_minor_units(
        amount, account.currency.minor_unit, base_currency.minor_unit, rate
    )
    return Transaction(
        user_id=user.id,
        account_id=account.id,
        category_id=category.id if category else None,
        type=transaction_type,
        amount=amount,
        currency_code=account.currency_code,
        base_currency_code=user.base_currency,
        fx_rate_to_base=rate,
        amount_in_base=amount_in_base,
        date=datetime.combine(occurred_on, datetime.min.time()),
        note=note.strip()[:2000] or None,
        tags=tags.strip()[:500] or None,
        transfer_group_id=transfer_group_id,
    )


def create_transaction(
    user: User,
    account_id: int,
    transaction_type: str,
    amount_text: str,
    category_id: int | None,
    occurred_on: date,
    note: str,
    tags: str,
    attachment_path: str | None = None,
) -> Transaction:
    if transaction_type not in {"income", "expense"}:
        raise FinanceError("Le type de transaction est invalide.")
    account = _user_account(user.id, account_id)
    category = _user_category(user.id, category_id, transaction_type)
    amount = parse_amount(amount_text, account.currency_code)
    transaction = _new_transaction(
        user, account, transaction_type, amount, category, occurred_on, note, tags
    )
    transaction.attachment_path = attachment_path
    db.session.add(transaction)
    db.session.commit()
    return transaction


def update_transaction(
    user: User,
    transaction_id: int,
    account_id: int,
    transaction_type: str,
    amount_text: str,
    category_id: int | None,
    occurred_on: date,
    note: str,
    tags: str,
    attachment_path: str | None = None,
) -> Transaction:
    transaction = db.session.scalar(
        db.select(Transaction).where(
            Transaction.id == transaction_id, Transaction.user_id == user.id
        )
    )
    if transaction is None:
        raise FinanceError("La transaction est introuvable.")
    if transaction.transfer_group_id:
        raise FinanceError("Un virement ne peut pas être modifié séparément.")
    if transaction_type not in {"income", "expense"}:
        raise FinanceError("Le type de transaction est invalide.")
    account = _user_account(
        user.id,
        account_id,
        allow_archived=account_id == transaction.account_id,
    )
    category = _user_category(user.id, category_id, transaction_type)
    amount = parse_amount(amount_text, account.currency_code)
    replacement = _new_transaction(
        user, account, transaction_type, amount, category, occurred_on, note, tags
    )
    transaction.account_id = replacement.account_id
    transaction.category_id = replacement.category_id
    transaction.type = replacement.type
    transaction.amount = replacement.amount
    transaction.currency_code = replacement.currency_code
    transaction.base_currency_code = replacement.base_currency_code
    transaction.fx_rate_to_base = replacement.fx_rate_to_base
    transaction.amount_in_base = replacement.amount_in_base
    transaction.date = replacement.date
    transaction.note = replacement.note
    transaction.tags = replacement.tags
    if attachment_path:
        transaction.attachment_path = attachment_path
    db.session.commit()
    return transaction


def delete_transaction(user_id: int, transaction_id: int) -> None:
    transaction = db.session.scalar(
        db.select(Transaction).where(
            Transaction.id == transaction_id, Transaction.user_id == user_id
        )
    )
    if transaction is None:
        raise FinanceError("La transaction est introuvable.")
    if transaction.transfer_group_id:
        paired = list(
            db.session.scalars(
                db.select(Transaction).where(
                    Transaction.user_id == user_id,
                    Transaction.transfer_group_id == transaction.transfer_group_id,
                )
            )
        )
        if len(paired) != 2:
            raise FinanceError("Le virement est incomplet et ne peut pas être supprimé.")
        for leg in paired:
            db.session.delete(leg)
    else:
        db.session.delete(transaction)
    db.session.commit()


def create_transfer(
    user: User,
    source_account_id: int,
    destination_account_id: int,
    source_amount_text: str,
    occurred_on: date,
    note: str,
    tags: str,
) -> tuple[Transaction, Transaction]:
    if source_account_id == destination_account_id:
        raise FinanceError("Les comptes source et destination doivent être différents.")
    source = _user_account(user.id, source_account_id)
    destination = _user_account(user.id, destination_account_id)
    source_amount = parse_amount(source_amount_text, source.currency_code)
    destination_amount = convert_minor_units(
        source_amount,
        source.currency.minor_unit,
        destination.currency.minor_unit,
        get_exchange_rate(source.currency_code, destination.currency_code),
    )
    if destination_amount <= 0:
        raise FinanceError("Le montant du virement est trop faible après conversion.")
    group_id = str(uuid4())
    outgoing = _new_transaction(
        user, source, "expense", source_amount, None, occurred_on, note, tags, group_id
    )
    incoming = _new_transaction(
        user, destination, "income", destination_amount, None, occurred_on, note, tags, group_id
    )
    db.session.add_all([outgoing, incoming])
    db.session.commit()
    return outgoing, incoming


def find_transaction(user_id: int, transaction_id: int) -> Transaction | None:
    return db.session.scalar(
        db.select(Transaction).where(
            Transaction.id == transaction_id, Transaction.user_id == user_id
        )
    )


def query_transactions(
    user_id: int,
    *,
    search: str | None = None,
    account_id: int | None = None,
    transaction_type: str | None = None,
    category_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_amount: str | None = None,
    max_amount: str | None = None,
    page: int = 1,
    per_page: int = 20,
):
    """Return one user's filtered ledger page; amount filters use the selected account currency."""
    query = db.select(Transaction).where(Transaction.user_id == user_id)
    account = None
    if account_id:
        account = _user_account(user_id, account_id, allow_archived=True)
        query = query.where(Transaction.account_id == account.id)
    if transaction_type == "transfer":
        query = query.where(Transaction.transfer_group_id.is_not(None))
    elif transaction_type:
        query = query.where(
            Transaction.type == transaction_type,
            Transaction.transfer_group_id.is_(None),
        )
    if category_id:
        category = _user_category(user_id, category_id, include_archived=True)
        query = query.where(Transaction.category_id == category.id)
    if date_from:
        query = query.where(Transaction.date >= datetime.combine(date_from, time.min))
    if date_to:
        query = query.where(
            Transaction.date < datetime.combine(date_to + timedelta(days=1), time.min)
        )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            db.or_(
                Transaction.note.ilike(pattern),
                Transaction.tags.ilike(pattern),
            )
        )
    if min_amount or max_amount:
        if account is None:
            raise FinanceError("Choisissez un compte pour filtrer par montant.")
        currency = account.currency
        if min_amount:
            minimum = parse_amount(min_amount, currency.code, allow_negative=True)
            if minimum < 0:
                raise FinanceError("Le montant minimum ne peut pas être négatif.")
            query = query.where(Transaction.amount >= minimum)
        if max_amount:
            maximum = parse_amount(max_amount, currency.code, allow_negative=True)
            if maximum < 0:
                raise FinanceError("Le montant maximum ne peut pas être négatif.")
            query = query.where(Transaction.amount <= maximum)
    if date_from and date_to and date_from > date_to:
        raise FinanceError("La date de début doit précéder la date de fin.")
    return db.paginate(
        query.order_by(Transaction.date.desc(), Transaction.id.desc()),
        page=max(1, page),
        per_page=per_page,
        error_out=False,
    )
