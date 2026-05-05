# app.py - Основное приложение Moodle Analytics Dashboard
# Это Flask-приложение для анализа данных Moodle с визуализацией оценок и активности студентов

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
from flask_bcrypt import Bcrypt
from flask_caching import Cache
import pandas as pd
import numpy as np
from functools import wraps
from datetime import datetime, date, timedelta
import os
import io
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text

# Инициализация Flask-приложения
app = Flask(__name__)
app.secret_key = "CHANGE_ME_SECRET"  # В продакшене заменить на безопасный секретный ключ

# Инициализация Bcrypt для хэширования паролей
bcrypt = Bcrypt(app)

# Настройка кэширования для улучшения производительности
# Используется SimpleCache (in-memory) для разработки, FileSystemCache для продакшена
cache = Cache(app, config={
    'CACHE_TYPE': 'simple',  # Для продакшена: 'filesystem'
    'CACHE_DEFAULT_TIMEOUT': 300  # 5 минут по умолчанию
})

# Настройки базы данных
DATA_DIR = "data"  # Директория для хранения данных
AUTO_IMPORT_DISABLED_FILE = os.path.join(DATA_DIR, ".no_auto_import")  # Файл-маркер для отключения автоимпорта
db_file = os.path.abspath(os.path.join(DATA_DIR, "moodle.db"))  # Абсолютный путь к SQLite файлу
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Инициализация SQLAlchemy для работы с базой данных
db = SQLAlchemy(app)

# Модели базы данных (ORM модели с использованием SQLAlchemy)

class Student(db.Model):
    """Модель для хранения информации о студентах"""
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)  # Уникальный ID студента
    name = db.Column(db.String, nullable=False)   # ФИО студента
    group = db.Column(db.String)                   # Группа студента
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)  # Время импорта
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)  # ID партии импорта

class Course(db.Model):
    """Модель для хранения информации о курсах"""
    __tablename__ = "courses"
    course_id = db.Column(db.Integer, primary_key=True)  # Уникальный ID курса
    course_name = db.Column(db.String, nullable=False)   # Название курса
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)  # Время импорта
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)  # ID партии импорта

class Grade(db.Model):
    """Модель для хранения оценок студентов"""
    __tablename__ = "grades"
    id = db.Column(db.Integer, primary_key=True)  # Автоинкрементный ID записи
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)  # ID студента
    course_id = db.Column(db.Integer, db.ForeignKey("courses.course_id"), nullable=False)  # ID курса
    grade = db.Column(db.Float, nullable=False)  # Оценка (число с плавающей точкой)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)  # Время импорта
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)  # ID партии импорта

class Log(db.Model):
    """Модель для хранения логов активности студентов"""
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)  # Автоинкрементный ID записи
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)  # ID студента
    course_id = db.Column(db.Integer, db.ForeignKey("courses.course_id"), nullable=False)  # ID курса
    action = db.Column(db.String)  # Действие (например, "login", "view", "submit")
    date = db.Column(db.String)    # Дата действия (строка для гибкости)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)  # Время импорта
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)  # ID партии импорта

class ImportBatch(db.Model):
    """Модель для отслеживания партий импорта данных"""
    __tablename__ = "import_batches"
    id = db.Column(db.Integer, primary_key=True)  # Уникальный ID партии
    created_at = db.Column(db.DateTime, default=datetime.utcnow)  # Время создания партии
    label = db.Column(db.String, nullable=False)  # Метка партии (например, "2026-03")
    source = db.Column(db.String, nullable=False)  # Источник данных (students/courses/grades/logs)

class UserSettings(db.Model):
    """Модель для хранения пользовательских настроек"""
    __tablename__ = "user_settings"
    username = db.Column(db.String, primary_key=True)  # Имя пользователя (первичный ключ)
    theme = db.Column(db.String, default="light")      # Тема интерфейса ('light' или 'dark')
    settings_json = db.Column(db.Text, default="{}")   # Дополнительные настройки в JSON формате


# Хешированные пароли пользователей (создано с помощью bcrypt)
# Оригинальные пароли: teacher -> "12345", admin -> "admin123"
# В продакшене пароли должны храниться в защищенной базе данных или переменных окружения
USERS = {
    "teacher": {
        "password_hash": "$2b$12$KBgC1aiBvpeDSWxvxCwaiuNCQVtVUBVpi9e777QQbkXrvgLNgnsvu",
        "role": "teacher"  # Роль преподавателя - ограниченный доступ
    },
    "admin": {
        "password_hash": "$2b$12$vY54C8jivxh9NvXUh018PuNpeAjuzwtp4gdW8Cd9WqQbrW.5fe4yG",
        "role": "admin"    # Роль администратора - полный доступ
    },
}

# Настройки безопасности аутентификации
LOGIN_ATTEMPTS_LIMIT = 5      # Максимальное количество неудачных попыток входа
LOGIN_ATTEMPTS_TIMEOUT = 15   # Время блокировки в минутах после превышения лимита

# Декоратор для проверки аутентификации пользователя
def login_required(view_func):
    """Декоратор, требующий аутентификации пользователя перед доступом к странице"""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user" not in session:  # Проверяем наличие пользователя в сессии
            return redirect(url_for("login"))  # Перенаправляем на страницу входа
        return view_func(*args, **kwargs)
    return wrapper

# Декоратор для проверки ролей пользователей
def role_required(*roles):
    """Декоратор для ограничения доступа по ролям пользователей"""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            if session.get("role") not in roles:  # Проверяем роль пользователя
                flash("Недостаточно прав", "error")  # Показываем сообщение об ошибке
                return redirect(url_for("index"))   # Перенаправляем на главную
            return view_func(*args, **kwargs)
        return wrapper
    return decorator

