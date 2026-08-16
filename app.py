"""
Conference Management System — Flask backend
================================================
Serves the static dashboard pages AND exposes a small JSON API
backed by a real SQLite database (database/cms.db).

Run:
    pip install -r requirements.txt
    python app.py
Then open:
    http://localhost:5000/login.html

The bundled dashboards (author/admin/reviewer_dashboard.html) work
fully standalone using localStorage demo auth, so the app runs with
zero backend setup. This file additionally wires up a real database
and /api/* endpoints for anyone extending the project into a full
client-server app (see static/js/common.js for the matching
front-end fetch() wrapper).
"""

import sys
import os
sys.stdout.reconfigure(encoding='utf-8')

import sqlite3
import pymysql
import secrets
from datetime import datetime

from flask import Flask, g, jsonify, request, send_from_directory, session, redirect, stream_with_context
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database", "cms.db")
SCHEMA_PATH = os.path.join(BASE_DIR, "database", "schema.sql")
SCHEMA_MYSQL = os.path.join(BASE_DIR, "database", "schema_mysql.sql")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
CORS(app)


# ─────────────────────────────────────────────
# Database connection helpers
# ─────────────────────────────────────────────
def get_db():
    if "db" not in g:
        db_type = os.environ.get("DB_TYPE", "sqlite").lower()
        if db_type == "mysql":
            # Connect to MySQL using PyMySQL and provide a small wrapper
            host = os.environ.get("MYSQL_HOST", "127.0.0.1")
            port = int(os.environ.get("MYSQL_PORT", "3306"))
            user = os.environ.get("MYSQL_USER", "root")
            password = os.environ.get("MYSQL_PASSWORD", "")
            db_name = os.environ.get("MYSQL_DB", "cms")
            conn = pymysql.connect(host=host, port=port, user=user, password=password,
                                   database=db_name, cursorclass=pymysql.cursors.DictCursor,
                                   autocommit=False)

            class MySQLDB:
                def __init__(self, conn):
                    self.conn = conn
                def execute(self, query, params=()):
                    # Translate SQLite-style ? placeholders to MySQL %s
                    q = query.replace('?', '%s')
                    cur = self.conn.cursor()
                    cur.execute(q, params)
                    return cur
                def executescript(self, script):
                    # naive split by semicolon for simple schema files
                    for stmt in script.split(";"):
                        s = stmt.strip()
                        if s:
                            cur = self.conn.cursor()
                            cur.execute(s)
                    return None
                def commit(self):
                    self.conn.commit()
                def close(self):
                    self.conn.close()

            g.db = MySQLDB(conn)
        else:
            g.db = sqlite3.connect(DB_PATH)
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def run_certificate_migration(db):
    """Allow completed conference certificates in SQLite schemas created earlier."""
    try:
        schema = db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='certificates'").fetchone()
        if not schema or "completed" in str(schema[0]):
            return
        db.execute("ALTER TABLE certificates RENAME TO certificates_old")
        db.execute(
            """
            CREATE TABLE certificates (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
                user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                cert_type       TEXT    NOT NULL DEFAULT 'acceptance'
                                CHECK (cert_type IN ('acceptance','participation','best_paper','completed')),
                cert_code       TEXT    NOT NULL UNIQUE,
                issued_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        db.execute(
            "INSERT INTO certificates (id, paper_id, user_id, cert_type, cert_code, issued_at) "
            "SELECT id, paper_id, user_id, cert_type, cert_code, issued_at FROM certificates_old"
        )
        db.execute("DROP TABLE certificates_old")
        db.commit()
    except Exception:
        db.rollback()


# ─────────────────────────────────────────────
# Server-Side Events (SSE) for real-time notifications
# ─────────────────────────────────────────────
from queue import Queue, Empty
import json
import threading

# mapping of user_id (string) -> list of Queue
USER_SSE = {}
USER_SSE_LOCK = threading.Lock()


def emit_user_event(user_id, event_name, payload):
    """Push an SSE event to any active listeners for the user."""
    uid = str(user_id)
    with USER_SSE_LOCK:
        queues = list(USER_SSE.get(uid, []))
    body = {"event": event_name, **payload}
    for q in queues:
        try:
            q.put(body, block=False)
        except Exception:
            pass


def notify_and_push(db, user_id, message):
    """Insert notification into DB and push to any SSE listeners for the user."""
    try:
        db.execute("INSERT INTO notifications (user_id, message) VALUES (?, ?)", (user_id, message))
        db.commit()
    except Exception:
        db.rollback()
    payload = {"user_id": user_id, "message": message, "created_at": datetime.utcnow().isoformat()}
    emit_user_event(user_id, "notification", payload)


def ensure_completed_conference_certificates(db, user_id=None):
    """Create completion certificates for accepted papers so conference completion is visible immediately."""
    query = (
        "SELECT p.id, p.title, p.author_id, p.status "
        "FROM papers p "
    )
    params = []
    if user_id:
        query += "WHERE p.author_id = ? "
        params.append(int(user_id))
    query += "ORDER BY p.id"

    rows = db.execute(query, params).fetchall()
    for row in rows:
        if row["status"] != "accepted":
            continue

        existing = db.execute(
            "SELECT id FROM certificates WHERE paper_id = ? AND user_id = ? AND cert_type = 'completed'",
            (row["id"], row["author_id"]),
        ).fetchone()
        if existing:
            continue

        cert_code = secrets.token_hex(12).upper()
        db.execute(
            "INSERT INTO certificates (paper_id, user_id, cert_type, cert_code) VALUES (?, ?, 'completed', ?)",
            (row["id"], row["author_id"], cert_code),
        )
    db.commit()


@app.route('/events/notifications')
def sse_notifications():
    sess_user = session.get('user')
    if not sess_user:
        return jsonify({'error': 'unauthenticated'}), 401
    uid = str(sess_user.get('id'))
    q = Queue()
    with USER_SSE_LOCK:
        USER_SSE.setdefault(uid, []).append(q)

    @stream_with_context
    def event_stream():
        try:
            # send recent unread notifications so client catches up
            db = get_db()
            try:
                rows = db.execute("SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 20", (sess_user.get('id'),)).fetchall()
                for r in reversed(rows):
                    yield f"event: notification\ndata: {json.dumps(dict(r))}\n\n"
            except Exception:
                pass
            while True:
                try:
                    payload = q.get(timeout=30)
                    event_name = payload.get('event', 'notification') if isinstance(payload, dict) else 'notification'
                    yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
                except Empty:
                    yield ": keep-alive\n\n"
        finally:
            with USER_SSE_LOCK:
                if uid in USER_SSE and q in USER_SSE[uid]:
                    USER_SSE[uid].remove(q)
    return app.response_class(event_stream(), mimetype='text/event-stream')


@app.route('/api/stream')
def reviewer_stream():
    reviewer_id = request.args.get('reviewer_id')
    if not reviewer_id:
        return jsonify({'error': 'missing reviewer_id'}), 400
    uid = str(reviewer_id)
    q = Queue()
    with USER_SSE_LOCK:
        USER_SSE.setdefault(uid, []).append(q)

    @stream_with_context
    def event_stream():
        try:
            db = get_db()
            try:
                rows = db.execute(
                    "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 20",
                    (int(reviewer_id),),
                ).fetchall()
                for r in reversed(rows):
                    yield f"event: notification\ndata: {json.dumps(dict(r))}\n\n"
            except Exception:
                pass
            while True:
                try:
                    payload = q.get(timeout=30)
                    event_name = payload.get('event', 'notification') if isinstance(payload, dict) else 'notification'
                    yield f"event: {event_name}\ndata: {json.dumps(payload)}\n\n"
                except Empty:
                    yield ": keep-alive\n\n"
        finally:
            with USER_SSE_LOCK:
                if uid in USER_SSE and q in USER_SSE[uid]:
                    USER_SSE[uid].remove(q)
    return app.response_class(event_stream(), mimetype='text/event-stream')

@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create tables from schema.sql (if not already present) and
    seed three demo accounts with REAL password hashes."""
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    first_run = not os.path.exists(DB_PATH) if db_type == "sqlite" else False
    if db_type == "mysql":
        print("⚠️ DB_TYPE=mysql detected. Please import 'database/schema_mysql.sql' into your MySQL server (Workbench). Skipping automatic schema run.")
        db = None
        try:
            db = get_db()
        except Exception:
            db = None
    else:
        db = sqlite3.connect(DB_PATH)
        db.executescript(open(SCHEMA_PATH, "r", encoding="utf-8").read())
        db.commit()
        run_certificate_migration(db)

    if db:
        seed_demo_users(db)
        try:
            ensure_completed_conference_certificates(db)
        except Exception:
            pass
        db.close()

    if first_run:
        print(f"✅ Initialized new database at {DB_PATH}")
    else:
        print(f"✅ Using existing database at {DB_PATH}")


def seed_demo_users(db):
    """Seed three demo accounts only when missing. Do NOT overwrite existing passwords.

    This avoids resetting admin/demo credentials on subsequent runs while still
    providing convenient demo accounts for fresh databases.
    """
    demo = [
        ("Madhav Kumar", "author@demo.com", "demo123", "author", "IIT Madras", "M"),
        ("Priya Nair", "reviewer@demo.com", "demo123", "reviewer", "NIT Trichy", "P"),
        ("Dr. Ramesh K.", "admin@demo.com", "demo123", "admin", "Anna University", "R"),
    ]
    for name, email, pwd, role, college, letter in demo:
        row = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            # don't overwrite existing users/passwords; keep current credentials intact
            continue
        pwd_hash = generate_password_hash(pwd)
        db.execute(
            "INSERT INTO users (name, email, password_hash, role, college, avatar_letter) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, email, pwd_hash, role, college, letter),
        )
    db.commit()


# ─────────────────────────────────────────────
# Static page routes (serve the HTML dashboards)
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/<page>.html")
def page(page):
    filename = f"{page}.html"
    # Protect dashboard pages server-side so unauthenticated users cannot
    # directly load them by URL. The front-end also performs a localStorage
    # check, but this server-side guard prevents direct access.
    protected = {
        "author_dashboard": "author",
        "reviewer_dashboard": "reviewer",
        "admin_dashboard": "admin",
    }
    if page in protected:
        user = session.get("user")
        if not user:
            return redirect("/login.html")
        # ensure role matches requested dashboard (admins may still view admin page only)
        required_role = protected[page]
        if user.get("role") != required_role:
            return redirect("/login.html")

    if os.path.exists(os.path.join(BASE_DIR, filename)):
        return send_from_directory(BASE_DIR, filename)
    return jsonify({"error": "Not found"}), 404


@app.route("/static/css/<path:filename>")
def css_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static", "css"), filename)


@app.route("/static/js/<path:filename>")
def js_files(filename):
    return send_from_directory(os.path.join(BASE_DIR, "static", "js"), filename)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ─────────────────────────────────────────────
# Auth API
# ─────────────────────────────────────────────
@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    role = data.get("role", "author")
    college = data.get("college", "")

    if not name or not email or not password:
        return jsonify({"error": "name, email and password are required"}), 400
    if role not in ("author", "reviewer", "admin"):
        return jsonify({"error": "invalid role"}), 400
    if len(password) < 6:
        return jsonify({"error": "password must be at least 6 characters"}), 400

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        return jsonify({"error": "email already registered"}), 409

    pwd_hash = generate_password_hash(password)
    letter = name[0].upper() if name else "U"
    cur = db.execute(
        "INSERT INTO users (name, email, password_hash, role, college, avatar_letter) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, pwd_hash, role, college, letter),
    )
    db.commit()
    print(f"[auth] registered user: {email} (id={cur.lastrowid})")
    token = secrets.token_hex(16)
    session_user = {
        "id": cur.lastrowid,
        "name": name,
        "email": email,
        "role": role,
        "college": college,
        "token": token,
    }
    # Set Flask session so user is immediately authenticated server-side
    session["user"] = session_user
    return jsonify({
        "token": token,
        "user": session_user,
    }), 201


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "invalid email or password"}), 401

    token = secrets.token_hex(16)  # demo token; swap for JWT/session in production

    # Store minimal user info in the Flask session so server-side page
    # requests can be guarded. Token is also returned for API use.
    session_user = {
        "id": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "college": user["college"],
        "token": token,
    }
    session["user"] = session_user

    return jsonify({
        "token": token,
        "user": session_user,
    })


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.pop("user", None)
    return jsonify({"ok": True})


