from flask import Blueprint

debts_bp = Blueprint("debts", __name__)


@debts_bp.route("/")
def index():
    return "Debts blueprint ready"