def ensure_data_dir():
    """Создает директорию данных и настраивает базу данных при первом запуске"""
    # Создаем директорию для данных, если она не существует
    os.makedirs(DATA_DIR, exist_ok=True)

    # Создаем все таблицы базы данных, если они еще не созданы
    db.create_all()

    # Добавляем недостающие колонки в существующие таблицы (для обратной совместимости)
    def ensure_column(table, column, definition):
        """Добавляет колонку в таблицу, если она отсутствует"""
        conn = db.engine.connect()
        try:
            # Получаем список существующих колонок
            existing = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
            if column not in existing:
                # Добавляем недостающую колонку
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        finally:
            conn.close()

    # Добавляем колонки для отслеживания времени импорта и партий
    ensure_column("students", "imported_at", "DATETIME")
    ensure_column("students", "import_batch_id", "INTEGER")
    ensure_column("courses", "imported_at", "DATETIME")
    ensure_column("courses", "import_batch_id", "INTEGER")
    ensure_column("grades", "imported_at", "DATETIME")
    ensure_column("grades", "import_batch_id", "INTEGER")
    ensure_column("logs", "imported_at", "DATETIME")
    ensure_column("logs", "import_batch_id", "INTEGER")

    # Автоматический импорт данных из CSV файлов при первом запуске
    # Примечание: после явного сброса данных мы избегаем повторного импорта из CSV,
    # чтобы сброс оставался в силе.
    auto_import_enabled = not os.path.exists(AUTO_IMPORT_DISABLED_FILE)

    def try_import(table_name, model):
        """Пытается импортировать данные из CSV файла в таблицу"""
        if not auto_import_enabled:
            return
        path = os.path.join(DATA_DIR, f"{table_name}.csv")
        if os.path.exists(path) and model.query.count() == 0:
            try:
                df = pd.read_csv(path)  # Читаем CSV файл
            except Exception:
                return
            recs = df.to_dict(orient="records")  # Преобразуем в список словарей
            for r in recs:
                obj = model(**r)  # Создаем объект модели
                db.session.add(obj)  # Добавляем в сессию
            db.session.commit()  # Сохраняем изменения

    # Пытаемся импортировать данные для каждой таблицы
    try_import("students", Student)
    try_import("courses", Course)
    try_import("grades", Grade)
    try_import("logs", Log)



def load_data():
    """Загружает все данные из базы данных в pandas DataFrames для анализа"""
    # Убеждаемся, что база данных и схема созданы
    ensure_data_dir()

    # Функция для загрузки таблицы в DataFrame
    def table_df(model, cols=None):
        try:
            df = pd.read_sql_table(model.__tablename__, db.engine)  # Читаем таблицу из БД
        except ValueError:
            # Таблица еще не существует
            df = pd.DataFrame(columns=cols or [])
        return df

    # Загружаем данные из всех таблиц
    students = table_df(Student, cols=["id", "name", "group", "imported_at", "import_batch_id"])
    courses = table_df(Course, cols=["course_id", "course_name", "imported_at", "import_batch_id"])
    grades = table_df(Grade, cols=["id", "student_id", "course_id", "grade", "imported_at", "import_batch_id"])
    logs = table_df(Log, cols=["id", "student_id", "course_id", "action", "date", "imported_at", "import_batch_id"])

    # Удаляем автоинкрементные ID из grades и logs (они не нужны для анализа)
    if "id" in grades.columns:
        grades = grades.drop(columns=["id"])
    if "id" in logs.columns:
        logs = logs.drop(columns=["id"])

    # Возвращаем кортеж из четырех DataFrames
    return students, courses, grades, logs

def compute_grade_metrics(students, courses, grades, pass_threshold=50):
    """Вычисляет метрики качества обучения на основе оценок студентов

    Args:
        students: DataFrame с данными студентов
        courses: DataFrame с данными курсов
        grades: DataFrame с оценками
        pass_threshold: порог сдачи (баллы)

    Returns:
        dict: словарь с вычисленными метриками
    """
    total_students = len(students)  # Общее количество студентов
    course_map = courses.set_index("course_id")["course_name"].to_dict()  # Словарь для быстрого поиска названий курсов

    # Средние оценки по курсам
    avg_by_course = grades.groupby("course_id")["grade"].mean().reset_index()
    avg_by_course["course_name"] = avg_by_course["course_id"].map(course_map)
    avg_by_course["grade"] = avg_by_course["grade"].round(2)

    # Итоговые оценки по студентам и курсам (усреднение по всем оценкам студента за курс)
    final_by_student_course = (
        grades.groupby(["course_id", "student_id"])["grade"]
        .mean()
        .reset_index()
        .rename(columns={"grade": "final_grade"})
    )

    # Процент сдачи по курсам
    pass_rate = final_by_student_course.copy()
    pass_rate["passed"] = pass_rate["final_grade"] >= pass_threshold  # Определяем, сдал ли студент курс
    pass_rate = (
        pass_rate.groupby("course_id")["passed"]
        .mean()  # Вычисляем долю сдавших
        .reset_index()
        .rename(columns={"passed": "pass_rate"})
    )
    pass_rate["course_name"] = pass_rate["course_id"].map(course_map)
    pass_rate["pass_rate"] = (pass_rate["pass_rate"] * 100).round(1)  # Преобразуем в проценты
    pass_rate = pass_rate[["course_name", "pass_rate"]]

    # Студенты, требующие внимания (оценка ниже порога)
    lagging = final_by_student_course[final_by_student_course["final_grade"] < pass_threshold].copy()
    lagging = lagging.merge(students, left_on="student_id", right_on="id", how="left")  # Добавляем данные студентов
    lagging["course_name"] = lagging["course_id"].map(course_map)
    lagging["final_grade"] = lagging["final_grade"].round(2)
    lagging = lagging[["student_id", "name", "group", "course_name", "final_grade"]].sort_values(
        ["course_name", "final_grade"]  # Сортируем по курсу и оценке
    )

    # Топ студентов по итоговым оценкам
    top_students = final_by_student_course.copy()
    top_students = top_students.merge(students, left_on="student_id", right_on="id", how="left")
    top_students["course_name"] = top_students["course_id"].map(course_map)
    top_students["final_grade"] = top_students["final_grade"].round(2)
    top_students = top_students[["student_id", "name", "group", "course_name", "final_grade"]].sort_values(
        "final_grade", ascending=False  # Сортируем по убыванию оценки
    ).head(5)  # Берем топ-5

    # Гистограмма распределения оценок
    bins = [0, 50, 60, 70, 80, 90, 101]  # Интервалы оценок
    labels = ["0–49", "50–59", "60–69", "70–79", "80–89", "90–100"]

    if len(final_by_student_course) == 0:
        histogram = {"labels": labels, "values": [0] * len(labels)}  # Пустая гистограмма
    else:
        hist = pd.cut(final_by_student_course["final_grade"], bins=bins, labels=labels, right=False)
        hist_counts = hist.value_counts().reindex(labels, fill_value=0)
        histogram = {"labels": labels, "values": hist_counts.tolist()}

    # Круговая диаграмма: распределение по категориям оценок
    if len(final_by_student_course) == 0:
        grade_pie = {"labels": ["Отлично (90-100)", "Хорошо (70-89)", "Удовлетворительно (50-69)", "Неудовлетворительно (0-49)"], "values": [0, 0, 0, 0]}
    else:
        # Вычисляем количество студентов в каждой категории
        excellent = len(final_by_student_course[final_by_student_course["final_grade"] >= 90])
        good = len(final_by_student_course[(final_by_student_course["final_grade"] >= 70) & (final_by_student_course["final_grade"] < 90)])
        satisfactory = len(final_by_student_course[(final_by_student_course["final_grade"] >= 50) & (final_by_student_course["final_grade"] < 70)])
        poor = len(final_by_student_course[final_by_student_course["final_grade"] < 50])

        grade_pie = {
            "labels": ["Отлично (90-100)", "Хорошо (70-89)", "Удовлетворительно (50-69)", "Неудовлетворительно (0-49)"],
            "values": [excellent, good, satisfactory, poor]
        }

    # Возвращаем все вычисленные метрики
    return {
        "total_students": total_students,
        "avg_by_course": avg_by_course.to_dict("records"),
        "pass_rate": pass_rate.to_dict("records"),
        "lagging": lagging.to_dict("records"),
        "top_students": top_students.to_dict("records"),
        "histogram": histogram,
        "grade_pie": grade_pie,
        "pass_threshold": pass_threshold,
    }

