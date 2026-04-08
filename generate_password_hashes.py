from flask import Flask
from flask_bcrypt import Bcrypt

app = Flask(__name__)
bcrypt = Bcrypt(app)

# Генерируем хеши для паролей
teacher_hash = bcrypt.generate_password_hash('12345').decode('utf-8')
admin_hash = bcrypt.generate_password_hash('admin123').decode('utf-8')

print("=" * 60)
print("Новые хеши паролей для USERS в app.py:")
print("=" * 60)
print(f'\n"teacher": {{\n    "password_hash": "{teacher_hash}",\n    "role": "teacher"\n}},\n')
print(f'"admin": {{\n    "password_hash": "{admin_hash}",\n    "role": "admin"\n}}')
print("\n" + "=" * 60)
print("Пароли:")
print("  teacher: 12345")
print("  admin: admin123")
print("=" * 60)
