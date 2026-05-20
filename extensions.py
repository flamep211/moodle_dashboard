from flask_bcrypt import Bcrypt
from flask_caching import Cache

# Экземпляры расширений, используемых в приложении.
# Инициализируются здесь и затем привязываются к приложению
# через их `init_app` в фабрике приложения (`app.create_app`).
bcrypt = Bcrypt()
cache = Cache()
