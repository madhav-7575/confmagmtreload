-- MySQL-ready version of the Conference Management schema
-- Converted from SQLite-friendly schema.sql: removes PRAGMA,
-- converts AUTOINCREMENT -> AUTO_INCREMENT, and adapts INSERT OR IGNORE.

-- Recommended: run this in MySQL Workbench connected to the `cms` database.

-- ─────────────────────────────────────────────
-- USERS  (authors, reviewers, admins)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255)    NOT NULL,
    email           VARCHAR(255)    NOT NULL UNIQUE,
    password_hash   VARCHAR(255)    NOT NULL,
    role            VARCHAR(32)    NOT NULL CHECK (role IN ('author','reviewer','admin')),
    college         VARCHAR(255),
    phone           TEXT,
    bio             TEXT,
    expertise       TEXT,
    avatar_letter   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────
-- CONFERENCES
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conferences (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(255)    NOT NULL,
    venue           VARCHAR(255),
    conf_date       DATE,
    deadline        DATE,
    description     TEXT,
    created_by      INT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (created_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────
-- PAPERS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS papers (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    title           VARCHAR(255)    NOT NULL,
    abstract        TEXT,
    keywords        TEXT,
    author_id       INT NOT NULL,
    conference_id   INT NOT NULL,
    file_path       TEXT,
    status          VARCHAR(32)    NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted','under_review','accepted','rejected')),
    submitted_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (author_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (conference_id) REFERENCES conferences(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────
-- ASSIGNMENTS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS assignments (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    paper_id        INT NOT NULL,
    reviewer_id     INT NOT NULL,
    assigned_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_id, reviewer_id),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (reviewer_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────
-- REVIEWS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS reviews (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    paper_id        INT NOT NULL,
    reviewer_id     INT NOT NULL,
    score           INT CHECK (score BETWEEN 0 AND 10),
    decision        VARCHAR(16)    CHECK (decision IN ('Accept','Reject')),
    comments        TEXT,
    criteria        TEXT,
    published       TINYINT NOT NULL DEFAULT 0,
    reviewed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(paper_id, reviewer_id),
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (reviewer_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────
-- CERTIFICATES
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS certificates (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    paper_id        INT NOT NULL,
    user_id         INT NOT NULL,
    cert_type       VARCHAR(64)    NOT NULL DEFAULT 'acceptance' CHECK (cert_type IN ('acceptance','participation','best_paper')),
    cert_code       VARCHAR(255)    NOT NULL UNIQUE,
    issued_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (paper_id) REFERENCES papers(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────
-- NOTIFICATIONS
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_id         INT NOT NULL,
    message         TEXT    NOT NULL,
    is_read         TINYINT NOT NULL DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ─────────────────────────────────────────────
-- INDEXES
-- ─────────────────────────────────────────────
CREATE INDEX idx_papers_author       ON papers(author_id);
CREATE INDEX idx_papers_conference    ON papers(conference_id);
CREATE INDEX idx_reviews_paper        ON reviews(paper_id);
CREATE INDEX idx_reviews_reviewer     ON reviews(reviewer_id);
CREATE INDEX idx_assignments_reviewer ON assignments(reviewer_id);
CREATE INDEX idx_notifications_user   ON notifications(user_id);

-- ─────────────────────────────────────────────
-- SEED DATA — demo accounts (password for all: demo123)
-- Replace the placeholder hashes or re-run the app to generate werkzeug hashes.
-- ─────────────────────────────────────────────

INSERT IGNORE INTO users (id, name, email, password_hash, role, college, avatar_letter) VALUES
 (1, 'Madhav Kumar',  'author@demo.com',   'scrypt:32768:8:1$PLACEHOLDER_AUTHOR',   'author',   'IIT Madras',      'M'),
 (2, 'Priya Nair',    'reviewer@demo.com', 'scrypt:32768:8:1$PLACEHOLDER_REVIEWER', 'reviewer', 'NIT Trichy',      'P'),
 (3, 'Dr. Ramesh K.', 'admin@demo.com',    'scrypt:32768:8:1$PLACEHOLDER_ADMIN',    'admin',    'Anna University', 'R');

INSERT IGNORE INTO conferences (id, name, venue, conf_date, deadline, description, created_by) VALUES
 (1, 'AI Summit 2026',   'Chennai Trade Centre',            '2026-09-24', '2026-09-15', 'Artificial intelligence research and applications.', 3),
 (2, 'IoTConf 2026',     'Bangalore International Centre',  '2026-10-12', '2026-10-01', 'Internet of Things systems and security.', 3),
 (3, 'SmartTech 2026',   'COEP Pune',                        '2026-11-05', '2026-10-25', 'Smart cities and embedded architecture.', 3),
 (4, 'NLP Summit 2026',  'IIT Delhi',                         '2026-12-20', '2026-12-10', 'Natural language processing and LLMs.', 3);

INSERT IGNORE INTO papers (id, title, abstract, keywords, author_id, conference_id, status) VALUES
 (1, 'AI in Healthcare Systems',
     'This paper proposes an AI-driven system for early diagnosis of chronic diseases using patient data from electronic health records.',
     'AI, Healthcare, LSTM, CNN', 1, 1, 'under_review'),
 (2, 'IoT Security Framework',
     'A lightweight security framework for resource-constrained IoT devices.',
     'IoT, Security', 1, 2, 'accepted'),
 (3, 'Smart City Architecture',
     'Architecture proposal for integrated smart city infrastructure.',
     'Smart Cities, Architecture', 1, 3, 'submitted');

INSERT IGNORE INTO assignments (id, paper_id, reviewer_id) VALUES
 (1, 1, 2);

INSERT IGNORE INTO notifications (id, user_id, message) VALUES
 (1, 1, 'A reviewer has been assigned to "AI in Healthcare Systems".'),
 (2, 2, 'New paper "AI in Healthcare Systems" assigned to you for review.'),
 (3, 3, '5 new paper submissions since yesterday.');
