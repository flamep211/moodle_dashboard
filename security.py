from functools import wraps
from flask import session, redirect, url_for, flash


# Словарь тестовых пользователей — используется для локальной аутентификации.
# Пароли хранятся в виде хешей (bcrypt). В реальном проде данные нужно хранить
# в базе и обеспечивать безопасное управление паролями.
USERS = {
    "teacher": {
        "password_hash": "$2b$12$KBgC1aiBvpeDSWxvxCwaiuNCQVtVUBVpi9e777QQbkXrvgLNgnsvu",
        "role": "teacher"
    },
    "admin": {
        "password_hash": "$2b$12$vY54C8jivxh9NvXUh018PuNpeAjuzwtp4gdW8Cd9WqQbrW.5fe4yG",
        "role": "admin"
    },
}

# Конфигурация ограничений по попыткам логина (используется в `views.login`)
LOGIN_ATTEMPTS_LIMIT = 5
LOGIN_ATTEMPTS_TIMEOUT = 15


def login_required(view_func):
    """Декоратор для маршрутов, требующих авторизации.

    Перенаправляет на страницу логина, если в `session` нет ключа `user`.
    """
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("main.login"))
        return view_func(*args, **kwargs)
    return wrapper


def role_required(*roles):
    """Декоратор для проверки роли пользователя.

    Пример использования: `@role_required('admin')`.
    Если роль пользователя не входит в `roles` — возвращает на главную
    и показывает сообщение об ошибке.
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if session.get("role") not in roles:
                flash("Недостаточно прав", "error")
                return redirect(url_for("main.index"))
            return view_func(*args, **kwargs)
        return wrapper
    return decorator
