from flask import Blueprint

accounts_bp = Blueprint("accounts", __name__)


@accounts_bp.route("/")
def list_accounts():
    return "Accounts blueprint ready"