@app.route("/api/whoami", methods=["GET"])
def api_whoami():
    """Return the server-side session user if present (or 401).
    Front-end uses this to verify the Flask session cookie before
    performing client-side redirects to dashboard pages.
    """
    user = session.get("user")
    if not user:
        return jsonify({"user": None}), 401
    return jsonify({"user": user})


# ─────────────────────────────────────────────
# Conferences API
# ─────────────────────────────────────────────
@app.route("/api/conferences", methods=["GET"])
def list_conferences():
    db = get_db()
    rows = db.execute(
        "SELECT c.*, COUNT(p.id) AS submissions FROM conferences c "
        "LEFT JOIN papers p ON p.conference_id = c.id "
        "GROUP BY c.id ORDER BY c.deadline ASC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/conferences", methods=["POST"])
def create_conference():
    data = request.get_json(force=True, silent=True) or {}
    required = ("name", "conf_date", "deadline")
    if not all(data.get(f) for f in required):
        return jsonify({"error": f"required fields: {', '.join(required)}"}), 400

    db = get_db()
    venue = (data.get("venue") or "").strip()
    cur = db.execute(
        "INSERT INTO conferences (name, venue, conf_date, deadline, description, created_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (data["name"], venue, data["conf_date"], data["deadline"],
         data.get("description", ""), data.get("created_by")),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid}), 201


