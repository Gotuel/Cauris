from flask_babel import Babel
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from flask_apscheduler import APScheduler


db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
babel = Babel()
mail = Mail()
csrf = CSRFProtect()
scheduler = APScheduler()


@login_manager.user_loader
def load_user(user_id: str):
    from .models import User

    return db.session.get(User, int(user_id))


login_manager.login_view = "auth.login"
login_manager.login_message_category = "info"