def compute_activity_metrics(students, logs, course_id=None, days=14):
    """Вычисляет метрики активности студентов за указанный период

    Args:
        students: DataFrame с данными студентов
        logs: DataFrame с логами действий
        course_id: ID курса для фильтрации (опционально)
        days: количество дней для анализа (по умолчанию 14)

    Returns:
        dict: метрики активности за период
    """
    # Проверяем наличие данных логов
    if logs is None or len(logs) == 0:
        return {
            "activity": {"labels": [], "values": []},  # Пустые данные активности
            "active_students_count": 0,  # Количество активных студентов
            "inactive_students_count": len(students),  # Все студенты неактивны
            "top_active": [],  # Нет топ-активных студентов
        }

    logs = logs.copy()
    # Преобразуем даты и очищаем данные
    logs["date"] = pd.to_datetime(logs["date"], errors="coerce")
    logs = logs.dropna(subset=["date"])  # Удаляем записи без даты

    # Преобразуем ID в числа и удаляем некорректные
    logs["course_id"] = pd.to_numeric(logs["course_id"], errors="coerce")
    logs["student_id"] = pd.to_numeric(logs["student_id"], errors="coerce")
    logs = logs.dropna(subset=["course_id", "student_id"])
    logs["course_id"] = logs["course_id"].astype(int)
    logs["student_id"] = logs["student_id"].astype(int)

    # Фильтруем по курсу, если указан
    if course_id is not None:
        logs = logs[logs["course_id"] == course_id]

    # Если после фильтрации нет данных
    if len(logs) == 0:
        return {
            "activity": {"labels": [], "values": []},
            "active_students_count": 0,
            "inactive_students_count": len(students),
            "top_active": [],
        }

    # Определяем временное окно анализа
    max_day = logs["date"].max().normalize()  # Последний день с данными
    start_day = max_day - pd.Timedelta(days=days - 1)  # Начало периода
    logs_window = logs[(logs["date"] >= start_day) & (logs["date"] <= max_day)]  # Логи за период

    # Группируем действия по дням
    per_day = logs_window.groupby(logs_window["date"].dt.date).size()
    # Создаем полный диапазон дат для заполнения пропусков
    all_days = pd.date_range(start_day, max_day, freq="D").date
    per_day = per_day.reindex(all_days, fill_value=0)  # Заполняем дни без активности нулями

    # Форматируем метки для диаграммы
    labels = [d.strftime("%d.%m") for d in pd.to_datetime(per_day.index)]
    values = per_day.tolist()

    # Определяем активных и неактивных студентов
    active_ids = set(logs_window["student_id"].unique().tolist())  # ID активных студентов
    all_ids = set(students["id"].astype(int).unique().tolist())  # Все ID студентов
    inactive_ids = list(all_ids - active_ids)  # ID неактивных студентов

    # Находим топ-5 самых активных студентов
    top = logs_window.groupby("student_id").size().reset_index(name="events")
    top = top.merge(students, left_on="student_id", right_on="id", how="left")
    top = top[["name", "group", "events"]].sort_values("events", ascending=False).head(5)

    # Возвращаем метрики активности
    return {
        "activity": {"labels": labels, "values": values},  # Данные для графика активности
        "active_students_count": len(active_ids),  # Количество активных студентов
        "inactive_students_count": len(inactive_ids),  # Количество неактивных студентов
        "top_active": top.to_dict("records"),  # Топ-активные студенты
    }


