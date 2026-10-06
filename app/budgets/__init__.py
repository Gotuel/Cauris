from flask import Blueprint

budgets_bp = Blueprint("budgets", __name__)


@budgets_bp.route("/")
def index():
    return "Budgets blueprint ready"
