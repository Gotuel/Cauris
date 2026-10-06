from flask import Blueprint

transactions_bp = Blueprint("transactions", __name__)


@transactions_bp.route("/")
def list_transactions():
    return "Transactions blueprint ready"