def create_excel_report(metrics):
    """Создание Excel отчёта с метриками аналитики

    Args:
        metrics: словарь с вычисленными метриками из compute_grade_metrics

    Returns:
        BytesIO: объект с Excel файлом в памяти
    """
    output = io.BytesIO()  # Создаем объект для хранения файла в памяти

    # Проверяем и обеспечиваем, что все ключи существуют и не None
    required_keys = ['avg_by_course', 'pass_rate', 'lagging', 'top_students']
    for key in required_keys:
        if key not in metrics or metrics[key] is None:
            metrics[key] = []  # Устанавливаем пустой список, если ключ отсутствует или None

    # Проверяем histogram
    if 'histogram' not in metrics or metrics['histogram'] is None:
        metrics['histogram'] = {'labels': [], 'values': []}

    try:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Лист 1: Средние оценки по курсам
            df_course_avg = pd.DataFrame(metrics['avg_by_course'])
            # Заменяем None и NaN на подходящие значения
            df_course_avg = df_course_avg.fillna({'course_name': 'Unknown', 'grade': 0})
            df_course_avg.to_excel(writer, sheet_name='Average Grades', index=False)

            # Лист 2: Процент сдачи по курсам
            df_pass_rate = pd.DataFrame(metrics['pass_rate'])
            df_pass_rate = df_pass_rate.fillna({'course_name': 'Unknown', 'pass_rate': 0})
            df_pass_rate.to_excel(writer, sheet_name='Pass Rate', index=False)

            # Лист 3: Студенты, требующие внимания (низкие оценки)
            df_lagging = pd.DataFrame(metrics['lagging'])
            df_lagging = df_lagging.fillna({'name': 'Unknown', 'group': 'Unknown', 'course_name': 'Unknown', 'final_grade': 0})
            df_lagging.to_excel(writer, sheet_name='At Risk Students', index=False)

            # Лист 4: Топ студентов (высокие оценки)
            df_top = pd.DataFrame(metrics['top_students'])
            df_top = df_top.fillna({'name': 'Unknown', 'group': 'Unknown', 'course_name': 'Unknown', 'final_grade': 0})
            df_top.to_excel(writer, sheet_name='Top Students', index=False)

            # Лист 5: Распределение оценок (гистограмма)
            df_histogram = pd.DataFrame({
                'Grade Range': metrics['histogram']['labels'],
                'Count': metrics['histogram']['values']
            })
            df_histogram.to_excel(writer, sheet_name='Grade Distribution', index=False)
    except Exception as e:
        # Если openpyxl не работает, пробуем xlsxwriter
        output = io.BytesIO()
        try:
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # Повторяем тот же код
                df_course_avg = pd.DataFrame(metrics['avg_by_course'])
                df_course_avg = df_course_avg.fillna({'course_name': 'Unknown', 'grade': 0})
                df_course_avg.to_excel(writer, sheet_name='Average Grades', index=False)

                df_pass_rate = pd.DataFrame(metrics['pass_rate'])
                df_pass_rate = df_pass_rate.fillna({'course_name': 'Unknown', 'pass_rate': 0})
                df_pass_rate.to_excel(writer, sheet_name='Pass Rate', index=False)

                df_lagging = pd.DataFrame(metrics['lagging'])
                df_lagging = df_lagging.fillna({'name': 'Unknown', 'group': 'Unknown', 'course_name': 'Unknown', 'final_grade': 0})
                df_lagging.to_excel(writer, sheet_name='At Risk Students', index=False)

                df_top = pd.DataFrame(metrics['top_students'])
                df_top = df_top.fillna({'name': 'Unknown', 'group': 'Unknown', 'course_name': 'Unknown', 'final_grade': 0})
                df_top.to_excel(writer, sheet_name='Top Students', index=False)

                df_histogram = pd.DataFrame({
                    'Grade Range': metrics['histogram']['labels'],
                    'Count': metrics['histogram']['values']
                })
                df_histogram.to_excel(writer, sheet_name='Grade Distribution', index=False)
        except Exception as e2:
            raise Exception(f"Failed to create Excel with both engines: openpyxl error: {str(e)}, xlsxwriter error: {str(e2)}")

    output.seek(0)  # Перемещаем указатель в начало файла
    return output


def create_pdf_report(metrics, report_title="Analytics Report"):
    """Создание HTML отчёта (сохраняйте как PDF через браузер Ctrl+P)

    Args:
        metrics: словарь с метриками аналитики
        report_title: заголовок отчета

    Returns:
        str: HTML содержимое отчета
    """
    from datetime import datetime

    # Подготовка данных для таблиц отчета
    courses_data = metrics['avg_by_course']  # Данные средних оценок
    pass_rate_data = metrics['pass_rate']  # Данные процента сдачи
    lagging_data = metrics['lagging'][:10]  # Топ-10 студентов с низкими оценками
    top_students_data = metrics['top_students']  # Топ студентов

    # Рендеринг HTML с помощью шаблона
    html_content = render_template(
        'report.html',
        report_title=report_title,
        generation_date=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        total_students=metrics.get('total_students', 0),
        total_courses=len(courses_data),
        courses_data=courses_data,
        pass_rate_data=pass_rate_data,
        lagging_data=lagging_data,
        top_students_data=top_students_data
    )

    return html_content

@app.route("/login", methods=["GET", "POST"])
def login():
    """Обработка входа в систему с защитой от brute-force атак"""
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()  # Получаем имя пользователя
        password = request.form["password"]  # Получаем пароль

        # Ключи для отслеживания попыток входа в сессии
        login_attempts_key = f"login_attempts:{username}"
        login_timeout_key = f"login_timeout:{username}"

        # Проверяем, не заблокирован ли аккаунт
        if login_timeout_key in session:
            timeout_end = session[login_timeout_key]
            if datetime.now().isoformat() < timeout_end:
                # Аккаунт все еще заблокирован
                remaining_minutes = (datetime.fromisoformat(timeout_end) - datetime.now()).seconds // 60
                error = f"Слишком много неверных попыток. Попробуйте через {remaining_minutes} мин."
            else:
                # Время блокировки истекло, сбрасываем счетчики
                session.pop(login_attempts_key, None)
                session.pop(login_timeout_key, None)

        if not error:
            # Получаем данные пользователя из словаря USERS
            user = USERS.get(username)

            # Проверяем пароль с помощью bcrypt
            if user and bcrypt.check_password_hash(user["password_hash"], password):
                # Успешный вход: сбрасываем счетчики и устанавливаем сессию
                session.pop(login_attempts_key, None)
                session.pop(login_timeout_key, None)
                session["user"] = username  # Сохраняем имя пользователя в сессии
                session["role"] = user["role"]  # Сохраняем роль пользователя
                session.setdefault("pass_threshold", 50)  # Устанавливаем порог сдачи по умолчанию
                flash(f"Добро пожаловать, {username}!", "success")
                return redirect(url_for("index"))  # Перенаправляем на главную страницу
            else:
                # Неверный пароль: увеличиваем счетчик попыток
                attempts = session.get(login_attempts_key, 0) + 1
                session[login_attempts_key] = attempts

                if attempts >= LOGIN_ATTEMPTS_LIMIT:
                    # Превышен лимит попыток: блокируем аккаунт
                    timeout_end = (datetime.now() + timedelta(minutes=LOGIN_ATTEMPTS_TIMEOUT)).isoformat()
                    session[login_timeout_key] = timeout_end
                    error = f"Слишком много неверных попыток. Аккаунт заблокирован на {LOGIN_ATTEMPTS_TIMEOUT} минут."
                else:
                    remaining = LOGIN_ATTEMPTS_LIMIT - attempts
                    error = f"Неверный логин или пароль. Осталось попыток: {remaining}"

    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    """Выход из системы - очистка сессии пользователя"""
    session.clear()  # Очищаем все данные сессии
    return redirect(url_for("login"))  # Перенаправляем на страницу входа

