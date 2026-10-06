from datetime import datetime, timedelta, timezone
from smtplib import SMTPException
from urllib.parse import urlsplit

from flask_babel import gettext as _
from flask import Blueprint, current_app, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import User
from .forms import (
    ChangePasswordForm,
    DeleteAccountForm,
    LoginForm,
    ProfileForm,
    RegistrationForm,
    RequestResetForm,
    ResetPasswordForm,
)
from .services import (
    hash_password,
    load_user_token,
    send_account_email,
    verify_password,
)

auth_bp = Blueprint("auth", __name__)


def _safe_next_url(target: str | None) -> str | None:
    if not target:
        return None
    parsed = urlsplit(target)
    if not parsed.scheme and not parsed.netloc and target.startswith("/") and not target.startswith("//"):
        return target
    return None


def _send_mail_or_report(user: User, purpose: str) -> bool:
    try:
        send_account_email(user, purpose)
    except (OSError, SMTPException):
        current_app.logger.exception("Could not send %s email to user %s", purpose, user.id)
        return False
    return True


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = RegistrationForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        existing_user = db.session.scalar(
            db.select(User).where(func.lower(User.email) == email)
        )
        if existing_user:
            form.email.errors.append(_("Cette adresse e-mail est déjà utilisée."))
        else:
            user = User(
                email=email,
                username=form.username.data.strip(),
                password_hash=hash_password(form.password.data),
                locale=form.locale.data,
                base_currency=form.base_currency.data,
            )
            db.session.add(user)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                form.email.errors.append(_("Cette adresse e-mail est déjà utilisée."))
            else:
                session["locale"] = user.locale
                if _send_mail_or_report(user, "confirm"):
                    flash(
                        _("Votre compte est créé. Consultez votre e-mail pour confirmer votre adresse."),
                        "success",
                    )
                    return redirect(url_for("auth.login"))
                flash(
                    _("Le compte est créé, mais l’e-mail de confirmation n’a pas pu être envoyé. "
                      "Vérifiez la configuration e-mail puis réessayez."),
                    "error",
                )
                return render_template("auth/register.html", form=form), 503
    return render_template("auth/register.html", form=form)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(db.select(User).where(func.lower(User.email) == email))
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if user and user.login_locked_until and user.login_locked_until > now:
            flash(_("Trop de tentatives. Réessayez dans quelques minutes."), "error")
        elif not user or not verify_password(user.password_hash, form.password.data):
            if user:
                user.failed_login_attempts += 1
                if user.failed_login_attempts >= current_app.config["LOGIN_MAX_ATTEMPTS"]:
                    user.login_locked_until = now + timedelta(
                        minutes=current_app.config["LOGIN_LOCKOUT_MINUTES"]
                    )
                    user.failed_login_attempts = 0
                db.session.commit()
            flash(_("Adresse e-mail ou mot de passe invalide."), "error")
        elif not user.is_active:
            flash(_("Ce compte est désactivé. Contactez l’assistance."), "error")
        elif not user.email_confirmed:
            if _send_mail_or_report(user, "confirm"):
                flash(
                    _("Confirmez votre adresse e-mail avant de vous connecter. "
                      "Un nouveau lien vient de vous être envoyé."),
                    "warning",
                )
            else:
                flash(
                    _("Votre adresse e-mail n’est pas encore confirmée et le message n’a pas pu être envoyé."),
                    "error",
                )
        else:
            user.failed_login_attempts = 0
            user.login_locked_until = None
            db.session.commit()
            login_user(user, remember=form.remember.data)
            return redirect(_safe_next_url(request.args.get("next")) or url_for("main.index"))
    return render_template("auth/login.html", form=form)


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    flash(_("Vous êtes déconnecté."), "success")
    return redirect(url_for("main.index"))


@auth_bp.get("/confirm/<token>")
def confirm_email(token: str):
    user = load_user_token(token, "confirm")
    if user is None:
        flash(_("Ce lien de confirmation est invalide ou a expiré."), "error")
    elif user.email_confirmed:
        session["locale"] = user.locale
        flash(_("Cette adresse e-mail est déjà confirmée."), "info")
    else:
        session["locale"] = user.locale
        user.email_confirmed = True
        db.session.commit()
        flash(_("Votre adresse e-mail est confirmée. Vous pouvez vous connecter."), "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/password-reset", methods=["GET", "POST"])
def request_password_reset():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = RequestResetForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = db.session.scalar(db.select(User).where(func.lower(User.email) == email))
        mail_sent = True if user is None else _send_mail_or_report(user, "reset")
        flash(
            _("Si cette adresse correspond à un compte, un lien de réinitialisation va être envoyé."),
            "info",
        )
        if not mail_sent:
            flash(
                _("Le message n’a pas pu être envoyé. Réessayez plus tard ou contactez l’assistance."),
                "error",
            )
            return render_template("auth/password_reset_request.html", form=form), 503
        return redirect(url_for("auth.login"))
    return render_template("auth/password_reset_request.html", form=form)


@auth_bp.route("/password-reset/<token>", methods=["GET", "POST"])
def reset_password(token: str):
    user = load_user_token(token, "reset")
    if user is None:
        flash(_("Ce lien de réinitialisation est invalide ou a expiré."), "error")
        return redirect(url_for("auth.request_password_reset"))
    session["locale"] = user.locale
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.password_hash = hash_password(form.password.data)
        user.failed_login_attempts = 0
        user.login_locked_until = None
        db.session.commit()
        flash(_("Votre mot de passe a été modifié. Vous pouvez vous connecter."), "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/password_reset.html", form=form)


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    form = ProfileForm(obj=current_user)
    if form.validate_on_submit():
        current_user.username = form.username.data.strip()
        current_user.locale = form.locale.data
        current_user.base_currency = form.base_currency.data
        current_user.theme = form.theme.data
        db.session.commit()
        flash("Vos préférences ont été enregistrées.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("auth/profile.html", form=form)


@auth_bp.route("/change-password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not verify_password(current_user.password_hash, form.current_password.data):
            form.current_password.errors.append(_("Le mot de passe actuel est incorrect."))
        else:
            current_user.password_hash = hash_password(form.password.data)
            db.session.commit()
            flash(_("Votre mot de passe a été modifié."), "success")
            return redirect(url_for("auth.profile"))
    return render_template("auth/change_password.html", form=form)


@auth_bp.route("/delete-account", methods=["GET", "POST"])
@login_required
def delete_account():
    form = DeleteAccountForm()
    if form.validate_on_submit():
        if not verify_password(current_user.password_hash, form.password.data):
            form.password.errors.append(_("Le mot de passe est incorrect."))
        else:
            user = current_user._get_current_object()
            logout_user()
            db.session.delete(user)
            db.session.commit()
            flash(_("Votre compte et ses données ont été supprimés."), "success")
            return redirect(url_for("main.index"))
    return render_template("auth/delete_account.html", form=form)
