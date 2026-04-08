import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

# Russian names
first_names = [
    'Иван', 'Петр', 'Сергей', 'Александр', 'Дмитрий', 'Владимир', 'Николай', 'Михаил',
    'Андрей', 'Павел', 'Станислав', 'Валерий', 'Игорь', 'Марк', 'Виктор',
    'Анна', 'Мария', 'Елена', 'Ольга', 'Татьяна', 'Наталья', 'Ирина', 'Светлана',
    'Юлия', 'Алиса', 'Виктория', 'Дарья', 'Полина', 'Снежана', 'Валентина'
]

last_names = [
    'Иванов', 'Петров', 'Сидоров', 'Соколов', 'Морозов', 'Волков', 'Орлов', 'Смирнов',
    'Кузнецов', 'Лебедев', 'Павлов', 'Никитин', 'Козлов', 'Зайцев', 'Медведев',
    'Александров', 'Фёдоров', 'Федосеев', 'Карпов', 'Синцов', 'Дмитриев', 'Новиков',
    'Соколовский', 'Беляков', 'Белов', 'Емелянов', 'Ефимов', 'Ершов', 'Ильин'
]

# Group names (department-semester format)
group_names = [
    'IT-21', 'IT-22', 'IT-23', 'IT-31', 'IT-32',
    'ML-21', 'ML-22', 'ML-31', 'ML-32',
    'WEB-21', 'WEB-22', 'WEB-31',
    'DATA-21', 'DATA-31',
    'CLOUD-21', 'CLOUD-22'
]

# Course names
courses = [
    'Python основы', 'Веб-разработка', 'Базы данных', 'Машинное обучение',
    'Облачные вычисления', 'Мобильная разработка', 'DevOps', 'Безопасность',
    'Алгоритмы и структуры данных', 'Проектный менеджмент'
]

# Activity actions
actions = ['login', 'view', 'quiz_attempt', 'submission', 'download', 'forum_post', 'video_watch']

print("Генерирую тестовые данные на 12 месяцев (март 2025‑2026)...")

# =========================================
# CONFIG
# =========================================
np.random.seed(42)
random.seed(42)

# Total students (some будут «неактивными» — без оценок и без логов)
num_students = 120
inactive_fraction = 0.2  # 20% студентов будут полностью неактивными

# Настройка периода генерации (включительно)
start_date = datetime(2025, 3, 15)
end_date = datetime(2026, 3, 15)

# Helper: список месяцев в формате YYYY_MM
months = []
current = datetime(start_date.year, start_date.month, 1)
while current <= end_date:
    months.append(current.strftime("%Y_%m"))
    # next month
    current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)

# =========================================
# GENERATE BASE DATA (STUDENTS + COURSES)
# =========================================
students_data = []
for i in range(1, num_students + 1):
    first_name = random.choice(first_names)
    last_name = random.choice(last_names)
    group = random.choice(group_names)
    students_data.append({'id': i, 'name': f'{last_name} {first_name}', 'group': group})

df_students = pd.DataFrame(students_data)

# mark inactive students (they будут без оценок и без логов)
inactive_ids = set(random.sample(range(1, num_students + 1), int(num_students * inactive_fraction)))

print(f"✓ Создано {len(df_students)} студентов ({len(inactive_ids)} неактивных)")

courses_data = [{'course_id': i + 1, 'course_name': name} for i, name in enumerate(courses)]
df_courses = pd.DataFrame(courses_data)
print(f"✓ Создано {len(df_courses)} курсов")

# =========================================
# GENERATE MONTHLY DATA (GRADES + LOGS)
# =========================================
all_records = []

for month in months:
    # Разбиваем период на даты текущего месяца
    year, mon = map(int, month.split("_"))
    month_start = datetime(year, mon, 1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = min(next_month - timedelta(days=1), end_date)

    # Список дат этого месяца для генерации логов
    days_in_month = (month_end - month_start).days + 1

    # Генерируем оценки и логи для активных студентов
    grades_data = []
    logs_data = []

    active_students = [s for s in range(1, num_students + 1) if s not in inactive_ids]

    # Основные оценки: 70-90% студентов получают оценки в этом месяце
    month_active_students = random.sample(active_students, k=max(1, int(len(active_students) * random.uniform(0.7, 0.9))))

    for student_id in month_active_students:
        num_courses = random.randint(3, 8)
        courses_for_student = random.sample(range(1, len(courses) + 1), min(num_courses, len(courses)))
        for course_id in courses_for_student:
            if random.random() < 0.75:
                base_grade = np.random.normal(75, 15)
                grade = max(0, min(100, int(base_grade)))
                grades_data.append({'student_id': student_id, 'course_id': course_id, 'grade': grade})

    # Логи: 200-400 записей в месяц, распределены по активным студентам
    num_logs = random.randint(200, 400)
    for _ in range(num_logs):
        student_id = random.choice(month_active_students)
        course_id = random.randint(1, len(courses))
        action = random.choice(actions)
        day_offset = random.randint(0, days_in_month - 1)
        log_date = (month_start + timedelta(days=day_offset)).strftime('%Y-%m-%d')
        logs_data.append({
            'student_id': student_id,
            'course_id': course_id,
            'action': action,
            'date': log_date
        })

    df_grades = pd.DataFrame(grades_data)
    df_logs = pd.DataFrame(logs_data).drop_duplicates().reset_index(drop=True)

    # Save per-month CSVs
    output_dir = 'data'
    df_students.to_csv(f'{output_dir}/students_{month}.csv', index=False, encoding='utf-8')
    df_courses.to_csv(f'{output_dir}/courses_{month}.csv', index=False, encoding='utf-8')
    df_grades.to_csv(f'{output_dir}/grades_{month}.csv', index=False, encoding='utf-8')
    df_logs.to_csv(f'{output_dir}/logs_{month}.csv', index=False, encoding='utf-8')

    print(f"✓ {month}: {len(df_students)} студентов, {len(df_courses)} курсов, {len(df_grades)} оценок, {len(df_logs)} логов")

print("\nГенерация завершена. Файлы созданы в папке data/.\n")
print("Теперь вы можете загрузить нужные CSV файлы через админку (множественный выбор файлов).")

print("\nВсе файлы созданы. Чтобы загрузить данные, используйте панель администратора и выберите нужные CSV (можно несколько файлов сразу).")
print("Файлы находятся в папке data/. Например:")
print("  data/students_2025_03.csv, data/grades_2025_03.csv, data/logs_2025_03.csv")
print("  data/students_2026_03.csv, data/grades_2026_03.csv, data/logs_2026_03.csv")
