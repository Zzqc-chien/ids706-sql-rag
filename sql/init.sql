-- SQL Quiz database setup (Supabase / PostgreSQL)
--
-- Run this whole file once in the Supabase SQL Editor.
-- It is safe to run again: the quiz data is rebuilt from scratch,
-- while saved answers and the audit log are kept.
--
-- NO PASSWORDS IN THIS FILE. Role passwords are set separately
-- (see README, "Set the role passwords"), and never committed to git.


-- Part 1. Quiz data (schema "quiz") - this is what quiz takers query.
-- Topic: a (fictional) graduate program's course enrollments.
DROP SCHEMA IF EXISTS quiz CASCADE;
CREATE SCHEMA quiz;

CREATE TABLE quiz.students (
    student_id  INT PRIMARY KEY,
    name        TEXT NOT NULL,
    program     TEXT NOT NULL,          -- MIDS, MEM, MS Stats, MEng
    start_year  INT  NOT NULL
);

CREATE TABLE quiz.courses (
    course_id    INT PRIMARY KEY,
    course_code  TEXT NOT NULL UNIQUE,  -- e.g. 'IDS 706'
    title        TEXT NOT NULL,
    department   TEXT NOT NULL,         -- IDS, STA, CS, ENV
    credits      INT  NOT NULL
);

CREATE TABLE quiz.enrollments (
    enrollment_id INT PRIMARY KEY,
    student_id    INT NOT NULL REFERENCES quiz.students(student_id),
    course_id     INT NOT NULL REFERENCES quiz.courses(course_id),
    term          TEXT NOT NULL,         -- 'Fall 2025', 'Spring 2026', 'Fall 2026'
    grade_points  NUMERIC(2,1),          -- 0.0-4.0; NULL = still in progress
    UNIQUE (student_id, course_id, term)
);

INSERT INTO quiz.students (student_id, name, program, start_year) VALUES
 (1,  'Ava Chen',        'MIDS',     2025),
 (2,  'Ben Okafor',      'MIDS',     2025),
 (3,  'Chloe Martin',    'MEM',      2024),
 (4,  'Daniel Kim',      'MIDS',     2026),
 (5,  'Emma Rossi',      'MS Stats', 2025),
 (6,  'Farah Haddad',    'MIDS',     2026),
 (7,  'George Liu',      'MEng',     2025),
 (8,  'Hana Sato',       'MIDS',     2025),
 (9,  'Ivan Petrov',     'MS Stats', 2026),
 (10, 'Julia Santos',    'MEM',      2025),
 (11, 'Kevin Brown',     'MEng',     2026),
 (12, 'Lina Wang',       'MIDS',     2026);

INSERT INTO quiz.courses (course_id, course_code, title, department, credits) VALUES
 (1,  'IDS 706', 'Data Engineering Systems',          'IDS', 3),
 (2,  'IDS 705', 'Principles of Machine Learning',    'IDS', 3),
 (3,  'IDS 702', 'Modeling and Representation',       'IDS', 3),
 (4,  'IDS 703', 'Natural Language Processing',       'IDS', 3),
 (5,  'STA 602', 'Bayesian Statistics',               'STA', 3),
 (6,  'STA 610', 'Hierarchical Models',               'STA', 3),
 (7,  'CS 571',  'Machine Learning',                  'CS',  3),
 (8,  'CS 516',  'Database Systems',                  'CS',  3),
 (9,  'ENV 761', 'Spatial Data Analysis',             'ENV', 2),
 (10, 'ENV 765', 'Environmental Data Visualization',  'ENV', 1);

INSERT INTO quiz.enrollments (enrollment_id, student_id, course_id, term, grade_points) VALUES
 -- Fall 2025 (completed)
 (1,  1, 3, 'Fall 2025', 4.0),
 (2,  1, 5, 'Fall 2025', 4.0),
 (3,  2, 3, 'Fall 2025', 3.3),
 (4,  2, 8, 'Fall 2025', 3.7),
 (5,  3, 9, 'Fall 2025', 3.7),
 (6,  3, 10,'Fall 2025', 4.0),
 (7,  5, 5, 'Fall 2025', 4.0),
 (8,  5, 3, 'Fall 2025', 3.7),
 (9,  7, 7, 'Fall 2025', 3.0),
 (10, 7, 8, 'Fall 2025', 3.3),
 (11, 8, 3, 'Fall 2025', 3.7),
 (12, 8, 5, 'Fall 2025', 3.3),
 (13, 10, 9,'Fall 2025', 3.0),
 -- Spring 2026 (completed)
 (14, 1, 2, 'Spring 2026', 3.7),
 (15, 1, 4, 'Spring 2026', 4.0),
 (16, 2, 2, 'Spring 2026', 3.0),
 (17, 3, 5, 'Spring 2026', 3.3),
 (18, 5, 6, 'Spring 2026', 4.0),
 (19, 5, 2, 'Spring 2026', 3.7),
 (20, 7, 2, 'Spring 2026', 3.7),
 (21, 8, 2, 'Spring 2026', 4.0),
 (22, 8, 4, 'Spring 2026', 3.7),
 (23, 10, 10,'Spring 2026', 3.7),
 (24, 10, 5, 'Spring 2026', 2.7),
 -- Fall 2026 (in progress: grade_points is NULL)
 (25, 1, 1,  'Fall 2026', NULL),
 (26, 2, 1,  'Fall 2026', NULL),
 (27, 4, 1,  'Fall 2026', NULL),
 (28, 4, 3,  'Fall 2026', NULL),
 (29, 6, 1,  'Fall 2026', NULL),
 (30, 6, 5,  'Fall 2026', NULL),
 (31, 8, 1,  'Fall 2026', NULL),
 (32, 9, 5,  'Fall 2026', NULL),
 (33, 9, 6,  'Fall 2026', NULL),
 (34, 11, 7, 'Fall 2026', NULL),
 (35, 12, 1, 'Fall 2026', NULL),
 (36, 12, 3, 'Fall 2026', NULL),
 (37, 5, 7,  'Fall 2026', NULL),
 (38, 7, 1,  'Fall 2026', NULL);


