from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from flask import current_app, url_for
from flask_babel import force_locale, gettext as _
from flask_mail import Message
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.extensions import db, mail
from app.models import User


password_hasher = PasswordHasher()
TOKEN_SALT = "cauris-account-security"


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError):
        return False


def create_user_token(user: User, purpose: str) -> str:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=TOKEN_SALT)
    payload = {"user_id": user.id, "purpose": purpose}
    if purpose == "reset":
        payload["password_hash"] = user.password_hash
    return serializer.dumps(payload)


def load_user_token(token: str, purpose: str) -> User | None:
    serializer = URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=TOKEN_SALT)
    try:
        payload = serializer.loads(
            token, max_age=current_app.config["SECURITY_TOKEN_MAX_AGE"]
        )
    except (BadSignature, SignatureExpired):
        return None

    if payload.get("purpose") != purpose:
        return None
    user = db.session.get(User, payload.get("user_id"))
    if purpose == "reset" and (
        user is None or payload.get("password_hash") != user.password_hash
    ):
        return None
    return user


def send_account_email(user: User, purpose: str) -> None:
    token = create_user_token(user, purpose)
    endpoint = "auth.confirm_email" if purpose == "confirm" else "auth.reset_password"
    with force_locale(user.locale):
        link = url_for(endpoint, token=token, _external=True)
        subject = (
            _("Confirmez votre adresse e-mail — Cauris")
            if purpose == "confirm"
            else _("Réinitialisez votre mot de passe — Cauris")
        )
        action = (
            _("confirmer votre adresse e-mail")
            if purpose == "confirm"
            else _("réinitialiser votre mot de passe")
        )
        body = _(
            "Bonjour %(username)s,\n\nUtilisez le lien suivant pour %(action)s :\n"
            "%(link)s\n\nCe lien expire dans %(minutes)s minutes.",
            username=user.username,
            action=action,
            link=link,
            minutes=current_app.config["SECURITY_TOKEN_MAX_AGE"] // 60,
        )
    mail.send(Message(subject=subject, recipients=[user.email], body=body))
