from flask import Blueprint

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login")
def login():
    return "Login blueprint ready"


@auth_bp.route("/register")
def register():
    return "Register blueprint ready"
