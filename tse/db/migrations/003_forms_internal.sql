-- Per-form internal review data (from the "For The School Expert — internal use" / CRM blocks of your forms)
ALTER TABLE registrations ADD COLUMN IF NOT EXISTS internal jsonb NOT NULL DEFAULT '{}';
-- One provider -> many courses: each course is its own registration + listing, linked to the first one
ALTER TABLE registrations ADD COLUMN IF NOT EXISTS parent_registration_id bigint REFERENCES registrations(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS registrations_parent_idx ON registrations (parent_registration_id);