-- Part 2. App tables (schema "app") - saved answers + audit log.
-- Quiz takers never query these directly.
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.submissions (
    id           BIGSERIAL PRIMARY KEY,
    user_id      UUID        NOT NULL,      -- Supabase Auth user id
    user_email   TEXT        NOT NULL,
    question_id  TEXT        NOT NULL,
    sql_text     TEXT        NOT NULL,
    saved_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.audit_log (
    id           BIGSERIAL PRIMARY KEY,
    logged_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id      UUID        NOT NULL,
    user_email   TEXT        NOT NULL,
    action       TEXT        NOT NULL CHECK (action IN ('run', 'save')),
    question_id  TEXT,
    sql_text     TEXT,
    success      BOOLEAN     NOT NULL,
    row_count    INT,
    error        TEXT
);

-- Integrity check: the audit log is append-only.
-- Any UPDATE, DELETE or TRUNCATE raises an error - for every role,
-- including the app's role and even the postgres owner.
CREATE OR REPLACE FUNCTION app.block_audit_changes()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % is not allowed', TG_OP;
END;
$$;

DROP TRIGGER IF EXISTS audit_log_no_update_delete ON app.audit_log;
CREATE TRIGGER audit_log_no_update_delete
    BEFORE UPDATE OR DELETE ON app.audit_log
    FOR EACH ROW EXECUTE FUNCTION app.block_audit_changes();

DROP TRIGGER IF EXISTS audit_log_no_truncate ON app.audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON app.audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION app.block_audit_changes();


-- Part 3. Database roles (least privilege)
--
--   quiz_reader : runs the SQL that quiz takers type.
--                 SELECT on the quiz tables only. Read-only, 5 s limit.
--   quiz_app    : writes saved answers and audit rows.
--                 INSERT + SELECT on app tables only. No UPDATE/DELETE.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quiz_reader') THEN
        CREATE ROLE quiz_reader LOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quiz_app') THEN
        CREATE ROLE quiz_app LOGIN;
    END IF;
END
$$;

-- quiz_reader: read the quiz tables, nothing else
GRANT USAGE  ON SCHEMA quiz TO quiz_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA quiz TO quiz_reader;
REVOKE ALL   ON SCHEMA app FROM quiz_reader;
ALTER ROLE quiz_reader SET search_path = quiz;
ALTER ROLE quiz_reader SET default_transaction_read_only = on;
ALTER ROLE quiz_reader SET statement_timeout = '5s';

-- quiz_app: append to the app tables, nothing else
GRANT USAGE          ON SCHEMA app TO quiz_app;
GRANT SELECT, INSERT ON app.submissions, app.audit_log TO quiz_app;
GRANT USAGE          ON ALL SEQUENCES IN SCHEMA app TO quiz_app;
REVOKE UPDATE, DELETE, TRUNCATE ON app.submissions, app.audit_log FROM quiz_app;
ALTER ROLE quiz_app SET statement_timeout = '5s';


-- Part 4. Row Level Security policies
--
-- New Supabase projects can switch RLS on automatically for every new
-- table. With RLS on and no policy, quiz_reader sees 0 rows (no error)
-- and quiz_app cannot insert. These policies say exactly who may do what.
-- RLS is switched on explicitly, so the result is the same on any project.
ALTER TABLE quiz.students    ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz.courses     ENABLE ROW LEVEL SECURITY;
ALTER TABLE quiz.enrollments ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.submissions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE app.audit_log    ENABLE ROW LEVEL SECURITY;

-- quiz_reader may read every row of the quiz tables
DROP POLICY IF EXISTS reader_select ON quiz.students;
DROP POLICY IF EXISTS reader_select ON quiz.courses;
DROP POLICY IF EXISTS reader_select ON quiz.enrollments;
CREATE POLICY reader_select ON quiz.students    FOR SELECT TO quiz_reader USING (true);
CREATE POLICY reader_select ON quiz.courses     FOR SELECT TO quiz_reader USING (true);
CREATE POLICY reader_select ON quiz.enrollments FOR SELECT TO quiz_reader USING (true);

-- quiz_app may add and read saved answers and audit rows (no UPDATE/DELETE policy)
DROP POLICY IF EXISTS app_select ON app.submissions;
DROP POLICY IF EXISTS app_insert ON app.submissions;
DROP POLICY IF EXISTS app_select ON app.audit_log;
DROP POLICY IF EXISTS app_insert ON app.audit_log;
CREATE POLICY app_select ON app.submissions FOR SELECT TO quiz_app USING (true);
CREATE POLICY app_insert ON app.submissions FOR INSERT TO quiz_app WITH CHECK (true);
CREATE POLICY app_select ON app.audit_log   FOR SELECT TO quiz_app USING (true);
CREATE POLICY app_insert ON app.audit_log   FOR INSERT TO quiz_app WITH CHECK (true);