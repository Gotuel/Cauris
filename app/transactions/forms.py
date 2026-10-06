from datetime import date

from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import DateField, FileField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, Optional

from app.extensions import db
from app.models import Account, Category
from app.services.finance import category_display_name


def required():
    return DataRequired(message=_l("Ce champ est obligatoire."))


def max_length(limit: int):
    return Length(
        max=limit,
        message=_l("Ce champ ne peut dépasser %(max)d caractères.", max=limit),
    )


def _account_choices(user_id: int, *, include_archived_id: int | None = None):
    query = db.select(Account).where(Account.user_id == user_id)
    if include_archived_id is None:
        query = query.where(Account.is_archived.is_(False))
    else:
        query = query.where(
            db.or_(Account.is_archived.is_(False), Account.id == include_archived_id)
        )
    return [
        (account.id, f"{account.name} ({account.currency_code})")
        for account in db.session.scalars(query.order_by(Account.name))
    ]


def _category_choices(
    user_id: int,
    category_type: str | None = None,
    *,
    include_archived: bool = False,
):
    conditions = [db.or_(Category.user_id == user_id, Category.user_id.is_(None))]
    if not include_archived:
        conditions.append(Category.is_archived.is_(False))
    query = db.select(Category).where(*conditions)
    if category_type in {"income", "expense"}:
        query = query.where(Category.type == category_type)
    return [(0, _l("Sans catégorie"))] + [
        (category.id, category_display_name(category))
        for category in db.session.scalars(query.order_by(Category.key))
    ]


class TransactionForm(FlaskForm):
    account_id = SelectField(_l("Compte"), coerce=int, validators=[required()])
    type = SelectField(
        _l("Type"),
        choices=[("expense", _l("Dépense")), ("income", _l("Revenu"))],
        validators=[required()],
    )
    amount = StringField(_l("Montant"), validators=[required(), max_length(40)])
    category_id = SelectField(_l("Catégorie"), coerce=int, validators=[Optional()])
    occurred_on = DateField(_l("Date"), format="%Y-%m-%d", default=date.today, validators=[required()])
    note = StringField(_l("Note"), validators=[Optional(), max_length(2000)])
    tags = StringField(_l("Tags, séparés par des virgules"), validators=[Optional(), max_length(500)])
    attachment = FileField(_l("Reçu (PNG, JPEG, WebP ou PDF)"))
    submit = SubmitField(_l("Enregistrer la transaction"))

    def __init__(
        self,
        user_id: int,
        *args,
        include_archived_account_id: int | None = None,
        category_type: str | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.account_id.choices = _account_choices(
            user_id, include_archived_id=include_archived_account_id
        )
        self.category_id.choices = _category_choices(user_id, category_type)


class TransferForm(FlaskForm):
    source_account_id = SelectField(_l("Compte source"), coerce=int, validators=[required()])
    destination_account_id = SelectField(
        _l("Compte destinataire"), coerce=int, validators=[required()]
    )
    source_amount = StringField(_l("Montant débité"), validators=[required(), max_length(40)])
    occurred_on = DateField(_l("Date"), format="%Y-%m-%d", default=date.today, validators=[required()])
    note = StringField(_l("Note"), validators=[Optional(), max_length(2000)])
    tags = StringField(_l("Tags, séparés par des virgules"), validators=[Optional(), max_length(500)])
    submit = SubmitField(_l("Enregistrer le virement"))

    def __init__(self, user_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = _account_choices(user_id)
        self.source_account_id.choices = choices
        self.destination_account_id.choices = choices


class CategoryForm(FlaskForm):
    key = StringField(_l("Clé technique"), validators=[required(), max_length(80)])
    custom_name = StringField(_l("Nom affiché"), validators=[required(), max_length(120)])
    type = SelectField(
        _l("Type"),
        choices=[("expense", _l("Dépense")), ("income", _l("Revenu"))],
        validators=[required()],
    )
    parent_id = SelectField(_l("Catégorie parente"), coerce=int, validators=[Optional()])
    icon = StringField(_l("Icône"), validators=[Optional(), max_length(50)])
    color = StringField(_l("Couleur"), default="#64748b", validators=[Optional(), max_length(7)])
    submit = SubmitField(_l("Créer la catégorie"))

    def __init__(self, user_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent_id.choices = [(0, _l("Aucune (catégorie principale)"))] + [
            (category.id, category_display_name(category))
            for category in db.session.scalars(
                db.select(Category)
                .where(
                    db.or_(Category.user_id == user_id, Category.user_id.is_(None)),
                    Category.parent_id.is_(None),
                    Category.is_archived.is_(False),
                )
                .order_by(Category.custom_name)
            )
        ]


class TransactionFilterForm(FlaskForm):
    search = StringField(_l("Recherche"), validators=[Optional(), max_length(100)])
    account_id = SelectField(_l("Compte"), coerce=int, validators=[Optional()])
    type = SelectField(
        _l("Type"),
        choices=[
            ("", _l("Tous")),
            ("income", _l("Revenu")),
            ("expense", _l("Dépense")),
            ("transfer", _l("Virement")),
        ],
        validators=[Optional()],
    )
    category_id = SelectField(_l("Catégorie"), coerce=int, validators=[Optional()])
    date_from = DateField(_l("Du"), format="%Y-%m-%d", validators=[Optional()])
    date_to = DateField(_l("Au"), format="%Y-%m-%d", validators=[Optional()])
    min_amount = StringField(_l("Montant minimum"), validators=[Optional(), max_length(40)])
    max_amount = StringField(_l("Montant maximum"), validators=[Optional(), max_length(40)])

    def __init__(self, user_id: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.account_id.choices = [(0, _l("Tous les comptes"))] + _account_choices(user_id)
        self.category_id.choices = [(0, _l("Toutes les catégories"))] + _category_choices(
            user_id, include_archived=True
        )[1:]
