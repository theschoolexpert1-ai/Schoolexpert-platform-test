-- 002: tiered plans (School/Vendor Basic-Plus-Pro), entitlements, upgrades, payouts, AI School Match,
--      attribution (SEO/SEM), mobile API tokens, legacy-site integration, analytics, guides.

ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS subscriptions_status_check;
ALTER TABLE subscriptions ADD CONSTRAINT subscriptions_status_check CHECK (status IN ('active','expired','cancelled','upgraded'));
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS upgraded_from bigint REFERENCES subscriptions(id);
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS amount_paise bigint;
CREATE INDEX IF NOT EXISTS subscriptions_active_idx ON subscriptions (org_id, status, ends_at);

ALTER TABLE plans ADD COLUMN IF NOT EXISTS family text;           -- school | vendor | teacher | parent | addon
ALTER TABLE plans ADD COLUMN IF NOT EXISTS level int;             -- 1 basic, 2 plus, 3 pro
ALTER TABLE plans ADD COLUMN IF NOT EXISTS badge text;
ALTER TABLE plans ADD COLUMN IF NOT EXISTS highlight text;

-- attribution for SEO/SEM (first touch)
ALTER TABLE users ADD COLUMN IF NOT EXISTS attribution jsonb;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS attribution jsonb;
ALTER TABLE organisations ADD COLUMN IF NOT EXISTS attribution jsonb;

-- daily listing analytics (views, unlocks, leads) for dashboards
CREATE TABLE IF NOT EXISTS listing_stats (
  listing_id bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE, day date NOT NULL,
  views int NOT NULL DEFAULT 0, unlocks int NOT NULL DEFAULT 0, leads int NOT NULL DEFAULT 0, match_appearances int NOT NULL DEFAULT 0,
  PRIMARY KEY (listing_id, day)
);

-- marketplace commission ledger & seller payouts
CREATE TABLE IF NOT EXISTS seller_ledger (
  id bigserial PRIMARY KEY, order_id bigint NOT NULL REFERENCES orders(id) ON DELETE CASCADE, order_item_id bigint REFERENCES order_items(id) ON DELETE CASCADE,
  seller_org_id bigint NOT NULL REFERENCES organisations(id), gross_paise bigint NOT NULL, commission_pct numeric(5,2) NOT NULL,
  commission_paise bigint NOT NULL, net_paise bigint NOT NULL, status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','payable','paid','reversed')),
  payout_ref text, paid_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS seller_ledger_org_idx ON seller_ledger (seller_org_id, status);

-- sponsored placements: purchased self-serve, approved by Growth desk
ALTER TABLE ad_placements ADD COLUMN IF NOT EXISTS order_id bigint REFERENCES orders(id);
ALTER TABLE ad_placements ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'approved';
ALTER TABLE ad_placements ADD COLUMN IF NOT EXISTS city text;

-- AI School Match
CREATE TABLE IF NOT EXISTS school_match_sessions (
  id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  user_id bigint REFERENCES users(id) ON DELETE SET NULL, prefs jsonb NOT NULL, results jsonb NOT NULL DEFAULT '[]',
  summary text, ai_used boolean NOT NULL DEFAULT false, attribution jsonb, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS shortlists (
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE, listing_id bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  note text, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (user_id, listing_id)
);

-- mobile / partner API tokens
CREATE TABLE IF NOT EXISTS api_tokens (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE, token_hash text UNIQUE NOT NULL,
  device text, last_used_at timestamptz, expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);

-- legacy website integration: pages at their old URLs + 301 redirect map
ALTER TABLE pages ADD COLUMN IF NOT EXISTS path text UNIQUE;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS body_format text NOT NULL DEFAULT 'markdown';   -- markdown | html
ALTER TABLE pages ADD COLUMN IF NOT EXISTS show_in_footer boolean NOT NULL DEFAULT false;
CREATE TABLE IF NOT EXISTS redirects (
  from_path text PRIMARY KEY, to_url text NOT NULL, code int NOT NULL DEFAULT 301, hits int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now()
);

-- SEO guides (content marketing)
CREATE TABLE IF NOT EXISTS articles (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL, title text NOT NULL, audience text NOT NULL DEFAULT 'parents',
  summary text, body text NOT NULL, cover_url text, keywords text, author text DEFAULT 'The School Expert™ Team',
  published_at timestamptz, updated_at timestamptz NOT NULL DEFAULT now()
);

