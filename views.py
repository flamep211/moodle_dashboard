import io
import os
from datetime import datetime, timedelta, date

import pandas as pd
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_file

from analytics import (
    load_data,
    compute_grade_metrics,
    compute_activity_metrics,
    create_excel_report,
    create_pdf_report,
    DATA_DIR,
    AUTO_IMPORT_DISABLED_FILE,
    ensure_data_dir,
)
from database import db
from models import Student, Course, Grade, Log, ImportBatch, UserSettings
from security import login_required, role_required

main_bp = Blueprint("main", __name__)


@main_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        login_attempts_key = f"login_attempts:{username}"
        login_timeout_key = f"login_timeout:{username}"

        if login_timeout_key in session:
            timeout_end = session[login_timeout_key]
            if datetime.now().isoformat() < timeout_end:
                remaining_minutes = (datetime.fromisoformat(timeout_end) - datetime.now()).seconds // 60
                error = f"Слишком много неверных попыток. Попробуйте через {remaining_minutes} мин."
            else:
                session.pop(login_attempts_key, None)
                session.pop(login_timeout_key, None)

        if not error:
            from security import USERS
            user = USERS.get(username)
            from extensions import bcrypt

            if user and bcrypt.check_password_hash(user["password_hash"], password):
                session.pop(login_attempts_key, None)
                session.pop(login_timeout_key, None)
                session["user"] = username
                session["role"] = user["role"]
                session.setdefault("pass_threshold", 50)
                flash(f"Добро пожаловать, {username}!", "success")
                return redirect(url_for("main.index"))
            else:
                attempts = session.get(login_attempts_key, 0) + 1
                session[login_attempts_key] = attempts
                if attempts >= 5:
                    timeout_end = (datetime.now() + timedelta(minutes=15)).isoformat()
                    session[login_timeout_key] = timeout_end
                    error = f"Слишком много неверных попыток. Аккаунт заблокирован на 15 минут."
                else:
                    remaining = 5 - attempts
                    error = f"Неверный логин или пароль. Осталось попыток: {remaining}"

    return render_template("login.html", error=error)


@main_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("main.login"))


@main_bp.route("/", methods=["GET"])
@login_required
def index():
    students, courses, grades, logs = load_data()
    selected_course = request.args.get("course_id", "")
    course_id = int(selected_course) if selected_course else None
    selected_group = request.args.get("group", "")
    groups = sorted(students["group"].dropna().unique().tolist())

    if selected_group:
        students = students[students["group"] == selected_group].copy()
        grades = grades[grades["student_id"].isin(students["id"])]
        logs = logs[logs["student_id"].isin(students["id"])]

    grades_view = grades
    if course_id is not None:
        grades_view = grades[grades["course_id"] == course_id].copy()

    threshold = int(session.get("pass_threshold", 50))
    grade_metrics = compute_grade_metrics(students, courses, grades_view, pass_threshold=threshold)
    activity_metrics = compute_activity_metrics(students, logs, course_id=course_id, days=14)

    lagging_page = int(request.args.get("lagging_page", 1))
    lagging_per_page = 10
    lagging_full = grade_metrics["lagging"]
    lagging_total = len(lagging_full)
    lagging_start = (lagging_page - 1) * lagging_per_page
    lagging_end = lagging_start + lagging_per_page
    lagging_paged = lagging_full[lagging_start:lagging_end]
    lagging_has_next = lagging_end < lagging_total
    lagging_has_prev = lagging_start > 0

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


@main_bp.route("/admin/settings", methods=["POST"])
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
    return redirect(url_for("main.index"))


@main_bp.route("/admin/upload", methods=["POST"])
@login_required
@role_required("admin")
def admin_upload():
    ensure_data_dir()
    allowed = {"students", "courses", "grades", "logs"}
    filetype = request.form.get("filetype", "").strip()

    if filetype not in allowed:
        flash("Неверный тип файла", "error")
        return redirect(url_for("main.index"))

    f = request.files.get("file")
    if not f or f.filename == "":
        flash("Файл не выбран", "error")
        return redirect(url_for("main.index"))

    try:
        df = pd.read_csv(f)
    except Exception as e:
        flash(f"Ошибка при чтении CSV: {e}", "error")
        return redirect(url_for("main.index"))

    records = df.to_dict(orient="records")

    if filetype == "students":
        Student.query.delete()
        for r in records:
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
    return redirect(url_for("main.index"))


