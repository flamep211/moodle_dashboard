from datetime import datetime
from database import db

class Student(db.Model):
    __tablename__ = "students"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    group = db.Column(db.String)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)

class Course(db.Model):
    __tablename__ = "courses"
    course_id = db.Column(db.Integer, primary_key=True)
    course_name = db.Column(db.String, nullable=False)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)

class Grade(db.Model):
    __tablename__ = "grades"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.course_id"), nullable=False)
    grade = db.Column(db.Float, nullable=False)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)

class Log(db.Model):
    __tablename__ = "logs"
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey("students.id"), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey("courses.course_id"), nullable=False)
    action = db.Column(db.String)
    date = db.Column(db.String)
    imported_at = db.Column(db.DateTime, default=datetime.utcnow)
    import_batch_id = db.Column(db.Integer, db.ForeignKey("import_batches.id"), nullable=True)

class ImportBatch(db.Model):
    __tablename__ = "import_batches"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    label = db.Column(db.String, nullable=False)
    source = db.Column(db.String, nullable=False)

class UserSettings(db.Model):
    __tablename__ = "user_settings"
    username = db.Column(db.String, primary_key=True)
    theme = db.Column(db.String, default="light")
    settings_json = db.Column(db.Text, default="{}")