# ─────────────────────────────────────────────
# Papers API
# ─────────────────────────────────────────────
@app.route("/api/papers", methods=["GET"])
def list_papers():
    db = get_db()
    author_id = request.args.get("author_id")
    reviewer_id = request.args.get("reviewer_id")

    query = (
        "SELECT p.*, u.name AS author_name, c.name AS conference_name, rv.name AS reviewer_name "
        "FROM papers p "
        "JOIN users u ON u.id = p.author_id "
        "JOIN conferences c ON c.id = p.conference_id "
        "LEFT JOIN assignments a ON a.paper_id = p.id "
        "LEFT JOIN users rv ON rv.id = a.reviewer_id "
    )
    params = []
    if author_id:
        query += "WHERE p.author_id = ? "
        params.append(author_id)
    elif reviewer_id:
        query += "WHERE a.reviewer_id = ? "
        params.append(reviewer_id)
    query += "ORDER BY p.submitted_at DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/papers", methods=["POST"])
def submit_paper():
    data = request.get_json(force=True, silent=True) or {}
    required = ("title", "author_id", "conference_id")
    if not all(data.get(f) for f in required):
        return jsonify({"error": f"required fields: {', '.join(required)}"}), 400

    db = get_db()
    cur = db.execute(
        "INSERT INTO papers (title, abstract, keywords, author_id, conference_id, file_path, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'submitted')",
        (data["title"], data.get("abstract", ""), data.get("keywords", ""),
         data["author_id"], data["conference_id"], data.get("file_path", "")),
    )
    db.commit()

    admins = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
    for admin in admins:
        notify_and_push(db, admin["id"], f'New paper submission: "{data["title"]}" has been received.')
    return jsonify({"id": cur.lastrowid}), 201


