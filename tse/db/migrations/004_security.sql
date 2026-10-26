-- ============================================================================
-- Security hardening at the database layer
--   1. Row-level security (RLS): tenant data is filtered INSIDE PostgreSQL, so a bug in application code cannot
--      leak one school's / vendor's / parent's records to another. Context is set per query by tse/db/db.py.
--   2. Tamper-evident, append-only audit log (hash chain; UPDATE/DELETE blocked).
--   3. Identity hardening columns: lockout, MFA, password age, session metadata.
--   4. Shared rate-limit store so limits hold across all app workers/servers.
-- ============================================================================

-- ---------- 1. RLS helpers ----------
CREATE OR REPLACE FUNCTION app_bypass() RETURNS boolean LANGUAGE sql STABLE AS
$$ SELECT coalesce(current_setting('app.bypass', true), '') = 'on' $$;
CREATE OR REPLACE FUNCTION app_uid() RETURNS bigint LANGUAGE sql STABLE AS
$$ SELECT nullif(current_setting('app.user_id', true), '')::bigint $$;
CREATE OR REPLACE FUNCTION app_orgs() RETURNS bigint[] LANGUAGE sql STABLE AS
$$ SELECT coalesce(string_to_array(nullif(current_setting('app.org_ids', true), ''), ',')::bigint[], '{}'::bigint[]) $$;

DO $$
DECLARE t text; cond text;
BEGIN
  FOR t, cond IN VALUES
    ('registrations',   'user_id = app_uid() OR org_id = ANY(app_orgs())'),
    ('leads',           'org_id = ANY(app_orgs()) OR user_id = app_uid()'),
    ('job_applications','teacher_id = app_uid() OR EXISTS (SELECT 1 FROM jobs j WHERE j.id = job_id AND j.org_id = ANY(app_orgs()))'),
    ('orders',          'user_id = app_uid() OR org_id = ANY(app_orgs()) OR EXISTS (SELECT 1 FROM shipments s WHERE s.order_id = orders.id AND s.seller_org_id = ANY(app_orgs()))'),
    ('seller_ledger',   'seller_org_id = ANY(app_orgs())'),
    ('support_tickets', 'user_id = app_uid() OR org_id = ANY(app_orgs())'),
    ('api_tokens',      'user_id = app_uid()'),
    ('addresses',       'user_id = app_uid() OR org_id = ANY(app_orgs())'),
    ('cart_items',      'user_id = app_uid()'),
    ('notifications',   'user_id = app_uid()'),
    ('unlock_packs',    'user_id = app_uid()'),
    ('unlocks',         'user_id = app_uid()'),
    ('shortlists',      'user_id = app_uid()'),
    ('pa_requests',     'user_id = app_uid()'),
    ('expert_requests', 'user_id = app_uid() OR org_id = ANY(app_orgs())')
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);        -- applies to the table owner too
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    -- reads/updates/deletes: only your own rows (staff & trusted system jobs bypass, and are audited);
    -- inserts: allowed (e.g. a parent's enquiry creates a lead owned by the school), validated by the application.
    EXECUTE format('CREATE POLICY tenant_isolation ON %I USING (app_bypass() OR %s) WITH CHECK (true)', t, cond);
  END LOOP;
END $$;

-- ---------- 2. Append-only, hash-chained audit log ----------
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS prev_hash text;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS row_hash text;
CREATE OR REPLACE FUNCTION audit_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p text;
BEGIN
  PERFORM pg_advisory_xact_lock(424242);                                    -- serialise the chain
  SELECT row_hash INTO p FROM audit_log ORDER BY id DESC LIMIT 1;
  NEW.prev_hash := coalesce(p, 'genesis');
  NEW.row_hash := encode(digest(NEW.prev_hash || '|' || coalesce(NEW.actor_id::text, '') || '|' || coalesce(NEW.action, '') || '|' ||
                  coalesce(NEW.entity, '') || '|' || coalesce(NEW.entity_id, '') || '|' || coalesce(NEW.org_id::text, '') || '|' ||
                  coalesce(host(NEW.ip), '') || '|' || NEW.meta::text || '|' || NEW.created_at::text, 'sha256'), 'hex');
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS audit_chain ON audit_log;
CREATE TRIGGER audit_chain BEFORE INSERT ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_chain();
CREATE OR REPLACE FUNCTION audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' AND coalesce(current_setting('app.retention', true), '') = 'on' THEN RETURN OLD; END IF;  -- scheduled retention purge only
  RAISE EXCEPTION 'audit_log is append-only';
END $$;
DROP TRIGGER IF EXISTS audit_immutable ON audit_log;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION audit_immutable();

-- ---------- 3. Identity hardening ----------
ALTER TABLE users ADD COLUMN IF NOT EXISTS failed_logins int NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS locked_until timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_secret_enc text;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE users ADD COLUMN IF NOT EXISTS mfa_recovery_hashes text[] NOT NULL DEFAULT '{}';
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at timestamptz;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_ip inet;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS last_seen_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS ip inet;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS user_agent text;
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);

-- ---------- 4. Shared rate limiting (UNLOGGED: fast, not replicated, safe to lose on crash) ----------
CREATE UNLOGGED TABLE IF NOT EXISTS rate_events (
  bucket text NOT NULL, at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS rate_events_idx ON rate_events (bucket, at);

-- ---------- 5. Least-privilege database roles (only when run by a role allowed to create roles) ----------
-- Production: the application connects as tse_app (no DDL), migrations run as the owner, reporting uses tse_readonly.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = current_user AND (rolsuper OR rolcreaterole)) THEN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tse_app') THEN CREATE ROLE tse_app LOGIN; END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tse_readonly') THEN CREATE ROLE tse_readonly LOGIN; END IF;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tse_app') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA public TO tse_app';
    EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tse_app';
    EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tse_app';
    EXECUTE 'REVOKE UPDATE, DELETE ON audit_log FROM tse_app';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tse_app';
    EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO tse_app';
    EXECUTE 'ALTER ROLE tse_app SET statement_timeout = ''15s''';
    EXECUTE 'ALTER ROLE tse_app SET idle_in_transaction_session_timeout = ''30s''';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'tse_readonly') THEN
    EXECUTE 'GRANT USAGE ON SCHEMA public TO tse_readonly';
    EXECUTE 'GRANT SELECT ON listings, categories, plans, subscriptions, orders, order_items, listing_stats, school_match_sessions, events, event_registrations TO tse_readonly';
    EXECUTE 'ALTER ROLE tse_readonly SET default_transaction_read_only = on';
  END IF;
END $$;