@app.route("/", methods=["GET"])
@login_required
def index():
    """Главная страница дашборда с аналитикой и графиками"""
    # Загружаем данные из базы данных
    students, courses, grades, logs = load_data()

    # Получаем фильтры из параметров запроса
    selected_course = request.args.get("course_id", "")  # ID выбранного курса
    course_id = int(selected_course) if selected_course else None  # Преобразуем в int или None
    selected_group = request.args.get("group", "")

    # compute available groups from complete students list (before filtering)
    groups = sorted(students["group"].dropna().unique().tolist())

    # apply group filter to students and logs/grades
    if selected_group:
        students = students[students["group"] == selected_group].copy()
        grades = grades[grades["student_id"].isin(students["id"])]
        logs = logs[logs["student_id"].isin(students["id"])]

    # apply course filter to grades view only
    grades_view = grades
    if course_id is not None:
        grades_view = grades[grades["course_id"] == course_id].copy()

    threshold = int(session.get("pass_threshold", 50))

    grade_metrics = compute_grade_metrics(students, courses, grades_view, pass_threshold=threshold)
    activity_metrics = compute_activity_metrics(students, logs, course_id=course_id, days=14)

    # pagination for lagging students table
    lagging_page = int(request.args.get("lagging_page", 1))
    lagging_per_page = 10
    lagging_full = grade_metrics["lagging"]
    lagging_total = len(lagging_full)
    lagging_start = (lagging_page - 1) * lagging_per_page
    lagging_end = lagging_start + lagging_per_page
    lagging_paged = lagging_full[lagging_start:lagging_end]
    lagging_has_next = lagging_end < lagging_total
    lagging_has_prev = lagging_start > 0

    # get user theme preference from db
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"

    return render_template(
        "index.html",
        **{k: v for k, v in grade_metrics.items() if k != "lagging"},
        activity=activity_metrics["activity"],
        active_students_count=activity_metrics["active_students_count"],
        inactive_students_count=activity_metrics["inactive_students_count"],
        top_active=activity_metrics["top_active"],
        courses=courses.to_dict("records"),
        groups=groups,
        selected_course=course_id,
        selected_group=selected_group,
        lagging=lagging_paged,
        lagging_page=lagging_page,
        lagging_has_next=lagging_has_next,
        lagging_has_prev=lagging_has_prev,
        username=session["user"],
        role=session["role"],
        user_theme=user_theme,
    )

@app.route("/admin/settings", methods=["POST"])
@login_required
@role_required("admin")
def admin_settings():
    threshold = request.form.get("pass_threshold", "").strip()
    try:
        threshold_int = int(threshold)
        if not (0 <= threshold_int <= 100):
            raise ValueError
        session["pass_threshold"] = threshold_int
        flash("Порог сдачи обновлён", "success")
    except ValueError:
        flash("Порог должен быть числом от 0 до 100", "error")
    return redirect(url_for("index"))

@app.route("/admin/upload", methods=["POST"])
@login_required
@role_required("admin")
def admin_upload():
    # import CSV data directly into the database
    ensure_data_dir()
    allowed = {"students", "courses", "grades", "logs"}
    filetype = request.form.get("filetype", "").strip()

    if filetype not in allowed:
        flash("Неверный тип файла", "error")
        return redirect(url_for("index"))

    f = request.files.get("file")
    if not f or f.filename == "":
        flash("Файл не выбран", "error")
        return redirect(url_for("index"))

    # read into pandas then push to appropriate table using the ORM
    try:
        df = pd.read_csv(f)
    except Exception as e:
        flash(f"Ошибка при чтении CSV: {e}", "error")
        return redirect(url_for("index"))

    # convert to records and insert
    records = df.to_dict(orient="records")

    if filetype == "students":
        Student.query.delete()
        for r in records:
            # allow missing id (autoincrement)
            student = Student(**r)
            db.session.add(student)
    elif filetype == "courses":
        Course.query.delete()
        for r in records:
            course = Course(**r)
            db.session.add(course)
    elif filetype == "grades":
        Grade.query.delete()
        for r in records:
            grade = Grade(**r)
            db.session.add(grade)
    elif filetype == "logs":
        Log.query.delete()
        for r in records:
            log = Log(**r)
            db.session.add(log)
    db.session.commit()

    flash(f"Данные из {filetype}.csv импортированы в базу", "success")
    return redirect(url_for("index"))