@app.route("/api/papers/<int:paper_id>/status", methods=["PUT"])
def update_paper_status(paper_id):
    data = request.get_json(force=True, silent=True) or {}
    status = data.get("status")
    if status not in ("submitted", "under_review", "accepted", "rejected"):
        return jsonify({"error": "invalid status"}), 400
    db = get_db()
    db.execute("UPDATE papers SET status = ? WHERE id = ?", (status, paper_id))
    if status == "accepted":
        paper = db.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if paper:
            ensure_completed_conference_certificates(db, user_id=paper["author_id"])
    db.commit()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# Reviews API
# ─────────────────────────────────────────────
@app.route("/api/reviews", methods=["GET"])
def list_reviews():
    db = get_db()
    reviewer_id = request.args.get("reviewer_id")
    query = (
        "SELECT r.*, p.title AS paper_title, p.file_path, c.name AS conference_name, u.name AS reviewer_name "
        "FROM reviews r "
        "JOIN papers p ON p.id = r.paper_id "
        "JOIN conferences c ON c.id = p.conference_id "
        "JOIN users u ON u.id = r.reviewer_id "
    )
    params = []
    if reviewer_id:
        query += "WHERE r.reviewer_id = ? "
        params.append(int(reviewer_id))
    query += "ORDER BY r.reviewed_at DESC"
    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/reviews", methods=["POST"])
