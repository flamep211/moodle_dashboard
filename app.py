import os
from flask import Flask

from database import db
from extensions import bcrypt, cache
from views import main_bp

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "moodle.db")


def create_app():
    app = Flask(__name__)
    app.secret_key = "CHANGE_ME_SECRET"

    os.makedirs(DATA_DIR, exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["CACHE_TYPE"] = "simple"
    app.config["CACHE_DEFAULT_TIMEOUT"] = 300

    bcrypt.init_app(app)
    cache.init_app(app)
    db.init_app(app)

    app.register_blueprint(main_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