# simple viewer for raw table data, admin only
@app.route("/admin/view/<table>")
@login_required
@role_required("admin")
def admin_view_table(table):
    # pagination & search for admin list view
    valid = ["students", "courses", "grades", "logs"]
    if table not in valid:
        flash("Неверная таблица", "error")
        return redirect(url_for("index"))

    students, courses, grades, logs = load_data()
    mapping = {
        "students": students,
        "courses": courses,
        "grades": grades,
        "logs": logs,
    }
    df = mapping[table]

    # apply search filter if provided
    query = request.args.get("q", "").strip()
    if query:
        # case‑insensitive search across all columns
        mask = False
        for col in df.columns:
            mask = mask | df[col].astype(str).str.contains(query, case=False, na=False)
        df = df[mask]

    # pagination parameters
    page = int(request.args.get("page", 1))
    per_page = 20
    total = len(df)
    start = (page - 1) * per_page
    end = start + per_page
    df_page = df.iloc[start:end]
    has_next = end < total
    has_prev = start > 0

    # get user theme preference from db
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"

    return render_template(
        "view_table.html",
        table_name=table,
        records=df_page.to_dict("records"),
        columns=list(df.columns),
        username=session.get("user"),
        role=session.get("role"),
        pass_threshold=session.get("pass_threshold", 50),
        page=page,
        has_next=has_next,
        has_prev=has_prev,
        query=query,
        user_theme=user_theme,
    )


@app.route("/export/excel")
@login_required
def export_excel():
    """Export analytics to Excel"""
    try:
        students, courses, grades, logs = load_data()
        threshold = int(session.get("pass_threshold", 50))
        metrics = compute_grade_metrics(students, courses, grades, pass_threshold=threshold)
        
        excel_file = create_excel_report(metrics)
        filename = f"analytics_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        return send_file(
            excel_file,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f"Ошибка при экспорте в Excel: {str(e)}", "error")
        return redirect(url_for("index"))