def submit_review():
    data = request.get_json(force=True, silent=True) or {}
    required = ("paper_id", "reviewer_id", "score", "decision")
    if not all(data.get(f) is not None for f in required):
        return jsonify({"error": f"required fields: {', '.join(required)}"}), 400
    if data["decision"] not in ("Accept", "Reject"):
        return jsonify({"error": "decision must be Accept or Reject"}), 400

    db = get_db()
    paper = db.execute("SELECT id, title FROM papers WHERE id = ?", (data["paper_id"],)).fetchone()
    if not paper:
        return jsonify({"error": "paper not found"}), 404

    db.execute(
        "INSERT INTO reviews (paper_id, reviewer_id, score, decision, comments, criteria) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(paper_id, reviewer_id) DO UPDATE SET "
        "score=excluded.score, decision=excluded.decision, "
        "comments=excluded.comments, criteria=excluded.criteria",
        (data["paper_id"], data["reviewer_id"], data["score"], data["decision"],
         data.get("comments", ""), data.get("criteria", "")),
    )
    new_status = "accepted" if data["decision"] == "Accept" else "rejected"
    db.execute("UPDATE papers SET status = 'under_review' WHERE id = ? AND status = 'submitted'",
               (data["paper_id"],))
    msg = f'You submitted your review for "{paper["title"]}" with score {data["score"]}/10.'
    notify_and_push(db, data["reviewer_id"], msg)
    reviewer = db.execute("SELECT name FROM users WHERE id = ?", (data["reviewer_id"],)).fetchone()
    admins = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
    reviewer_name = reviewer["name"] if reviewer else 'Reviewer'
    for admin in admins:
        notify_and_push(db, admin["id"], f'{reviewer_name} submitted a review for "{paper["title"]}" (score {data["score"]}/10).')
    emit_user_event(data["reviewer_id"], "review_submitted", {
        "paper_id": data["paper_id"],
        "title": paper["title"],
        "score": data["score"],
        "decision": data["decision"],
        "reviewer_id": data["reviewer_id"],
    })
    db.commit()
    return jsonify({"ok": True, "suggested_status": new_status})


@app.route("/api/reviews/<int:review_id>/publish", methods=["PUT"])
def publish_review(review_id):
    db = get_db()
    review = db.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if not review:
        return jsonify({"error": "review not found"}), 404
    db.execute("UPDATE reviews SET published = 1 WHERE id = ?", (review_id,))
    final_status = "accepted" if review["decision"] == "Accept" else "rejected"
    db.execute("UPDATE papers SET status = ? WHERE id = ?", (final_status, review["paper_id"]))
    # notify author about published result
    try:
        paper = db.execute("SELECT id, title, author_id FROM papers WHERE id = ?", (review["paper_id"],)).fetchone()
        if paper:
            msg = f'Your paper "{paper["title"]}" has been {final_status}.'
            notify_and_push(db, paper["author_id"], msg)
    except Exception:
        pass
    db.commit()
    return jsonify({"ok": True, "status": final_status})


# ─────────────────────────────────────────────
# Notifications API
# ─────────────────────────────────────────────
@app.route("/api/notifications", methods=["GET"])
def list_notifications():
    user_id = request.args.get("user_id")
    db = get_db()
    if user_id:
        rows = db.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
        ).fetchall()
    else:
        rows = db.execute("SELECT * FROM notifications ORDER BY created_at DESC").fetchall()
    return jsonify([dict(r) for r in rows])


