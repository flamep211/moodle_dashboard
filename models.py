from datetime import datetime
from database import db


# Модели ORM для хранения данных приложения.
# Каждая модель соответствует таблице в sqlite и используется
# при импортe/экспорте и построении аналитики.

class Student(db.Model):
    __tablename__ = "students"
    # Уникальный идентификатор студента
    id = db.Column(db.Integer, primary_key=True)
    # Полное имя студента
    name = db.Column(db.String, nullable=False)
    # Группа/класс
    group = db.Column(db.String)
    # Время импорта/создания записи
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Связь с батчем импорта (если применимо)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)


class Course(db.Model):
    __tablename__ = "courses"
    # Идентификатор курса (возможно, id из Moodle)
    course_id = db.Column(db.Integer, primary_key=True)
    # Название курса
    course_name = db.Column(db.String, nullable=False)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)


class Grade(db.Model):
    __tablename__ = "grades"
    # Временная таблица оценок — каждая запись = оценка студента по курсу
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.course_id"), nullable=False)
    grade = db.Column(db.Float, nullable=False)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)


class Log(db.Model):
    __tablename__ = "logs"
    # Логи активности студентов: просмотр материала, отправка заданий и т.п.
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.course_id"), nullable=False)
    action = db.Column(db.String)
    # Храним дату как строку, т.к. часто импортируем из CSV в разном формате
    date = db.Column(db.String)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)


class ImportBatch(db.Model):
    __tablename__ = "import_batches"
    # Информация о каждой партии импорта (для аналитики и отката)
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    label = db.Column(db.String, nullable=False)
    source = db.Column(db.String, nullable=False)


class UserSettings(db.Model):
    __tablename__ = "user_settings"
    # Настройки пользователя (тема, сериализованные настройки и т.д.)
    username = db.Column(db.String, primary_key=True)
    theme = db.Column(db.String, default="light")
    settings_json = db.Column(db.Text, default="{}")
