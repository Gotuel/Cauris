from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length

from app.extensions import db
from app.models import Currency


def required():
    return DataRequired(message=_l("Ce champ est obligatoire."))


def max_length(limit: int):
    return Length(max=limit, message=_l("Ce champ ne peut dépasser %(max)d caractères.", max=limit))


ACCOUNT_TYPES = [
    ("cash", _l("Espèces")),
    ("bank", _l("Banque")),
    ("mobile_money", _l("Mobile money")),
    ("savings", _l("Épargne")),
    ("card", _l("Carte")),
]


class AccountForm(FlaskForm):
    name = StringField(_l("Nom du compte"), validators=[required(), max_length(120)])
    type = SelectField(_l("Type de compte"), choices=ACCOUNT_TYPES, validators=[required()])
    currency_code = SelectField(_l("Devise"), validators=[required()])
    initial_balance = StringField(_l("Solde initial"), validators=[required(), max_length(40)])
    submit = SubmitField(_l("Enregistrer le compte"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.currency_code.choices = [
            (currency.code, f"{currency.code} — {currency.name}")
            for currency in db.session.scalars(db.select(Currency).order_by(Currency.code))
        ]