@app.route('/api/reviewer_stats', methods=['GET'])
def reviewer_stats():
    reviewer_id = request.args.get('reviewer_id')
    if not reviewer_id:
        return jsonify({"error": "missing reviewer_id"}), 400

    db = get_db()
    reviewer_id = int(reviewer_id)
    assigned = db.execute(
        "SELECT COUNT(*) AS c FROM assignments WHERE reviewer_id = ?",
        (reviewer_id,),
    ).fetchone()['c'] or 0
    pending = db.execute(
        "SELECT COUNT(*) AS c FROM assignments a "
        "LEFT JOIN reviews r ON r.paper_id = a.paper_id AND r.reviewer_id = a.reviewer_id "
        "WHERE a.reviewer_id = ? AND r.id IS NULL",
        (reviewer_id,),
    ).fetchone()['c'] or 0
    done = db.execute(
        "SELECT COUNT(*) AS c FROM reviews WHERE reviewer_id = ?",
        (reviewer_id,),
    ).fetchone()['c'] or 0
    overall_percent = 0 if assigned == 0 else round((done / assigned) * 100, 0)
    month_percent = 0 if done == 0 else min(100, round((done / 2) * 100, 0))
    response_days = 4.2 if done == 0 else round((done * 2.1) / max(1, done), 1)
    urgent = db.execute(
        "SELECT p.title FROM assignments a "
        "JOIN papers p ON p.id = a.paper_id "
        "LEFT JOIN reviews r ON r.paper_id = a.paper_id AND r.reviewer_id = a.reviewer_id "
        "WHERE a.reviewer_id = ? AND r.id IS NULL "
        "ORDER BY a.assigned_at ASC LIMIT 1",
        (reviewer_id,),
    ).fetchone()

    payload = {
        "assigned": assigned,
        "pending": pending,
        "done": done,
        "overall_percent": overall_percent,
        "month_percent": month_percent,
        "response_days": response_days,
        "urgent": None,
    }
    if urgent:
        payload["urgent"] = {
            "message": f'\"{urgent["title"]}\" review due in',
            "when": '3 days',
        }
    return jsonify(payload)


@app.route("/api/notifications/<int:notif_id>/read", methods=["PUT"])
def mark_notification_read(notif_id):
    db = get_db()
    db.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notif_id,))
    db.commit()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# File upload (simple)
# ─────────────────────────────────────────────
@app.route('/api/upload', methods=['POST'])
def api_upload():
    if 'file' not in request.files:
        return jsonify({'error': 'no file provided'}), 400
    f = request.files['file']
    filename = secure_filename(f.filename or '')
    if not filename:
        return jsonify({'error': 'invalid filename'}), 400
    dest = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    f.save(dest)
    return jsonify({'file_path': f'/uploads/{filename}'}), 201


@app.route('/api/users', methods=['GET'])
def api_list_users():
    db = get_db()
    rows = db.execute("SELECT id, name, email, role, college, created_at FROM users ORDER BY id DESC").fetchall()
    users = []
    for r in rows:
        # normalize sqlite Row vs dict-like
        try:
            u = {'id': r['id'], 'name': r['name'], 'email': r['email'], 'role': r['role'], 'college': r.get('college') if isinstance(r, dict) else r['college'], 'created_at': r.get('created_at') if isinstance(r, dict) else r['created_at']}
        except Exception:
            u = dict(r)
        # For reviewer role include workload metrics used by admin UI
        if u.get('role') == 'reviewer':
            try:
                assigned = db.execute("SELECT COUNT(*) AS c FROM assignments WHERE reviewer_id = ?", (u['id'],)).fetchone()[0]
                completed = db.execute("SELECT COUNT(*) AS c FROM reviews WHERE reviewer_id = ? AND published = 1", (u['id'],)).fetchone()[0]
                avg_score_row = db.execute("SELECT AVG(score) AS avg FROM reviews WHERE reviewer_id = ?", (u['id'],)).fetchone()
                avg_score = avg_score_row[0] if avg_score_row else None
                u['assigned'] = assigned or 0
                u['completed'] = completed or 0
                u['avg_score'] = round(avg_score,2) if avg_score else None
                # simple heuristic: active if assigned workload under 5
                u['active'] = (u['assigned'] < 5)
            except Exception:
                u['assigned'] = 0
                u['completed'] = 0
                u['avg_score'] = None
                u['active'] = False
        users.append(u)
    return jsonify(users)


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
def api_delete_user(user_id):
    db = get_db()
    # Prevent deleting last admin or self-deleting could be implemented later
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    return jsonify({"ok": True})


