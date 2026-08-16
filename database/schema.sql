-- ═══════════════════════════════════════════════════════════
-- Conference Management System — Database Schema
-- Compatible with SQLite (default, zero-setup) and MySQL/Postgres
-- with minor type tweaks noted inline.
-- ═══════════════════════════════════════════════════════════

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────
-- USERS  (authors, reviewers, admins)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,   -- MySQL: INT AUTO_INCREMENT PRIMARY KEY
    name            TEXT    NOT NULL,
    email           TEXT    NOT NULL UNIQUE,
    password_hash   TEXT    NOT NULL,
    role            TEXT    NOT NULL CHECK (role IN ('author','reviewer','admin')),
    college         TEXT,
    phone           TEXT,
    bio             TEXT,
    expertise       TEXT,                                 -- reviewer expertise area
    avatar_letter   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────
-- CONFERENCES
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conferences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    venue           TEXT,
    conf_date       DATE,
    deadline        DATE,
    description     TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────
-- PAPERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS papers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    abstract        TEXT,
    keywords        TEXT,
    author_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conference_id   INTEGER NOT NULL REFERENCES conferences(id) ON DELETE CASCADE,
    file_path       TEXT,                                  -- stored under /uploads
    status          TEXT    NOT NULL DEFAULT 'submitted'
                    CHECK (status IN ('submitted','under_review','accepted','rejected')),
    submitted_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────
-- PAPER <-> REVIEWER ASSIGNMENT
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assignments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    reviewer_id     INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    assigned_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_id, reviewer_id)
);

-- ─────────────────────────────────────────────
-- REVIEWS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        INTEGER NOT NULL REFERENCES papers(id)    ON DELETE CASCADE,
    reviewer_id     INTEGER NOT NULL REFERENCES users(id)     ON DELETE CASCADE,
    score           INTEGER CHECK (score BETWEEN 0 AND 10),
    decision        TEXT    CHECK (decision IN ('Accept','Reject')),
    comments        TEXT,
    criteria        TEXT,                                    -- JSON-encoded checklist
    published       INTEGER NOT NULL DEFAULT 0,               -- 0/1 boolean (admin publish step)
    reviewed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_id, reviewer_id)
);

-- ─────────────────────────────────────────────
-- CERTIFICATES
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS certificates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    user_id         INTEGER NOT NULL REFERENCES users(id)  ON DELETE CASCADE,
    cert_type       TEXT    NOT NULL DEFAULT 'acceptance'
                    CHECK (cert_type IN ('acceptance','participation','best_paper','completed')),
    cert_code       TEXT    NOT NULL UNIQUE,
    issued_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────
-- NOTIFICATIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    message         TEXT    NOT NULL,
    is_read         INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ─────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_papers_author       ON papers(author_id);
CREATE INDEX IF NOT EXISTS idx_papers_conference    ON papers(conference_id);
CREATE INDEX IF NOT EXISTS idx_reviews_paper        ON reviews(paper_id);
CREATE INDEX IF NOT EXISTS idx_reviews_reviewer     ON reviews(reviewer_id);
CREATE INDEX IF NOT EXISTS idx_assignments_reviewer ON assignments(reviewer_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user   ON notifications(user_id);

-- ═══════════════════════════════════════════════════════════
-- SEED DATA — demo accounts (password for all: demo123)
-- Password hashes below are werkzeug generate_password_hash()
-- output for the plaintext "demo123" — app.py verifies these
-- with check_password_hash() at login.
-- ═══════════════════════════════════════════════════════════

INSERT OR IGNORE INTO users (id, name, email, password_hash, role, college, avatar_letter) VALUES
 (1, 'Madhav Kumar',  'author@demo.com',   'scrypt:32768:8:1$PLACEHOLDER_AUTHOR',   'author',   'IIT Madras',      'M'),
 (2, 'Priya Nair',    'reviewer@demo.com', 'scrypt:32768:8:1$PLACEHOLDER_REVIEWER', 'reviewer', 'NIT Trichy',      'P'),
 (3, 'Dr. Ramesh K.', 'admin@demo.com',    'scrypt:32768:8:1$PLACEHOLDER_ADMIN',    'admin',    'Anna University', 'R');

-- NOTE: the placeholder hashes above are NOT valid werkzeug hashes.
-- Running `python app.py` the first time calls seed_demo_users()
-- in app.py, which re-inserts these three accounts with REAL
-- password hashes generated at runtime (see app.py -> init_db()).
-- This file is kept for reference / manual `sqlite3 cms.db < schema.sql`
-- use; when in doubt, just run app.py and let it initialize the DB.

INSERT OR IGNORE INTO conferences (id, name, venue, conf_date, deadline, description, created_by) VALUES
 (1, 'AI Summit 2026',   'Chennai Trade Centre',            '2026-09-24', '2026-09-15', 'Artificial intelligence research and applications.', 3),
 (2, 'IoTConf 2026',     'Bangalore International Centre',  '2026-10-12', '2026-10-01', 'Internet of Things systems and security.', 3),
 (3, 'SmartTech 2026',   'COEP Pune',                        '2026-11-05', '2026-10-25', 'Smart cities and embedded architecture.', 3),
 (4, 'NLP Summit 2026',  'IIT Delhi',                         '2026-12-20', '2026-12-10', 'Natural language processing and LLMs.', 3);

INSERT OR IGNORE INTO papers (id, title, abstract, keywords, author_id, conference_id, status) VALUES
 (1, 'AI in Healthcare Systems',
     'This paper proposes an AI-driven system for early diagnosis of chronic diseases using patient data from electronic health records.',
     'AI, Healthcare, LSTM, CNN', 1, 1, 'under_review'),
 (2, 'IoT Security Framework',
     'A lightweight security framework for resource-constrained IoT devices.',
     'IoT, Security', 1, 2, 'accepted'),
 (3, 'Smart City Architecture',
     'Architecture proposal for integrated smart city infrastructure.',
     'Smart Cities, Architecture', 1, 3, 'submitted');

INSERT OR IGNORE INTO assignments (id, paper_id, reviewer_id) VALUES
 (1, 1, 2);

INSERT OR IGNORE INTO notifications (id, user_id, message) VALUES
 (1, 1, 'A reviewer has been assigned to "AI in Healthcare Systems".'),
 (2, 2, 'New paper "AI in Healthcare Systems" assigned to you for review.'),
 (3, 3, '5 new paper submissions since yesterday.');
