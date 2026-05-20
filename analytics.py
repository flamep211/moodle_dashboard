import os
import io
from datetime import datetime, date, timedelta
from sqlalchemy import text

import pandas as pd
import numpy as np
from flask import render_template

from database import db
from models import Student, Course, Grade, Log

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
AUTO_IMPORT_DISABLED_FILE = os.path.join(DATA_DIR, ".no_auto_import")


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    db.create_all()

    def ensure_column(table, column, definition):
        conn = db.engine.connect()
        try:
            existing = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
        finally:
            conn.close()

    ensure_column("students", "imported_at", "DATETIME")
    ensure_column("students", "import_batch_id", "INTEGER")
    ensure_column("courses", "imported_at", "DATETIME")
    ensure_column("courses", "import_batch_id", "INTEGER")
    ensure_column("grades", "imported_at", "DATETIME")
    ensure_column("grades", "import_batch_id", "INTEGER")
    ensure_column("logs", "imported_at", "DATETIME")
    ensure_column("logs", "import_batch_id", "INTEGER")

    auto_import_enabled = not os.path.exists(AUTO_IMPORT_DISABLED_FILE)

    def try_import(table_name, model):
        if not auto_import_enabled:
            return
        path = os.path.join(DATA_DIR, f"{table_name}.csv")
        if os.path.exists(path) and model.query.count() == 0:
            try:
                df = pd.read_csv(path)
            except Exception:
                return
            recs = df.to_dict(orient="records")
            for r in recs:
                obj = model(**r)
                db.session.add(obj)
            db.session.commit()

    try_import("students", Student)
    try_import("courses", Course)
    try_import("grades", Grade)
    try_import("logs", Log)


def load_data():
    ensure_data_dir()

    def table_df(model, cols=None):
        try:
            df = pd.read_sql_table(model.__tablename__, db.engine)
        except ValueError:
            df = pd.DataFrame(columns=cols or [])
        return df

    students = table_df(Student, cols=["id", "name", "group", "imported_at", "import_batch_id"])
    courses = table_df(Course, cols=["course_id", "course_name", "imported_at", "import_batch_id"])
    grades = table_df(Grade, cols=["id", "student_id", "course_id", "grade", "imported_at", "import_batch_id"])
    logs = table_df(Log, cols=["id", "student_id", "course_id", "action", "date", "imported_at", "import_batch_id"])

    if "id" in grades.columns:
        grades = grades.drop(columns=["id"])
    if "id" in logs.columns:
        logs = logs.drop(columns=["id"])

    return students, courses, grades, logs


def compute_grade_metrics(students, courses, grades, pass_threshold=50):
    total_students = len(students)
    course_map = courses.set_index("course_id")["course_name"].to_dict()

    avg_by_course = grades.groupby("course_id")["grade"].mean().reset_index()
    avg_by_course["course_name"] = avg_by_course["course_id"].map(course_map)
    avg_by_course["grade"] = avg_by_course["grade"].round(2)

    final_by_student_course = (
        grades.groupby(["course_id", "student_id"])["grade"]
        .mean()
        .reset_index()
        .rename(columns={"grade": "final_grade"})
    )

    pass_rate = final_by_student_course.copy()
    pass_rate["passed"] = pass_rate["final_grade"] >= pass_threshold
    pass_rate = (
        pass_rate.groupby("course_id")["passed"]
        .mean()
        .reset_index()
        .rename(columns={"passed": "pass_rate"})
    )
    pass_rate["course_name"] = pass_rate["course_id"].map(course_map)
    pass_rate["pass_rate"] = (pass_rate["pass_rate"] * 100).round(1)
    pass_rate = pass_rate[["course_name", "pass_rate"]]

    lagging = final_by_student_course[final_by_student_course["final_grade"] < pass_threshold].copy()
    lagging = lagging.merge(students, left_on="student_id", right_on="id", how="left")
    lagging["course_name"] = lagging["course_id"].map(course_map)
    lagging["final_grade"] = lagging["final_grade"].round(2)
    lagging = lagging[["student_id", "name", "group", "course_name", "final_grade"]].sort_values(
        ["course_name", "final_grade"]
    )

    top_students = final_by_student_course.copy()
    top_students = top_students.merge(students, left_on="student_id", right_on="id", how="left")
    top_students["course_name"] = top_students["course_id"].map(course_map)
    top_students["final_grade"] = top_students["final_grade"].round(2)
    top_students = top_students[["student_id", "name", "group", "course_name", "final_grade"]].sort_values(
        "final_grade", ascending=False
    ).head(5)

    bins = [0, 50, 60, 70, 80, 90, 101]
    labels = ["0–49", "50–59", "60–69", "70–79", "80–89", "90–100"]

    if len(final_by_student_course) == 0:
        histogram = {"labels": labels, "values": [0] * len(labels)}
    else:
        hist = pd.cut(final_by_student_course["final_grade"], bins=bins, labels=labels, right=False)
        hist_counts = hist.value_counts().reindex(labels, fill_value=0)
        histogram = {"labels": labels, "values": hist_counts.tolist()}

    if len(final_by_student_course) == 0:
        grade_pie = {"labels": ["Отлично (90-100)", "Хорошо (70-89)", "Удовлетворительно (50-69)", "Неудовлетворительно (0-49)"], "values": [0, 0, 0, 0]}
    else:
        excellent = len(final_by_student_course[final_by_student_course["final_grade"] >= 90])
        good = len(final_by_student_course[(final_by_student_course["final_grade"] >= 70) & (final_by_student_course["final_grade"] < 90)])
        satisfactory = len(final_by_student_course[(final_by_student_course["final_grade"] >= 50) & (final_by_student_course["final_grade"] < 70)])
        poor = len(final_by_student_course[final_by_student_course["final_grade"] < 50])

        grade_pie = {
            "labels": ["Отлично (90-100)", "Хорошо (70-89)", "Удовлетворительно (50-69)", "Неудовлетворительно (0-49)"],
            "values": [excellent, good, satisfactory, poor]
        }

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
    if logs is None or len(logs) == 0:
        return {
            "activity": {"labels": [], "values": []},
            "active_students_count": 0,
            "inactive_students_count": len(students),
            "top_active": [],
        }

    logs = logs.copy()
    logs["date"] = pd.to_datetime(logs["date"], errors="coerce")
    logs = logs.dropna(subset=["date"])
    logs["course_id"] = pd.to_numeric(logs["course_id"], errors="coerce")
    logs["student_id"] = pd.to_numeric(logs["student_id"], errors="coerce")
    logs = logs.dropna(subset=["course_id", "student_id"])
    logs["course_id"] = logs["course_id"].astype(int)
    logs["student_id"] = logs["student_id"].astype(int)

    if course_id is not None:
        logs = logs[logs["course_id"] == course_id]

    if len(logs) == 0:
        return {
            "activity": {"labels": [], "values": []},
            "active_students_count": 0,
            "inactive_students_count": len(students),
            "top_active": [],
        }

    max_day = logs["date"].max().normalize()
    start_day = max_day - pd.Timedelta(days=days - 1)
    logs_window = logs[(logs["date"] >= start_day) & (logs["date"] <= max_day)]

    per_day = logs_window.groupby(logs_window["date"].dt.date).size()
    all_days = pd.date_range(start_day, max_day, freq="D").date
    per_day = per_day.reindex(all_days, fill_value=0)

    labels = [d.strftime("%d.%m") for d in pd.to_datetime(per_day.index)]
    values = per_day.tolist()

    active_ids = set(logs_window["student_id"].unique().tolist())
    all_ids = set(students["id"].astype(int).unique().tolist())
    inactive_ids = list(all_ids - active_ids)

    top = logs_window.groupby("student_id").size().reset_index(name="events")
    top = top.merge(students, left_on="student_id", right_on="id", how="left")
    top = top[["name", "group", "events"]].sort_values("events", ascending=False).head(5)

    return {
        "activity": {"labels": labels, "values": values},
        "active_students_count": len(active_ids),
        "inactive_students_count": len(inactive_ids),
        "top_active": top.to_dict("records"),
    }


