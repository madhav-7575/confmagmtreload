"""
Standalone database initializer.

Usually you don't need to run this directly — `python app.py`
calls init_db() automatically on startup. Use this script if you
want to (re)build database/cms.db without starting the web server,
e.g. in a deploy/CI step:

    python init_db.py
"""
import os
import sqlite3
from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "cms.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "database", "schema.sql")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

db = sqlite3.connect(DB_PATH)
db.executescript(open(SCHEMA_PATH, "r", encoding="utf-8").read())

demo = [
    ("Madhav Kumar", "author@demo.com", "demo123", "author", "IIT Madras", "M"),
    ("Priya Nair", "reviewer@demo.com", "demo123", "reviewer", "NIT Trichy", "P"),
    ("Dr. Ramesh K.", "admin@demo.com", "demo123", "admin", "Anna University", "R"),
]
for name, email, pwd, role, college, letter in demo:
    row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    # Only insert demo user if not already present. Do not overwrite existing passwords.
    if row:
        continue
    pwd_hash = generate_password_hash(pwd)
    db.execute(
        "INSERT INTO users (name, email, password_hash, role, college, avatar_letter) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, pwd_hash, role, college, letter),
    )
db.commit()
db.close()

print(f"✅ Database ready at {DB_PATH}")
print("   Demo logins (password: demo123):")
print("   author@demo.com | reviewer@demo.com | admin@demo.com")