@main_bp.route("/admin/view/<table>")
@login_required
@role_required("admin")
def admin_view_table(table):
    valid = ["students", "courses", "grades", "logs"]
    if table not in valid:
        flash("Неверная таблица", "error")
        return redirect(url_for("main.index"))

    students, courses, grades, logs = load_data()
    mapping = {
        "students": students,
        "courses": courses,
        "grades": grades,
        "logs": logs,
    }
    df = mapping[table]

    query = request.args.get("q", "").strip()
    if query:
        mask = False
        for col in df.columns:
            mask = mask | df[col].astype(str).str.contains(query, case=False, na=False)
        df = df[mask]

    page = int(request.args.get("page", 1))
    per_page = 20
    total = len(df)
    start = (page - 1) * per_page
    end = start + per_page
    df_page = df.iloc[start:end]
    has_next = end < total
    has_prev = start > 0

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


@main_bp.route("/export/excel")
@login_required
def export_excel():
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
            download_name=filename,
        )
    except Exception as e:
        flash(f"Ошибка при экспорте в Excel: {str(e)}", "error")
        return redirect(url_for("main.index"))


@main_bp.route("/export/pdf")
@login_required
def export_pdf():
    try:
        students, courses, grades, logs = load_data()
        threshold = int(session.get("pass_threshold", 50))
        metrics = compute_grade_metrics(students, courses, grades, pass_threshold=threshold)
        html_content = create_pdf_report(metrics, "Аналитика качества обучения")
        html_file = io.BytesIO(html_content.encode("utf-8"))
        html_file.seek(0)
        filename = f"analytics_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        return send_file(
            html_file,
            mimetype="text/html; charset=utf-8",
            as_attachment=True,
            download_name=filename,
        )
    except Exception as e:
        flash(f"Ошибка при экспорте отчёта: {str(e)}", "error")
        return redirect(url_for("main.index"))


@main_bp.route("/api/cache-clear", methods=["POST"])
@login_required
@role_required("admin")
def api_cache_clear():
    from extensions import cache
    cache.clear()
    flash("Кэш очищен успешно", "success")
    return redirect(url_for("main.admin_panel"))


@main_bp.route("/api/theme", methods=["POST"])
@login_required
def api_set_theme():
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


@main_bp.route("/api/settings/export", methods=["GET"])
@login_required
def api_export_settings():
    user = session["user"]
    settings = UserSettings.query.filter_by(username=user).first()
    export = {
        "username": user,
        "theme": settings.theme if settings else "light",
        "settings": settings.settings_json if settings else "{}",
    }
    return export


@main_bp.route("/api/settings/import", methods=["POST"])
@login_required
def api_import_settings():
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


@main_bp.route("/courses")
@login_required
def courses_view():
    students, courses, grades, logs = load_data()
    course_enrollments = []
    for _, course in courses.iterrows():
        course_id = course["course_id"]
        course_name = course["course_name"]
        course_grades = grades[grades["course_id"] == course_id]
        enrolled_students = students[students["id"].isin(course_grades["student_id"].unique())]
        avg_grade = course_grades["grade"].mean() if len(course_grades) > 0 else 0
        enrolled_count = len(enrolled_students)
        course_enrollments.append({
            "course_id": course_id,
            "course_name": course_name,
            "enrolled_count": enrolled_count,
            "avg_grade": round(avg_grade, 2),
            "students": enrolled_students.sort_values("name").to_dict("records"),
        })

    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"
    return render_template(
        "courses.html",
        courses=course_enrollments,
        username=session["user"],
        role=session["role"],
        user_theme=user_theme,
    )


@main_bp.route("/students")
@login_required
def students_view():
    students, _, _, _ = load_data()
    groups = students.groupby("group").apply(lambda g: g.sort_values("name").to_dict("records")).to_dict()
    sorted_groups = dict(sorted(groups.items()))
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"
    return render_template(
        "students.html",
        groups=sorted_groups,
        total_students=len(students),
        username=session["user"],
        role=session["role"],
        user_theme=user_theme,
    )


@main_bp.route("/admin", methods=["GET", "POST"])
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
                    df = pd.read_csv(f)
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
            Grade.query.delete()
            Log.query.delete()
            Student.query.delete()
            Course.query.delete()
            ImportBatch.query.delete()
            db.session.commit()
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                open(AUTO_IMPORT_DISABLED_FILE, "w", encoding="utf-8").close()
            except Exception:
                pass
            flash("Все данные успешно удалены", "success")
        return redirect(url_for("main.admin_panel"))

    threshold = int(session.get("pass_threshold", 50))
    user_settings = UserSettings.query.filter_by(username=session["user"]).first()
    user_theme = "dark" if user_settings and user_settings.theme == "dark" else "light"
    return render_template(
        "admin.html",
        pass_threshold=threshold,
        username=session["user"],
        role=session["role"],
        user_theme=user_theme,
    )


