from flask_wtf import FlaskForm
from flask_babel import lazy_gettext as _l
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length

from app.extensions import db
from app.models import Currency


LOCALE_CHOICES = [("fr", _l("Français")), ("en", _l("English"))]
THEME_CHOICES = [("light", _l("Clair")), ("dark", _l("Sombre")), ("system", _l("Système"))]


def required():
    return DataRequired(message=_l("Ce champ est obligatoire."))


class CurrencyChoiceMixin:
    def set_currency_choices(self) -> None:
        self.base_currency.choices = [
            (currency.code, f"{currency.code} — {currency.name}")
            for currency in db.session.scalars(db.select(Currency).order_by(Currency.code))
        ]


class RegistrationForm(CurrencyChoiceMixin, FlaskForm):
    username = StringField(
        _l("Nom d’utilisateur"),
        validators=[required(), Length(max=80, message=_l("Le nom ne peut dépasser 80 caractères."))],
    )
    email = StringField(
        _l("Adresse e-mail"),
        validators=[
            required(),
            Email(message=_l("Saisissez une adresse e-mail valide.")),
            Length(max=255, message=_l("L’adresse e-mail est trop longue.")),
        ],
    )
    password = PasswordField(
        _l("Mot de passe"),
        validators=[
            required(),
            Length(
                min=12,
                max=128,
                message=_l("Le mot de passe doit compter entre 12 et 128 caractères."),
            ),
        ],
    )
    confirm_password = PasswordField(
        _l("Confirmer le mot de passe"),
        validators=[required(), EqualTo("password", message=_l("Les mots de passe ne correspondent pas."))],
    )
    locale = SelectField(_l("Langue"), choices=LOCALE_CHOICES, validators=[required()])
    base_currency = SelectField(_l("Devise principale"), validators=[required()])
    submit = SubmitField(_l("Créer mon compte"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_currency_choices()


class LoginForm(FlaskForm):
    email = StringField(
        _l("Adresse e-mail"),
        validators=[
            required(),
            Email(message=_l("Saisissez une adresse e-mail valide.")),
            Length(max=255, message=_l("L’adresse e-mail est trop longue.")),
        ],
    )
    password = PasswordField(_l("Mot de passe"), validators=[required()])
    remember = BooleanField(_l("Rester connecté"))
    submit = SubmitField(_l("Se connecter"))


class RequestResetForm(FlaskForm):
    email = StringField(
        _l("Adresse e-mail"),
        validators=[
            required(),
            Email(message=_l("Saisissez une adresse e-mail valide.")),
            Length(max=255, message=_l("L’adresse e-mail est trop longue.")),
        ],
    )
    submit = SubmitField(_l("Envoyer le lien"))


class ResetPasswordForm(FlaskForm):
    password = PasswordField(
        _l("Nouveau mot de passe"),
        validators=[
            required(),
            Length(
                min=12,
                max=128,
                message=_l("Le mot de passe doit compter entre 12 et 128 caractères."),
            ),
        ],
    )
    confirm_password = PasswordField(
        _l("Confirmer le mot de passe"),
        validators=[required(), EqualTo("password", message=_l("Les mots de passe ne correspondent pas."))],
    )
    submit = SubmitField(_l("Réinitialiser le mot de passe"))


class ProfileForm(CurrencyChoiceMixin, FlaskForm):
    username = StringField(
        _l("Nom d’utilisateur"),
        validators=[required(), Length(max=80, message=_l("Le nom ne peut dépasser 80 caractères."))],
    )
    locale = SelectField(_l("Langue"), choices=LOCALE_CHOICES, validators=[required()])
    base_currency = SelectField(_l("Devise principale"), validators=[required()])
    theme = SelectField(_l("Thème"), choices=THEME_CHOICES, validators=[required()])
    submit = SubmitField(_l("Enregistrer les préférences"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_currency_choices()


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(_l("Mot de passe actuel"), validators=[required()])
    password = PasswordField(
        _l("Nouveau mot de passe"),
        validators=[
            required(),
            Length(
                min=12,
                max=128,
                message=_l("Le mot de passe doit compter entre 12 et 128 caractères."),
            ),
        ],
    )
    confirm_password = PasswordField(
        _l("Confirmer le nouveau mot de passe"),
        validators=[required(), EqualTo("password", message=_l("Les mots de passe ne correspondent pas."))],
    )
    submit = SubmitField(_l("Changer le mot de passe"))


class DeleteAccountForm(FlaskForm):
    password = PasswordField(_l("Mot de passe"), validators=[required()])
    submit = SubmitField(_l("Supprimer définitivement mon compte"))