def create_excel_report(metrics):
    output = io.BytesIO()
    required_keys = ["avg_by_course", "pass_rate", "lagging", "top_students"]
    for key in required_keys:
        if key not in metrics or metrics[key] is None:
            metrics[key] = []
    if "histogram" not in metrics or metrics["histogram"] is None:
        metrics["histogram"] = {"labels": [], "values": []}

    def write_excel(writer):
        df_course_avg = pd.DataFrame(metrics["avg_by_course"])
        df_course_avg = df_course_avg.fillna({"course_name": "Unknown", "grade": 0})
        df_course_avg.to_excel(writer, sheet_name="Average Grades", index=False)

        df_pass_rate = pd.DataFrame(metrics["pass_rate"])
        df_pass_rate = df_pass_rate.fillna({"course_name": "Unknown", "pass_rate": 0})
        df_pass_rate.to_excel(writer, sheet_name="Pass Rate", index=False)

        df_lagging = pd.DataFrame(metrics["lagging"])
        df_lagging = df_lagging.fillna({"name": "Unknown", "group": "Unknown", "course_name": "Unknown", "final_grade": 0})
        df_lagging.to_excel(writer, sheet_name="At Risk Students", index=False)

        df_top = pd.DataFrame(metrics["top_students"])
        df_top = df_top.fillna({"name": "Unknown", "group": "Unknown", "course_name": "Unknown", "final_grade": 0})
        df_top.to_excel(writer, sheet_name="Top Students", index=False)

        df_histogram = pd.DataFrame({
            "Grade Range": metrics["histogram"]["labels"],
            "Count": metrics["histogram"]["values"]
        })
        df_histogram.to_excel(writer, sheet_name="Grade Distribution", index=False)

    try:
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            write_excel(writer)
    except Exception as e:
        output = io.BytesIO()
        try:
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                write_excel(writer)
        except Exception as e2:
            raise Exception(f"Failed to create Excel with both engines: openpyxl error: {str(e)}, xlsxwriter error: {str(e2)}")

    output.seek(0)
    return output


def create_pdf_report(metrics, report_title="Analytics Report"):
    courses_data = metrics["avg_by_course"]
    pass_rate_data = metrics["pass_rate"]
    lagging_data = metrics["lagging"][:10]
    top_students_data = metrics["top_students"]

    html_content = render_template(
        "report.html",
        report_title=report_title,
        generation_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_students=metrics.get("total_students", 0),
        total_courses=len(courses_data),
        courses_data=courses_data,
        pass_rate_data=pass_rate_data,
        lagging_data=lagging_data,
        top_students_data=top_students_data,
    )

    return html_content
