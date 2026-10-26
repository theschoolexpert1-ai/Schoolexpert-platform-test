-- Teachers Hub (formerly the standalone TeachersInn app): upskilling with CPD certificates, tutorials, lesson planner,
-- educator network with private messaging, mentorship. Teachers only. No student / child data is collected anywhere here.

-- Hub profile: the networking side of a teacher account (the recruitment side stays in teacher_profiles).
CREATE TABLE IF NOT EXISTS hub_members (
  user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  designation text NOT NULL DEFAULT '', school text NOT NULL DEFAULT '', subjects text NOT NULL DEFAULT '',
  grades text NOT NULL DEFAULT '', board text NOT NULL DEFAULT '', experience_years int NOT NULL DEFAULT 0 CHECK (experience_years BETWEEN 0 AND 60),
  bio text NOT NULL DEFAULT '',
  directory_visible boolean NOT NULL DEFAULT false,      -- privacy by default: teachers opt in to the educator directory
  open_to_mentor boolean NOT NULL DEFAULT false,
  mentor_status text NOT NULL DEFAULT 'none' CHECK (mentor_status IN ('none','pending','approved','rejected')),
  cpd_goal int NOT NULL DEFAULT 50 CHECK (cpd_goal BETWEEN 1 AND 500),
  joined_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

-- Upskilling ----------------------------------------------------------------
CREATE TABLE IF NOT EXISTS courses (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL, title text NOT NULL, category text NOT NULL,
  level text NOT NULL DEFAULT 'Beginner', summary text NOT NULL, instructor text NOT NULL,
  cpd_hours int NOT NULL DEFAULT 1 CHECK (cpd_hours BETWEEN 0 AND 200),
  published boolean NOT NULL DEFAULT true, sort int NOT NULL DEFAULT 100, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS course_lessons (
  id bigserial PRIMARY KEY, course_id bigint NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  position int NOT NULL, title text NOT NULL, body text NOT NULL, minutes int NOT NULL DEFAULT 10,
  UNIQUE (course_id, position)
);
CREATE TABLE IF NOT EXISTS course_enrolments (
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_id bigint NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  enrolled_at timestamptz NOT NULL DEFAULT now(), completed_at timestamptz,
  certificate_code text UNIQUE,
  PRIMARY KEY (user_id, course_id)
);
CREATE TABLE IF NOT EXISTS lesson_progress (
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  lesson_id bigint NOT NULL REFERENCES course_lessons(id) ON DELETE CASCADE,
  done_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, lesson_id)
);

-- Tutorials & planner ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS tutorials (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL, title text NOT NULL, category text NOT NULL,
  summary text NOT NULL, steps jsonb NOT NULL DEFAULT '[]', minutes int NOT NULL DEFAULT 5,
  published boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS tutorial_saves (
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tutorial_id bigint NOT NULL REFERENCES tutorials(id) ON DELETE CASCADE,
  saved boolean NOT NULL DEFAULT false, viewed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, tutorial_id)
);
CREATE TABLE IF NOT EXISTS lesson_plans (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title text NOT NULL, subject text NOT NULL DEFAULT '', grade text NOT NULL DEFAULT '', plan_date date,
  duration_min int NOT NULL DEFAULT 40, objectives text NOT NULL DEFAULT '', materials text NOT NULL DEFAULT '',
  activities text NOT NULL DEFAULT '', assessment text NOT NULL DEFAULT '', reflection text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lesson_plans_user ON lesson_plans (user_id, plan_date);

-- Network --------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS connections (
  id bigserial PRIMARY KEY,
  requester_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  addressee_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','declined')),
  created_at timestamptz NOT NULL DEFAULT now(), responded_at timestamptz,
  CHECK (requester_id <> addressee_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS connections_pair ON connections (LEAST(requester_id, addressee_id), GREATEST(requester_id, addressee_id));

-- Private messages between connected educators / mentor pairs. Bodies are AES-256-GCM encrypted at rest.
CREATE TABLE IF NOT EXISTS direct_messages (
  id bigserial PRIMARY KEY,
  sender_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  recipient_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  body_enc text NOT NULL, read_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS direct_messages_pair ON direct_messages (LEAST(sender_id, recipient_id), GREATEST(sender_id, recipient_id), id);
CREATE INDEX IF NOT EXISTS direct_messages_unread ON direct_messages (recipient_id) WHERE read_at IS NULL;

CREATE TABLE IF NOT EXISTS mentorships (
  id bigserial PRIMARY KEY,
  mentee_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  mentor_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  topic text NOT NULL, message text NOT NULL,
  status text NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','active','declined','completed')),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  CHECK (mentee_id <> mentor_id)
);

-- Workshops are ordinary events (kind workshop / webinar, audience teachers) and now carry CPD hours.
ALTER TABLE events ADD COLUMN IF NOT EXISTS cpd_hours int NOT NULL DEFAULT 0;
ALTER TABLE events ADD COLUMN IF NOT EXISTS facilitator text;
ALTER TABLE events ADD COLUMN IF NOT EXISTS category text;

-- Row-level security on every private Teachers Hub table (same model as migration 004).
DO $$
DECLARE t text; cond text;
BEGIN
  FOR t, cond IN VALUES
    ('course_enrolments', 'user_id = app_uid()'),
    ('lesson_progress',   'user_id = app_uid()'),
    ('tutorial_saves',    'user_id = app_uid()'),
    ('lesson_plans',      'user_id = app_uid()'),
    ('connections',       'requester_id = app_uid() OR addressee_id = app_uid()'),
    ('direct_messages',   'sender_id = app_uid() OR recipient_id = app_uid()'),
    ('mentorships',       'mentee_id = app_uid() OR mentor_id = app_uid()')
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (app_bypass() OR %s) WITH CHECK (true)', t, cond);
  END LOOP;
END $$;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tse_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON hub_members, courses, course_lessons, course_enrolments, lesson_progress, tutorials, tutorial_saves,
          lesson_plans, connections, direct_messages, mentorships TO tse_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tse_app;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tse_readonly') THEN
    GRANT SELECT ON hub_members, courses, course_lessons, tutorials TO tse_readonly;
  END IF;
END $$;
