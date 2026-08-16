# Conference Management System (CMS)

A full conference submission / peer-review / publishing platform with
three roles — **Author**, **Reviewer**, **Admin** — plus a Flask +
SQLite backend with a real database connection.

## 📂 Folder structure

```
conference-management/
│
├── login.html                  ← Login + Register page
├── author_dashboard.html       ← Author dashboard
├── admin_dashboard.html        ← Admin dashboard
├── reviewer_dashboard.html     ← Reviewer dashboard
├── index.html                  ← Public landing page
│
├── static/
│   ├── css/style.css           ← Shared design tokens
│   └── js/
│       ├── common.js           ← fetch() wrapper around the API
│       └── i18n.js             ← dark mode + language helpers
│
├── database/
│   ├── schema.sql              ← Full SQL schema + seed data
│   └── cms.db                  ← SQLite database (auto-created, ready to use)
│
├── uploads/                    ← Uploaded paper PDFs land here
│
├── app.py                      ← Flask backend + REST API + DB connection
├── init_db.py                  ← Standalone DB (re)initializer
├── requirements.txt
├── .env.example                ← Copy to .env and edit
└── README.md
```

## 🚀 Quick start

```bash
cd conference-management
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open **http://localhost:5000/login.html**

The database (`database/cms.db`) is created and seeded automatically
the first time `app.py` runs. To rebuild it manually at any time:

```bash
python init_db.py
```

## 🔑 Demo logins

| Role     | Email               | Password |
|----------|----------------------|----------|
| Author   | author@demo.com      | demo123  |
| Reviewer | reviewer@demo.com    | demo123  |
| Admin    | admin@demo.com       | demo123  |

Or click the **Author / Reviewer / Admin** demo buttons on the login
page to auto-fill credentials, or use the **Register** tab to create
a brand-new account (stored in browser localStorage for the front-end
demo flow, and also insertable via the `/api/register` endpoint).

## 🗄️ Database

- **Engine:** SQLite (zero-config, single file at `database/cms.db`)
- **Schema:** `database/schema.sql` — tables: `users`, `conferences`,
  `papers`, `assignments`, `reviews`, `certificates`, `notifications`
- **Connection:** `app.py` opens a per-request SQLite connection via
  Flask's `g` context (see `get_db()` / `close_db()`), with foreign
  keys enabled.
- **Passwords:** hashed with Werkzeug's `generate_password_hash` /
  `check_password_hash` — never stored in plain text.
- **Switching to MySQL/Postgres:** the schema uses standard SQL with
  SQLite-specific `AUTOINCREMENT`; swap that for `AUTO_INCREMENT`
  (MySQL) or `SERIAL` (Postgres), and swap `sqlite3.connect(...)` in
  `app.py` for `mysql.connector` / `psycopg2` + a connection pool.

## 🔌 REST API (used by static/js/common.js)

| Method | Endpoint                          | Description                     |
|--------|------------------------------------|----------------------------------|
| POST   | `/api/register`                    | Create a new user                |
| POST   | `/api/login`                       | Authenticate, returns a token    |
| GET    | `/api/conferences`                 | List conferences + submission counts |
| POST   | `/api/conferences`                 | Create a conference (admin)      |
| GET    | `/api/papers?author_id=`           | List a user's submitted papers   |
| GET    | `/api/papers?reviewer_id=`         | List papers assigned to a reviewer |
| POST   | `/api/papers`                      | Submit a new paper               |
| PUT    | `/api/papers/<id>/status`          | Update a paper's status          |
| GET    | `/api/reviews`                     | List all reviews                 |
| POST   | `/api/reviews`                     | Submit/update a review           |
| PUT    | `/api/reviews/<id>/publish`        | Admin publishes a review result  |
| GET    | `/api/notifications?user_id=`      | List a user's notifications      |
| PUT    | `/api/notifications/<id>/read`     | Mark a notification read         |
| GET    | `/api/health`                      | Health check                     |

> **Note:** the bundled dashboard HTML files ship with a client-side
> demo mode (localStorage) so the whole app works instantly with
> **no backend running at all** — just open the HTML files, or serve
> them with any static server. `app.py` + the database layer are
> there for anyone who wants to wire the UI up to real persistence;
> `static/js/common.js` has ready-made `CMS.login()`, `CMS.getPapers()`,
> etc. helpers matching the routes above.

## 🧪 Test checklist

- [ ] `python app.py` starts without errors, prints the DB path
- [ ] `http://localhost:5000/` loads the landing page
- [ ] Login with each demo account lands on the correct dashboard
- [ ] Wrong password shows an inline error
- [ ] Register a new account → auto-redirects to its dashboard
- [ ] Visiting `admin_dashboard.html` while logged out redirects to `login.html`
- [ ] Dark mode toggle persists after refresh
- [ ] `curl http://localhost:5000/api/health` returns `{"status":"ok",...}`

## 🐛 Troubleshooting

**`ModuleNotFoundError: No module named 'flask_cors'`**
→ `pip install -r requirements.txt`

**Dashboard shows "redirecting to login"**
→ Check browser DevTools → Application → Local Storage for `cms_session`.

**Port already in use**
→ `PORT=5050 python app.py` (or edit `.env`)

**Want to reset all data**
→ delete `database/cms.db` and run `python init_db.py` again.

## 📱 Access from your phone (same Wi-Fi)

```bash
python app.py            # already binds 0.0.0.0
ipconfig / ifconfig       # find your machine's LAN IP
```
Then open `http://<your-ip>:5000/login.html` on your phone.