# Allow admin or the user themselves to update their profile (including password)
@app.route('/api/users/<int:user_id>', methods=['PUT'])
def api_update_user(user_id):
    sess_user = session.get('user')
    if not sess_user:
        return jsonify({'error': 'unauthenticated'}), 401
    # only admins or the user themselves may update
    if sess_user.get('role') != 'admin' and sess_user.get('id') != user_id:
        return jsonify({'error': 'forbidden'}), 403

    data = request.get_json(force=True, silent=True) or {}
    name = data.get('name')
    email = data.get('email')
    password = data.get('password')
    role = data.get('role')
    college = data.get('college')
    expertise = data.get('expertise')

    if role and role not in ('author','reviewer','admin'):
        return jsonify({'error': 'invalid role'}), 400

    db = get_db()
    # build update dynamically to avoid overwriting unspecified fields
    updates = []
    params = []
    if name is not None:
        updates.append('name = ?')
        params.append(name)
    if email is not None:
        updates.append('email = ?')
        params.append(email.lower())
    if role is not None and sess_user.get('role') == 'admin':
        updates.append('role = ?')
        params.append(role)
    if college is not None:
        updates.append('college = ?')
        params.append(college)
    if expertise is not None:
        updates.append('expertise = ?')
        params.append(expertise)
    if password:
        if len(password) < 6:
            return jsonify({'error': 'password must be at least 6 characters'}), 400
        updates.append('password_hash = ?')
        params.append(generate_password_hash(password))

    if not updates:
        return jsonify({'error': 'no updatable fields provided'}), 400

    params.append(user_id)
    q = f"UPDATE users SET {', '.join(updates)} WHERE id = ?"
    try:
        db.execute(q, params)
        db.commit()
    except Exception as e:
        db.rollback()
        return jsonify({'error': str(e)}), 400

    # return updated user record (sanitized)
    u = db.execute('SELECT id, name, email, role, college, expertise, created_at FROM users WHERE id = ?', (user_id,)).fetchone()
    return jsonify(dict(u))


@app.route('/api/conferences/<int:conf_id>', methods=['DELETE'])
def api_delete_conference(conf_id):
    db = get_db()
    # delete conference and cascade papers via foreign keys
    db.execute("DELETE FROM conferences WHERE id = ?", (conf_id,))
    db.commit()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# Assignments API
