-- File storage inside PostgreSQL, for serverless hosting (Vercel) where the server has no permanent disk.
-- Fine for a prototype and modest volumes; switch STORAGE_BACKEND to s3 for production scale.
CREATE TABLE IF NOT EXISTS blobs (
  key text PRIMARY KEY,                 -- e.g. registrations/2026/10/<uuid>.png
  private boolean NOT NULL DEFAULT false,
  mime text NOT NULL,
  size int NOT NULL,
  data bytea NOT NULL,                  -- private files are already AES-256-GCM encrypted before they get here
  created_at timestamptz NOT NULL DEFAULT now()
);
