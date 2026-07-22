from flask import Flask
from .services.auth_service import init_db


def create_app():
    app = Flask(__name__)
    app.secret_key = 'opshub_secure_session_key_2026'

    # Initialize SQLite Database & Seed Default Admin
    init_db()

    from .routes import main
    app.register_blueprint(main)

    return app
