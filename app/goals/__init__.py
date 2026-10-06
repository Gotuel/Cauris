from flask import Blueprint

goals_bp = Blueprint("goals", __name__)


@goals_bp.route("/")
def index():
    return "Goals blueprint ready"
