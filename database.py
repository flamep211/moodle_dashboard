from flask_sqlalchemy import SQLAlchemy
from flask import current_app

# Глобальный объект SQLAlchemy — объявляем здесь, чтобы другие
# модули (models, views, analytics) могли импортировать `db` без
# немедленной привязки к приложению. Привязка выполняется далее
# при инициализации Flask-приложения.
db = SQLAlchemy()


def init_db(app):
	# Обёртка для `db.init_app(app)` — для единообразия вызовов
	# и лучшей читаемости кода. Вызывается из фабрики приложения
	# (например, в `app.create_app()` или при старте сервера).
	db.init_app(app)


def create_all(app=None):
	# Создаёт все таблицы, описанные через SQLAlchemy модели.
	# Если передан `app`, используем его контекст. Иначе предполагаем,
	# что уже есть активный `current_app`.
	if app is None:
		app = current_app
	with app.app_context():
		db.create_all()