# ─────────────────────────────────────────────
@app.route('/api/assignments', methods=['POST'])
def create_assignment():
    data = request.get_json(force=True, silent=True) or {}
    paper_id = data.get('paper_id')
    reviewer_id = data.get('reviewer_id')
    if not paper_id or not reviewer_id:
        return jsonify({'error': 'paper_id and reviewer_id required'}), 400
    db = get_db()
    # insert assignment if not exists
    try:
        cur = db.execute("INSERT INTO assignments (paper_id, reviewer_id) VALUES (?, ?)", (paper_id, reviewer_id))
        # mark paper under review
        db.execute("UPDATE papers SET status = 'under_review' WHERE id = ?", (paper_id,))
        # notify reviewer and author
        rv = db.execute("SELECT name FROM users WHERE id = ?", (reviewer_id,)).fetchone()
        paper = db.execute("SELECT title, author_id FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if rv and paper:
            notify_and_push(db, reviewer_id, f'New paper "{paper["title"]}" assigned to you for review.')
            notify_and_push(db, paper['author_id'], f'A reviewer has been assigned to "{paper["title"]}".')
            admins = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchall()
            for admin in admins:
                notify_and_push(db, admin["id"], f'Reviewer {rv["name"]} assigned to "{paper["title"]}".')

    except Exception as e:
        # unique constraint or other error
        db.rollback()
        return jsonify({'error': str(e)}), 400
    return jsonify({'ok': True, 'assignment_id': getattr(cur, 'lastrowid', None)})

@app.route('/api/assignments/<int:assn_id>', methods=['DELETE'])
def delete_assignment(assn_id):
    db = get_db()
    db.execute("DELETE FROM assignments WHERE id = ?", (assn_id,))
    db.commit()
    return jsonify({'ok': True})


@app.route('/api/assignments', methods=['GET'])
def list_assignments():
    db = get_db()
    reviewer_id = request.args.get('reviewer_id')
    query = (
        "SELECT a.id AS assignment_id, a.paper_id, a.reviewer_id, a.assigned_at, p.title AS paper_title, u.name AS reviewer_name "
        "FROM assignments a "
        "JOIN papers p ON p.id = a.paper_id "
        "JOIN users u ON u.id = a.reviewer_id "
    )
    params = []
    if reviewer_id:
        query += "WHERE a.reviewer_id = ? "
        params.append(reviewer_id)
    query += "ORDER BY a.assigned_at DESC"
    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────
# Certificates API
# ─────────────────────────────────────────────
@app.route("/api/certificates", methods=["GET"])
def list_certificates():
    """Get certificates with full paper and conference details."""
    db = get_db()
    user_id = request.args.get("user_id")
    ensure_completed_conference_certificates(db, user_id=user_id)

    query = (
        "SELECT c.id, c.paper_id, c.user_id, c.cert_type, c.cert_code, c.issued_at, "
        "p.title AS paper_title, p.status AS paper_status, conf.name AS conference_name, "
        "conf.conf_date AS conference_date, conf.venue, u.name AS author_name "
        "FROM certificates c "
        "JOIN papers p ON p.id = c.paper_id "
        "JOIN conferences conf ON conf.id = p.conference_id "
        "JOIN users u ON u.id = p.author_id "
    )
    params = []
    if user_id:
        query += "WHERE c.user_id = ? "
        params.append(user_id)
    query += "ORDER BY c.issued_at DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


@app.route("/api/certificates", methods=["POST"])
def create_certificate():
    """Create a certificate for an accepted paper."""
    data = request.get_json(force=True, silent=True) or {}
    required = ("paper_id", "user_id", "cert_type")
    if not all(data.get(f) for f in required):
        return jsonify({"error": f"required fields: {', '.join(required)}"}), 400
    if data["cert_type"] not in ("acceptance", "participation", "best_paper", "completed"):
        return jsonify({"error": "invalid cert_type"}), 400
    
    db = get_db()
    # Generate unique cert code
    cert_code = secrets.token_hex(12).upper()
    
    try:
        cur = db.execute(
            "INSERT INTO certificates (paper_id, user_id, cert_type, cert_code) "
            "VALUES (?, ?, ?, ?)",
            (data["paper_id"], data["user_id"], data["cert_type"], cert_code),
        )
        db.commit()
        
        # Notify user
        paper = db.execute("SELECT title FROM papers WHERE id = ?", (data["paper_id"],)).fetchone()
        if paper:
            msg = f'Certificate issued for your paper "{paper["title"]}"'
            notify_and_push(db, data["user_id"], msg)
        
        return jsonify({"id": cur.lastrowid, "cert_code": cert_code}), 201
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 400


@app.route("/api/papers-with-certificates", methods=["GET"])
def list_papers_with_certificates():
    """Get papers with certificate information and conference details."""
    db = get_db()
    author_id = request.args.get("author_id")
    ensure_completed_conference_certificates(db, user_id=author_id)

    query = (
        "SELECT p.id, p.title, p.abstract, p.keywords, p.author_id, p.conference_id, "
        "p.file_path, p.status, p.submitted_at, "
        "u.name AS author_name, c.name AS conference_name, c.conf_date, c.venue, c.deadline, "
        "cert.id AS cert_id, cert.cert_type, cert.cert_code, cert.issued_at "
        "FROM papers p "
        "JOIN users u ON u.id = p.author_id "
        "JOIN conferences c ON c.id = p.conference_id "
        "LEFT JOIN certificates cert ON cert.paper_id = p.id AND cert.cert_type = 'completed' "
    )
    params = []
    if author_id:
        query += "WHERE p.author_id = ? "
        params.append(author_id)
    query += "ORDER BY p.submitted_at DESC"

    rows = db.execute(query, params).fetchall()
    return jsonify([dict(r) for r in rows])


# ─────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat(), "db": DB_PATH})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    # Control the reloader explicitly to avoid noisy restarts when tools/ files change.
    use_reloader = os.environ.get("USE_RELOADER", "0") in ("1", "true", "True")
    print(f"🚀 CMS running at http://localhost:{port}/login.html")
    app.run(debug=debug, use_reloader=use_reloader, host="0.0.0.0", port=port)
