from functools import wraps
from flask import session, redirect, url_for, flash

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

LOGIN_ATTEMPTS_LIMIT = 5
LOGIN_ATTEMPTS_TIMEOUT = 15


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("main.login"))
        return view_func(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if session.get("role") not in roles:
                flash("Недостаточно прав", "error")
                return redirect(url_for("main.index"))
            return view_func(*args, **kwargs)
        return wrapper
    return decorator