@main_bp.route("/analytics")
@login_required
def analytics_view():
    students, courses, grades, logs = load_data()
    logs["date"] = pd.to_datetime(logs["date"], errors="coerce")
    grades["imported_at"] = pd.to_datetime(grades.get("imported_at"), errors="coerce")
    logs["imported_at"] = pd.to_datetime(logs.get("imported_at"), errors="coerce")
    logs["event_date"] = logs["date"].fillna(logs["imported_at"])
    grades["event_date"] = grades["imported_at"]

    def month_label(dt):
        if pd.isna(dt):
            return None
        return dt.strftime("%Y-%m")

    all_months = sorted({m for m in logs["event_date"].map(month_label).dropna().unique()} | {m for m in grades["event_date"].map(month_label).dropna().unique()})
    if not all_months:
        all_months = [date.today().strftime("%Y-%m")]

    selected_months_count = request.args.get("months", "3")
    if selected_months_count == "all":
        selected_months = all_months
    else:
        try:
            n = int(selected_months_count)
            selected_months = all_months[-n:]
        except Exception:
            selected_months = all_months[-3:]
            selected_months_count = "3"

    if not selected_months:
        selected_months = all_months[-1:]

    grades_filtered = grades[grades["event_date"].map(month_label).isin(selected_months)].copy()
    logs_filtered = logs[logs["event_date"].map(month_label).isin(selected_months)].copy()

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

    trend_data = []
    for month in selected_months:
        month_grades = grades_filtered[grades_filtered["event_date"].dt.strftime("%Y-%m") == month]
        avg_grade = month_grades["grade"].mean() if len(month_grades) > 0 else 0
        month_logs = logs_filtered[logs_filtered["event_date"].dt.strftime("%Y-%m") == month]
        activity_count = len(month_logs)
        enrolled = len(students)
        trend_data.append({
            "month": month,
            "avg_grade": round(avg_grade, 1),
            "activity": activity_count,
            "enrolled": enrolled,
        })

    current_avg = trend_data[-1]["avg_grade"] if trend_data else 0
    current_activity = trend_data[-1]["activity"] if trend_data else 0
    current_enrolled = len(students)

    logs_filtered["week"] = logs_filtered["event_date"].dt.strftime("%Y-%U")
    weekly_activity = logs_filtered.groupby("week").size().reset_index(name="events")
    weekly_activity = weekly_activity.sort_values("week").tail(8)

    dropout_risk = []
    for _, student in students.iterrows():
        student_id = student["id"]
        student_grades = grades_filtered[grades_filtered["student_id"] == student_id]
        student_logs = logs_filtered[logs_filtered["student_id"] == student_id]
        if len(student_grades) == 0:
            continue
        avg_grade = student_grades["grade"].mean()
        total_activity = len(student_logs)
        courses_taken = len(student_grades)
        grade_risk = max(0, (70 - avg_grade) / 30)
        activity_risk = max(0, (50 - total_activity / courses_taken) / 50) if courses_taken else 0
        total_risk = (grade_risk + activity_risk) / 2
        risk_level = "Низкий" if total_risk < 0.3 else "Средний" if total_risk < 0.7 else "Высокий"
        dropout_risk.append({
            "student_id": student_id,
            "name": student["name"],
            "group": student["group"],
            "avg_grade": round(avg_grade, 1),
            "total_activity": total_activity,
            "risk_level": risk_level,
            "risk_score": round(total_risk * 100, 1),
        })

    dropout_risk = sorted(dropout_risk, key=lambda x: x["risk_score"], reverse=True)[:10]
    if len(trend_data) >= 3:
        grades_trend = [d["avg_grade"] for d in trend_data[-3:]]
        slope = (grades_trend[-1] - grades_trend[0]) / (len(grades_trend) - 1) if len(grades_trend) >= 2 else 0
        next_month_prediction = max(0, min(100, grades_trend[-1] + slope))
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
        user_theme=user_theme,
    )


@main_bp.route("/student/<int:student_id>")
@login_required
def student_detail(student_id):
    students, courses, grades, logs = load_data()
    student = students[students["id"] == student_id]
    if student.empty:
        flash("Студент не найден", "error")
        return redirect(url_for("main.students_view"))
    student = student.iloc[0]
    student_grades = grades[grades["student_id"] == student_id].copy()
    student_grades = student_grades.merge(courses, on="course_id")
    student_logs = logs[logs["student_id"] == student_id].copy()
    student_logs = student_logs.merge(courses, on="course_id")
    total_courses = len(student_grades)
    passed_courses = len(student_grades[student_grades["grade"] >= int(session.get("pass_threshold", 50))])
    avg_grade = student_grades["grade"].mean() if len(student_grades) > 0 else 0
    activity_by_date = student_logs.groupby("date").size().reset_index(name="events").sort_values("date")
    activity_by_course = student_logs.groupby("course_name").size().reset_index(name="events").sort_values("events", ascending=False)
    group_students = students[students["group"] == student["group"]]
    group_grades = grades[grades["student_id"].isin(group_students["id"])]
    group_avg = group_grades["grade"].mean() if len(group_grades) > 0 else 0
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
        user_theme=user_theme,
    )
