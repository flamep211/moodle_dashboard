import os
from flask import Flask

from database import db, init_db
from extensions import bcrypt, cache
from views import main_bp

# Базовая директория проекта — используется для построения
# абсолютных путей к папке `data` и файлу базы данных.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
# Папка, где хранятся CSV и файл sqlite; создаётся при старте.
DATA_DIR = os.path.join(BASE_DIR, "data")
# Полный путь к sqlite-файлу. Используем абсолютный путь,
# чтобы не зависеть от текущей рабочей директории при запуске.
DB_PATH = os.path.join(DATA_DIR, "moodle.db")


def create_app():
    app = Flask(__name__)
    app.secret_key = "CHANGE_ME_SECRET"

    # Создаём папку `data`, если её нет — это важно для sqlite-файла
    os.makedirs(DATA_DIR, exist_ok=True)

    # Настройка SQLAlchemy: используем sqlite с абсолютным путём
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Кеш и bcrypt инициализируем через их .init_app
    app.config["CACHE_TYPE"] = "simple"
    app.config["CACHE_DEFAULT_TIMEOUT"] = 300

    bcrypt.init_app(app)
    cache.init_app(app)

    # Привязываем глобальный объект `db` к приложению
    init_db(app)

    # Регистрируем Blueprint с обработчиками (routes)
    app.register_blueprint(main_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