@app.route("/export/pdf")
@login_required
def export_pdf():
    """Export analytics as HTML (для сохранения как PDF используйте Ctrl+P)"""
    try:
        students, courses, grades, logs = load_data()
        threshold = int(session.get("pass_threshold", 50))
        metrics = compute_grade_metrics(students, courses, grades, pass_threshold=threshold)
        
        html_content = create_pdf_report(metrics, "Аналитика качества обучения")
        html_file = io.BytesIO(html_content.encode('utf-8'))
        html_file.seek(0)
        filename = f"analytics_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        
        return send_file(
            html_file,
            mimetype="text/html; charset=utf-8",
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        flash(f"Ошибка при экспорте отчёта: {str(e)}", "error")
        return redirect(url_for("index"))


@app.route("/api/cache-clear", methods=["POST"])
@login_required
@role_required("admin")
def api_cache_clear():
    """Clear application cache (admin only)"""
    cache.clear()
    flash("Кэш очищен успешно", "success")
    return redirect(url_for("admin_panel"))


@app.route("/api/theme", methods=["POST"])
@login_required
def api_set_theme():
    # save theme preference to database
    theme = request.json.get("theme", "light")
    user = session["user"]
    settings = UserSettings.query.filter_by(username=user).first()
    if not settings:
        settings = UserSettings(username=user, theme=theme)
        db.session.add(settings)
    else:
        settings.theme = theme
    db.session.commit()
    return {"status": "ok", "theme": theme}


@app.route("/api/settings/export", methods=["GET"])
@login_required
def api_export_settings():
    # export user settings as JSON
    user = session["user"]
    settings = UserSettings.query.filter_by(username=user).first()
    export = {
        "username": user,
        "theme": settings.theme if settings else "light",
        "settings": settings.settings_json if settings else "{}",
    }
    return export


@app.route("/api/settings/import", methods=["POST"])
@login_required
def api_import_settings():
    # import user settings from JSON
    user = session["user"]
    data = request.json
    settings = UserSettings.query.filter_by(username=user).first()
    if not settings:
        settings = UserSettings(username=user)
        db.session.add(settings)
    settings.theme = data.get("theme", "light")
    settings.settings_json = data.get("settings", "{}")
    db.session.commit()
    return {"status": "ok"}


@app.route("/courses")
@login_required
def courses_view():
    students, courses, grades, logs = load_data()
    
    # Create course enrollment list
    course_enrollments = []
    for _, course in courses.iterrows():
        course_id = course["course_id"]
        course_name = course["course_name"]
        
        # Get students with grades in this course
        course_grades = grades[grades["course_id"] == course_id]
        enrolled_students = students[students["id"].isin(course_grades["student_id"].unique())]
        
        # Calculate course metrics
        avg_grade = course_grades["grade"].mean() if len(course_grades) > 0 else 0
        enrolled_count = len(enrolled_students)
        
        course_enrollments.append({
            "course_id": course_id,
            "course_name": course_name,
            "enrolled_count": enrolled_count,
            "avg_grade": round(avg_grade, 2),
            "students": enrolled_students.sort_values("name").to_dict("records")
        })
    
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"
    
    return render_template(
        "courses.html",
        courses=course_enrollments,
        username=session["user"],
        role=session["role"],
        user_theme=user_theme
    )


@app.route("/students")
@login_required
def students_view():
    students, _, _, _ = load_data()
    
    # Group students by group
    groups = students.groupby("group").apply(
        lambda g: g.sort_values("name").to_dict("records")
    ).to_dict()
    
    # Sort groups alphabetically
    sorted_groups = dict(sorted(groups.items()))
    
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"
    
    return render_template(
        "students.html",
        groups=sorted_groups,
        total_students=len(students),
        username=session["user"],
        role=session["role"],
        user_theme=user_theme
    )


@app.route("/admin", methods=["GET", "POST"])
@login_required
@role_required("admin")
def admin_panel():
    if request.method == "POST":
        action = request.form.get("action")
        
        if action == "update_threshold":
            threshold = request.form.get("pass_threshold", "").strip()
            try:
                threshold_int = int(threshold)
                if not (0 <= threshold_int <= 100):
                    raise ValueError
                session["pass_threshold"] = threshold_int
                flash("Порог сдачи обновлён", "success")
            except ValueError:
                flash("Порог должен быть числом от 0 до 100", "error")
        
        elif action == "upload_csv":
            table_type = request.form.get("table_type")
            files = request.files.getlist("files") or request.files.getlist("file")

            if not files:
                flash("Пожалуйста, выберите CSV файл(ы)", "error")
            else:
                successes = []
                errors = []

                def import_file(f, table_type_hint=None):
                    # Read CSV
                    df = pd.read_csv(f)

                    # determine import period label (e.g., 2026-03)
                    now = datetime.utcnow()
                    label = now.strftime("%Y-%m")
                    if (table_type_hint == "logs") and ("date" in df.columns):
                        try:
                            parsed = pd.to_datetime(df["date"], errors="coerce")
                            if not parsed.isna().all():
                                max_date = parsed.max()
                                label = max_date.strftime("%Y-%m")
                        except Exception:
                            pass

                    batch = ImportBatch(label=label, source=table_type_hint)
                    db.session.add(batch)
                    db.session.commit()

                    imported_at = datetime.utcnow()

                    if table_type_hint == "students":
                        for _, row in df.iterrows():
                            try:
                                student_id = int(row["id"])
                            except Exception:
                                continue
                            st = Student.query.get(student_id)
                            if st:
                                st.name = row.get("name")
                                st.group = row.get("group")
                                st.imported_at = imported_at
                                st.import_batch_id = batch.id
                            else:
                                st = Student(
                                    id=student_id,
                                    name=row.get("name"),
                                    group=row.get("group"),
                                    imported_at=imported_at,
                                    import_batch_id=batch.id,
                                )
                                db.session.add(st)
                        db.session.commit()
                        return f"Импортировано {len(df)} студентов"

                    elif table_type_hint == "courses":
                        for _, row in df.iterrows():
                            try:
                                course_id = int(row["course_id"])
                            except Exception:
                                continue
                            c = Course.query.get(course_id)
                            if c:
                                c.course_name = row.get("course_name")
                                c.imported_at = imported_at
                                c.import_batch_id = batch.id
                            else:
                                c = Course(
                                    course_id=course_id,
                                    course_name=row.get("course_name"),
                                    imported_at=imported_at,
                                    import_batch_id=batch.id,
                                )
                                db.session.add(c)
                        db.session.commit()
                        return f"Импортировано {len(df)} курсов"

                    elif table_type_hint == "grades":
                        for _, row in df.iterrows():
                            try:
                                g = Grade(
                                    student_id=int(row["student_id"]),
                                    course_id=int(row["course_id"]),
                                    grade=float(row["grade"]),
                                    imported_at=imported_at,
                                    import_batch_id=batch.id,
                                )
                                db.session.add(g)
                            except Exception:
                                continue
                        db.session.commit()
                        return f"Импортировано {len(df)} оценок (добавлено)"

                    elif table_type_hint == "logs":
                        for _, row in df.iterrows():
                            try:
                                l = Log(
                                    student_id=int(row["student_id"]),
                                    course_id=int(row["course_id"]),
                                    action=row.get("action"),
                                    date=row.get("date"),
                                    imported_at=imported_at,
                                    import_batch_id=batch.id,
                                )
                                db.session.add(l)
                            except Exception:
                                continue
                        db.session.commit()
                        return f"Импортировано {len(df)} логов (добавлено)"

                    return "Неизвестный тип данных"

                for f in files:
                    if not f or not f.filename or not f.filename.lower().endswith(".csv"):
                        errors.append("Один из файлов не является CSV")
                        continue

                    # Determine type either from selector or from filename
                    chosen_type = table_type
                    if not chosen_type or chosen_type == "auto" or len(files) > 1:
                        fname = f.filename.lower()
                        for candidate in ["students", "courses", "grades", "logs"]:
                            if candidate in fname:
                                chosen_type = candidate
                                break

                    if chosen_type not in ["students", "courses", "grades", "logs"]:
                        errors.append(
                            f"Не удалось определить тип для {f.filename}. Добавьте в имя файла students/courses/grades/logs или выберите тип."
                        )
                        continue

                    try:
                        msg = import_file(f, chosen_type)
                        successes.append(f"{f.filename}: {msg}")
                    except Exception as e:
                        errors.append(f"{f.filename}: ошибка при импорте ({e})")

                for m in successes:
                    flash(m, "success")
                for m in errors:
                    flash(m, "error")

        elif action == "reset_data":
            # полностью очистить все загруженные данные (без удаления настроек)
            Grade.query.delete()
            Log.query.delete()
            Student.query.delete()
            Course.query.delete()
            ImportBatch.query.delete()
            db.session.commit()

            # prevent automatic re-import from existing CSV files until user uploads new data
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                open(AUTO_IMPORT_DISABLED_FILE, "w", encoding="utf-8").close()
            except Exception:
                pass

            flash("Все данные успешно удалены", "success")

        return redirect(url_for("admin_panel"))
    
    threshold = int(session.get("pass_threshold", 50))
    
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"
    
    return render_template(
        "admin.html",
        pass_threshold=threshold,
        username=session["user"],
        role=session["role"],
        user_theme=user_theme
    )


@app.route("/analytics")
@login_required
def analytics_view():
    students, courses, grades, logs = load_data()

    # make sure date columns are parsed
    logs['date'] = pd.to_datetime(logs['date'], errors='coerce')
    grades['imported_at'] = pd.to_datetime(grades.get('imported_at'), errors='coerce')
    logs['imported_at'] = pd.to_datetime(logs.get('imported_at'), errors='coerce')

    # Choose a time field for logs (prefer explicit date if available)
    logs['event_date'] = logs['date'].fillna(logs['imported_at'])
    grades['event_date'] = grades['imported_at']

    # Determine which months are available based on imports
    def month_label(dt):
        if pd.isna(dt):
            return None
        return dt.strftime('%Y-%m')

    all_months = sorted({m for m in logs['event_date'].map(month_label).dropna().unique()} | {m for m in grades['event_date'].map(month_label).dropna().unique()})

    # If we have no months (no data), fall back to current month
    if not all_months:
        all_months = [date.today().strftime('%Y-%m')]

    # Period selection (months back)
    selected_months_count = request.args.get('months', '3')
    if selected_months_count == 'all':
        selected_months = all_months
    else:
        try:
            n = int(selected_months_count)
            selected_months = all_months[-n:]
        except Exception:
            selected_months = all_months[-3:]
            selected_months_count = '3'

    # Ensure there is at least one month
    if not selected_months:
        selected_months = all_months[-1:]

    # Filter data by selected months
    grades_filtered = grades[grades['event_date'].map(month_label).isin(selected_months)].copy()
    logs_filtered = logs[logs['event_date'].map(month_label).isin(selected_months)].copy()

    # Build descriptive labels for UI
    MONTH_NAMES_RU = [
        "январь", "февраль", "март", "апрель", "май", "июнь",
        "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
    ]

    def human_month(label):
        try:
            y, m = label.split('-')
            m = int(m)
            return f"{MONTH_NAMES_RU[m-1]} {y}"
        except Exception:
            return label

    display_months = [human_month(m) for m in selected_months]
    period_label = ", ".join(display_months)

    # Compute monthly trend data
    trend_data = []
    for month in selected_months:
        month_grades = grades_filtered[grades_filtered['event_date'].dt.strftime('%Y-%m') == month]
        avg_grade = month_grades['grade'].mean() if len(month_grades) > 0 else 0

        month_logs = logs_filtered[logs_filtered['event_date'].dt.strftime('%Y-%m') == month]
        activity_count = len(month_logs)

        enrolled = len(students)

        trend_data.append({
            'month': month,
            'avg_grade': round(avg_grade, 1),
            'activity': activity_count,
            'enrolled': enrolled,
        })

    # Current snapshot (last month in range)
    current_avg = trend_data[-1]['avg_grade'] if trend_data else 0
    current_activity = trend_data[-1]['activity'] if trend_data else 0
    current_enrolled = len(students)

    # Group activity by week for recent trends (based on logs)
    logs_filtered['week'] = logs_filtered['event_date'].dt.strftime('%Y-%U')
    weekly_activity = logs_filtered.groupby('week').size().reset_index(name='events')
    weekly_activity = weekly_activity.sort_values('week').tail(8)

    # Predict dropout risk (based on filtered period)
    dropout_risk = []
    for _, student in students.iterrows():
        student_id = student['id']
        student_grades = grades_filtered[grades_filtered['student_id'] == student_id]
        student_logs = logs_filtered[logs_filtered['student_id'] == student_id]

        if len(student_grades) == 0:
            continue

        avg_grade = student_grades['grade'].mean()
        total_activity = len(student_logs)
        courses_taken = len(student_grades)

        grade_risk = max(0, (70 - avg_grade) / 30)
        activity_risk = max(0, (50 - total_activity / courses_taken) / 50) if courses_taken else 0

        total_risk = (grade_risk + activity_risk) / 2
        risk_level = 'Низкий' if total_risk < 0.3 else 'Средний' if total_risk < 0.7 else 'Высокий'

        dropout_risk.append({
            'student_id': student_id,
            'name': student['name'],
            'group': student['group'],
            'avg_grade': round(avg_grade, 1),
            'total_activity': total_activity,
            'risk_level': risk_level,
            'risk_score': round(total_risk * 100, 1),
        })

    dropout_risk = sorted(dropout_risk, key=lambda x: x['risk_score'], reverse=True)[:10]

    # Performance predictions
    if len(trend_data) >= 3:
        grades_trend = [d['avg_grade'] for d in trend_data[-3:]]
        if len(grades_trend) >= 2:
            slope = (grades_trend[-1] - grades_trend[0]) / (len(grades_trend) - 1)
            next_month_prediction = grades_trend[-1] + slope
            next_month_prediction = max(0, min(100, next_month_prediction))
        else:
            next_month_prediction = grades_trend[-1]
    else:
        next_month_prediction = current_avg
    
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"
    
    return render_template(
        "analytics.html",
        trend_data=trend_data,
        weekly_activity=weekly_activity.to_dict("records"),
        dropout_risk=dropout_risk,
        next_month_prediction=round(next_month_prediction, 1),
        current_avg=round(current_avg, 1),
        period_label=period_label,
        selected_months_count=selected_months_count,
        available_months=all_months,
        username=session["user"],
        role=session["role"],
        user_theme=user_theme
    )


@app.route("/student/<int:student_id>")
@login_required
def student_detail(student_id):
    students, courses, grades, logs = load_data()
    
    # Get student info
    student = students[students["id"] == student_id]
    if student.empty:
        flash("Студент не найден", "error")
        return redirect(url_for("students_view"))
    
    student = student.iloc[0]
    
    # Get student's grades
    student_grades = grades[grades["student_id"] == student_id].copy()
    student_grades = student_grades.merge(courses, on="course_id")
    
    # Get student's activity logs
    student_logs = logs[logs["student_id"] == student_id].copy()
    student_logs = student_logs.merge(courses, on="course_id")
    
    # Calculate metrics
    total_courses = len(student_grades)
    passed_courses = len(student_grades[student_grades["grade"] >= int(session.get("pass_threshold", 50))])
    avg_grade = student_grades["grade"].mean() if len(student_grades) > 0 else 0
    
    # Group activity by date
    activity_by_date = student_logs.groupby("date").size().reset_index(name="events")
    activity_by_date = activity_by_date.sort_values("date")
    
    # Group activity by course
    activity_by_course = student_logs.groupby("course_name").size().reset_index(name="events")
    activity_by_course = activity_by_course.sort_values("events", ascending=False)
    
    # Compare with group average
    group_students = students[students["group"] == student["group"]]
    group_grades = grades[grades["student_id"].isin(group_students["id"])]
    group_avg = group_grades["grade"].mean() if len(group_grades) > 0 else 0
    
    # Recent activity (last 10 events)
    recent_logs = student_logs.sort_values("date", ascending=False).head(10)
    
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"
    
    return render_template(
        "student_detail.html",
        student=student,
        grades=student_grades.to_dict("records"),
        activity_by_date=activity_by_date.to_dict("records"),
        activity_by_course=activity_by_course.to_dict("records"),
        recent_logs=recent_logs.to_dict("records"),
        total_courses=total_courses,
        passed_courses=passed_courses,
        avg_grade=round(avg_grade, 2),
        group_avg=round(group_avg, 2),
        pass_threshold=int(session.get("pass_threshold", 50)),
        username=session["user"],
        role=session["role"],
        user_theme=user_theme
    )


if __name__ == "__main__":
    app.run(debug=True)
