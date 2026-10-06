from flask import Blueprint, flash, redirect, render_template, url_for
from flask_babel import gettext as _
from flask_login import current_user, login_required

from app.accounts.forms import AccountForm
from app.models import Account
from app.services.finance import (
    FinanceError,
    amount_input_value,
    account_balance,
    create_account,
    format_minor_amount,
    set_account_archived,
    update_account,
)

accounts_bp = Blueprint("accounts", __name__)


def _account_form(account: Account | None = None) -> AccountForm:
    form = AccountForm()
    if account is not None:
        form.name.data = account.name
        form.type.data = account.type
        form.currency_code.data = account.currency_code
        form.initial_balance.data = amount_input_value(
            account.initial_balance, account.currency_code
        )
    return form


@accounts_bp.route("/")
@login_required
def list_accounts():
    accounts = (
        Account.query.filter_by(user_id=current_user.id)
        .order_by(Account.is_archived, Account.name)
        .all()
    )
    balances = {
        account.id: format_minor_amount(account_balance(account), account.currency_code)
        for account in accounts
    }
    return render_template("accounts/list.html", accounts=accounts, balances=balances)


@accounts_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_account():
    form = AccountForm()
    if form.validate_on_submit():
        try:
            create_account(
                current_user,
                form.name.data,
                form.type.data,
                form.currency_code.data,
                form.initial_balance.data,
            )
        except FinanceError as error:
            flash(str(error), "error")
        else:
            flash(_("Le compte a été créé."), "success")
            return redirect(url_for("accounts.list_accounts"))
    return render_template("accounts/form.html", form=form, account=None)


@accounts_bp.route("/<int:account_id>/edit", methods=["GET", "POST"])
@login_required
def edit_account(account_id: int):
    account = Account.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    form = AccountForm()
    if not form.is_submitted():
        form = _account_form(account)
    if form.validate_on_submit():
        try:
            update_account(
                current_user.id,
                account.id,
                form.name.data,
                form.type.data,
                form.currency_code.data,
                form.initial_balance.data,
            )
        except FinanceError as error:
            flash(str(error), "error")
        else:
            flash(_("Le compte a été mis à jour."), "success")
            return redirect(url_for("accounts.list_accounts"))
    return render_template("accounts/form.html", form=form, account=account)


@accounts_bp.post("/<int:account_id>/archive")
@login_required
def archive_account(account_id: int):
    Account.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    try:
        set_account_archived(current_user.id, account_id, True)
    except FinanceError as error:
        flash(str(error), "error")
        return redirect(url_for("accounts.list_accounts"))
    flash(_("Le compte a été archivé."), "success")
    return redirect(url_for("accounts.list_accounts"))


@accounts_bp.post("/<int:account_id>/restore")
@login_required
def restore_account(account_id: int):
    Account.query.filter_by(id=account_id, user_id=current_user.id).first_or_404()
    try:
        set_account_archived(current_user.id, account_id, False)
    except FinanceError as error:
        flash(str(error), "error")
        return redirect(url_for("accounts.list_accounts"))
    flash(_("Le compte a été restauré."), "success")
    return redirect(url_for("accounts.list_accounts"))
