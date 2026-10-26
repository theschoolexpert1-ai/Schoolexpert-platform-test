-- The School Expert™ — core schema (PostgreSQL 13+)
-- Conventions: money in paise (bigint), timestamps in UTC (timestamptz), tenant-owned rows carry org_id.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;

-- ============ Identity & tenancy ============
CREATE TABLE users (
  id            bigserial PRIMARY KEY,
  email         citext UNIQUE NOT NULL,
  phone         text,
  name          text NOT NULL,
  password_hash text NOT NULL,
  account_type  text NOT NULL CHECK (account_type IN ('parent','teacher','organisation','admin','staff')),
  is_adult      boolean NOT NULL DEFAULT false,          -- DPDP: platform accounts are for adults (18+)
  email_verified_at timestamptz,
  phone_verified_at timestamptz,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','pending_deletion','deleted')),
  staff_role    text,                                    -- admin | moderator | support | sales | pa_agent (for staff/admin)
  city          text, state text, pincode text,
  avatar_url    text,
  prefs         jsonb NOT NULL DEFAULT '{}',
  nominee       jsonb,                                   -- DPDP s.14 right to nominate
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_login_at timestamptz,
  deleted_at    timestamptz
);
CREATE INDEX ON users (account_type);

CREATE TABLE organisations (                             -- tenants
  id          bigserial PRIMARY KEY,
  name        text NOT NULL,
  slug        text UNIQUE NOT NULL,
  category    text NOT NULL,                             -- schools | vendors | learning | experts | events ...
  kind        text NOT NULL DEFAULT 'organisation',      -- organisation | individual
  status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','closed')),
  gstin       text,
  billing     jsonb NOT NULL DEFAULT '{}',
  settings    jsonb NOT NULL DEFAULT '{}',
  founding_partner boolean NOT NULL DEFAULT false,
  founding_partner_since date,
  renewal_waived_until date,
  exclusive_category text,
  created_by  bigint REFERENCES users(id),
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE org_members (
  org_id   bigint NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  user_id  bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role     text NOT NULL DEFAULT 'owner' CHECK (role IN ('owner','admin','editor','viewer')),
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, user_id)
);

CREATE TABLE org_invites (
  id bigserial PRIMARY KEY, org_id bigint NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  email citext NOT NULL, role text NOT NULL DEFAULT 'editor', token text UNIQUE NOT NULL,
  invited_by bigint REFERENCES users(id), accepted_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  sid text PRIMARY KEY, data jsonb NOT NULL, user_id bigint, expires_at timestamptz NOT NULL
);
CREATE INDEX ON sessions (expires_at);

CREATE TABLE tokens (                                    -- email verification, password reset, OTP
  id bigserial PRIMARY KEY, purpose text NOT NULL, target text NOT NULL, token_hash text NOT NULL,
  user_id bigint REFERENCES users(id) ON DELETE CASCADE, data jsonb NOT NULL DEFAULT '{}',
  attempts int NOT NULL DEFAULT 0, expires_at timestamptz NOT NULL, used_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON tokens (purpose, target);

-- ============ Forms, registrations, listings ============
CREATE TABLE categories (
  slug        text PRIMARY KEY,                          -- = form slug
  grp         text NOT NULL,                             -- schools | vendors | learning | experts | teachers | ambassadors | events
  label       text NOT NULL,
  description text,
  entity      text NOT NULL,                             -- organisation | individual | minor
  parent_access text NOT NULL DEFAULT 'browse' CHECK (parent_access IN ('browse','ask','none')),
  school_access text NOT NULL DEFAULT 'browse' CHECK (school_access IN ('browse','ask','detailed_free','none')),
  listed      boolean NOT NULL DEFAULT true,             -- appears in public directory
  sort        int NOT NULL DEFAULT 100,
  icon        text
);

CREATE TABLE form_definitions (
  slug        text PRIMARY KEY REFERENCES categories(slug) ON UPDATE CASCADE,
  title       text NOT NULL,
  version     int NOT NULL DEFAULT 1,
  provisional boolean NOT NULL DEFAULT false,
  definition  jsonb NOT NULL,
  active      boolean NOT NULL DEFAULT true,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE registrations (
  id           bigserial PRIMARY KEY,
  form_slug    text NOT NULL REFERENCES form_definitions(slug),
  form_version int NOT NULL DEFAULT 1,
  user_id      bigint REFERENCES users(id) ON DELETE SET NULL,
  org_id       bigint REFERENCES organisations(id) ON DELETE CASCADE,
  status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','submitted','payment_pending','under_review','changes_requested','verified','rejected','suspended','withdrawn')),
  answers      jsonb NOT NULL DEFAULT '{}',              -- public + detailed answers
  private_enc  text,                                     -- AES-256-GCM encrypted JSON of private answers (DPDP safeguard)
  files        jsonb NOT NULL DEFAULT '{}',              -- key -> [{url, name, private}]
  progress     int NOT NULL DEFAULT 0,
  submitted_at timestamptz, verified_at timestamptz, verified_by bigint REFERENCES users(id),
  review_notes text,
  checks       jsonb NOT NULL DEFAULT '{}',              -- internal verification checklist
  internal_tags text[] NOT NULL DEFAULT '{}',
  engagement_status text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON registrations (form_slug, status);
CREATE INDEX ON registrations (org_id);
CREATE INDEX ON registrations (user_id);

CREATE TABLE listings (
  id             bigserial PRIMARY KEY,
  registration_id bigint UNIQUE REFERENCES registrations(id) ON DELETE CASCADE,
  org_id         bigint REFERENCES organisations(id) ON DELETE CASCADE,
  user_id        bigint REFERENCES users(id) ON DELETE CASCADE,  -- for individual listings
  category       text NOT NULL REFERENCES categories(slug),
  slug           text UNIQUE NOT NULL,
  name           text NOT NULL,
  headline       text,
  about          text,
  logo_url       text,
  city           text, district text, state text, pincode text, locality text,
  boards         text[] NOT NULL DEFAULT '{}',
  tags           text[] NOT NULL DEFAULT '{}',
  public_data    jsonb NOT NULL DEFAULT '{}',
  detailed_data  jsonb NOT NULL DEFAULT '{}',
  tier           text NOT NULL DEFAULT 'basic' CHECK (tier IN ('basic','detailed','featured')),
  tier_until     date,
  featured_until date,
  is_published   boolean NOT NULL DEFAULT false,
  verified       boolean NOT NULL DEFAULT false,
  in_house_panel boolean NOT NULL DEFAULT false,           -- experts: in-house vs referral
  rating_avg     numeric(3,2) NOT NULL DEFAULT 0,
  rating_count   int NOT NULL DEFAULT 0,
  view_count     int NOT NULL DEFAULT 0,
  parent_listing_id bigint REFERENCES listings(id),        -- additional campuses
  search         tsvector,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON listings (category, is_published);
CREATE INDEX ON listings (lower(city));
CREATE INDEX ON listings USING gin (search);
CREATE INDEX ON listings USING gin (name gin_trgm_ops);

CREATE TABLE listing_media (
  id bigserial PRIMARY KEY, listing_id bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('photo','video','document')), url text NOT NULL, caption text,
  sort int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now()
);

-- ============ Plans, subscriptions, payments ============
CREATE TABLE plans (
  code        text PRIMARY KEY,
  audience    text NOT NULL,                             -- school | vendor | provider | expert | teacher | parent | any
  stream      text NOT NULL,                             -- revenue stream key (see docs)
  name        text NOT NULL,
  description text,
  price_paise bigint NOT NULL,
  gst_rate    numeric(4,2) NOT NULL DEFAULT 18,
  interval    text NOT NULL CHECK (interval IN ('one_time','monthly','annual')),
  grants      jsonb NOT NULL DEFAULT '{}',               -- e.g. {"tier":"detailed","unlocks":10,"featured":true}
  features    jsonb NOT NULL DEFAULT '[]',
  active      boolean NOT NULL DEFAULT true,
  sort        int NOT NULL DEFAULT 100
);

CREATE TABLE subscriptions (
  id bigserial PRIMARY KEY,
  org_id bigint REFERENCES organisations(id) ON DELETE CASCADE,
  user_id bigint REFERENCES users(id) ON DELETE CASCADE,
  listing_id bigint REFERENCES listings(id) ON DELETE SET NULL,
  plan_code text NOT NULL REFERENCES plans(code),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','expired','cancelled')),
  starts_at date NOT NULL DEFAULT current_date, ends_at date,
  order_id bigint, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON subscriptions (org_id); CREATE INDEX ON subscriptions (user_id);

CREATE TABLE orders (
  id            bigserial PRIMARY KEY,
  public_id     uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
  user_id       bigint REFERENCES users(id) ON DELETE SET NULL,
  org_id        bigint REFERENCES organisations(id) ON DELETE SET NULL,
  kind          text NOT NULL,                           -- plan | unlock_pack | personal_assistance | event_pass | marketplace | expert | storytelling | meetup | newsletter | ...
  description   text NOT NULL,
  subtotal_paise bigint NOT NULL, gst_paise bigint NOT NULL DEFAULT 0, shipping_paise bigint NOT NULL DEFAULT 0,
  total_paise   bigint NOT NULL,
  currency      text NOT NULL DEFAULT 'INR',
  status        text NOT NULL DEFAULT 'created' CHECK (status IN ('created','paid','failed','cancelled','refunded','fulfilled','shipped','delivered')),
  gateway       text, gateway_order_id text, gateway_payment_id text,
  meta          jsonb NOT NULL DEFAULT '{}',
  address       jsonb,
  invoice_no    text UNIQUE,
  referral_code text,
  paid_at       timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON orders (user_id); CREATE INDEX ON orders (org_id); CREATE INDEX ON orders (kind, status);

CREATE TABLE order_items (
  id bigserial PRIMARY KEY, order_id bigint NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  product_id bigint, title text NOT NULL, qty int NOT NULL DEFAULT 1, unit_paise bigint NOT NULL,
  seller_org_id bigint REFERENCES organisations(id)
);

CREATE TABLE payment_events (
  id bigserial PRIMARY KEY, gateway text NOT NULL, event text, gateway_order_id text, raw jsonb NOT NULL,
  verified boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);

CREATE SEQUENCE invoice_seq START 1001;

-- ============ Parent unlocks, leads, reviews ============
CREATE TABLE unlock_packs (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  order_id bigint REFERENCES orders(id), category_group text NOT NULL DEFAULT 'schools',
  city text NOT NULL, locality text, quota int NOT NULL, used int NOT NULL DEFAULT 0,
  expires_at timestamptz NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE unlocks (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  listing_id bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE, pack_id bigint REFERENCES unlock_packs(id),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (user_id, listing_id)
);

CREATE TABLE leads (
  id bigserial PRIMARY KEY,
  listing_id bigint REFERENCES listings(id) ON DELETE CASCADE,
  org_id bigint REFERENCES organisations(id) ON DELETE CASCADE,
  source text NOT NULL,                                   -- unlock_contact | enquiry | personal_assistance | ask_expert | event | marketplace
  user_id bigint REFERENCES users(id) ON DELETE SET NULL,
  name text, email text, phone text, message text,
  verified boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','contacted','follow_up','converted','closed','lost')),
  notes text, consent_id bigint,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON leads (org_id, status);

CREATE TABLE reviews (
  id bigserial PRIMARY KEY, listing_id bigint NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
  user_id bigint REFERENCES users(id) ON DELETE SET NULL, rating int NOT NULL CHECK (rating BETWEEN 1 AND 5),
  title text, body text, verified boolean NOT NULL DEFAULT false,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','published','rejected')),
  response text, created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (listing_id, user_id)
);

-- ============ Ask The School Expert & Personal Assistance ============
CREATE TABLE expert_requests (
  id bigserial PRIMARY KEY, user_id bigint REFERENCES users(id) ON DELETE SET NULL, org_id bigint REFERENCES organisations(id),
  requester_type text NOT NULL, topic text NOT NULL, category text, message text NOT NULL,
  preferred_mode text, city text, status text NOT NULL DEFAULT 'new' CHECK (status IN ('new','in_review','quoted','paid','matched','completed','closed')),
  panel text CHECK (panel IN ('in_house','referral')), matched_listing_id bigint REFERENCES listings(id),
  quote_paise bigint, order_id bigint REFERENCES orders(id), staff_notes text,
  child_info_consent boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pa_cities (city text PRIMARY KEY, state text, active boolean NOT NULL DEFAULT true, base_paise bigint NOT NULL DEFAULT 0, per_km_paise bigint NOT NULL DEFAULT 0);
CREATE TABLE pa_services (
  code text PRIMARY KEY, name text NOT NULL, description text, price_paise bigint NOT NULL, sort int NOT NULL DEFAULT 100, active boolean NOT NULL DEFAULT true
);
CREATE TABLE pa_requests (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  listing_id bigint REFERENCES listings(id), school_name text, city text NOT NULL, distance_km numeric(6,1),
  services text[] NOT NULL, postal_address jsonb, notes text,
  status text NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','quoted','paid','in_progress','completed','cancelled')),
  quote_paise bigint, order_id bigint REFERENCES orders(id), assigned_to bigint REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE pa_updates (
  id bigserial PRIMARY KEY, request_id bigint NOT NULL REFERENCES pa_requests(id) ON DELETE CASCADE,
  stage text NOT NULL, note text, attachment_url text, created_by bigint REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ============ Teachers, CVs, jobs ============
CREATE TABLE teacher_profiles (
  user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  registration_id bigint REFERENCES registrations(id) ON DELETE SET NULL,
  slug text UNIQUE, headline text, visibility text NOT NULL DEFAULT 'schools',  -- public | schools | hidden
  open_to_work boolean NOT NULL DEFAULT true,
  cv_json jsonb, cv_generated_at timestamptz, cv_file_url text, uploaded_cv_url text,
  membership_until date, updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE jobs (
  id bigserial PRIMARY KEY, org_id bigint NOT NULL REFERENCES organisations(id) ON DELETE CASCADE,
  listing_id bigint REFERENCES listings(id) ON DELETE SET NULL,
  slug text UNIQUE NOT NULL, title text NOT NULL, role text, subjects text[] NOT NULL DEFAULT '{}', grades text[] NOT NULL DEFAULT '{}',
  board text, employment_type text, experience text, qualifications text,
  city text, state text, salary_min int, salary_max int, show_salary boolean NOT NULL DEFAULT false,
  description text NOT NULL, status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','closed')),
  featured_until date, published_at timestamptz, closes_on date, created_by bigint REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON jobs (status, published_at DESC);

CREATE TABLE job_applications (
  id bigserial PRIMARY KEY, job_id bigint NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  teacher_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  cv_url text, cv_snapshot jsonb, cover_letter text,
  status text NOT NULL DEFAULT 'applied' CHECK (status IN ('applied','viewed','shortlisted','interview','offered','hired','rejected','withdrawn')),
  share_consent_id bigint, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (job_id, teacher_id)
);

-- ============ Safe communities ============
CREATE TABLE communities (
  slug text PRIMARY KEY, name text NOT NULL, description text,
  view_roles text[] NOT NULL, post_roles text[] NOT NULL,
  premoderate boolean NOT NULL DEFAULT false, allow_comments boolean NOT NULL DEFAULT true, sort int NOT NULL DEFAULT 100
);
CREATE TABLE posts (
  id bigserial PRIMARY KEY, community text NOT NULL REFERENCES communities(slug), user_id bigint REFERENCES users(id) ON DELETE SET NULL,
  title text NOT NULL, body text NOT NULL, kind text NOT NULL DEFAULT 'discussion',  -- discussion | resource | question | showcase
  attachment_url text, status text NOT NULL DEFAULT 'published' CHECK (status IN ('pending','published','hidden','removed')),
  moderation_reason text, pinned boolean NOT NULL DEFAULT false, comment_count int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON posts (community, status, created_at DESC);
CREATE TABLE comments (
  id bigserial PRIMARY KEY, post_id bigint NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  user_id bigint REFERENCES users(id) ON DELETE SET NULL, body text NOT NULL,
  status text NOT NULL DEFAULT 'published' CHECK (status IN ('pending','published','hidden','removed')),
  moderation_reason text, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE content_reports (
  id bigserial PRIMARY KEY, target_type text NOT NULL, target_id bigint NOT NULL, reporter_id bigint REFERENCES users(id) ON DELETE SET NULL,
  reason text NOT NULL, details text, status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','actioned','dismissed')),
  resolved_by bigint REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE community_bans (user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE, reason text, until timestamptz, created_at timestamptz NOT NULL DEFAULT now());

-- Parents' Corner (submissions only; no discussion)
CREATE TABLE corner_submissions (
  id bigserial PRIMARY KEY, user_id bigint REFERENCES users(id) ON DELETE SET NULL,
  kind text NOT NULL CHECK (kind IN ('craft_project','model_tutorial','activity_idea')),
  title text NOT NULL, grade text, materials text, steps text NOT NULL, media_url text,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','published','rejected')),
  created_at timestamptz NOT NULL DEFAULT now()
);

-- ============ Events, podcasts, gallery, newsletters, resources ============
CREATE TABLE events (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL, title text NOT NULL, kind text NOT NULL,
  -- conference | roundtable | workshop | webinar | meetup | homeschool_meetup | storytelling | bookclub | expo
  summary text, body text, audience text[] NOT NULL DEFAULT '{}', mode text NOT NULL DEFAULT 'online',
  venue text, city text, starts_at timestamptz NOT NULL, ends_at timestamptz,
  price_paise bigint NOT NULL DEFAULT 0, member_price_paise bigint, capacity int,
  form_slug text REFERENCES form_definitions(slug), cover_url text,
  status text NOT NULL DEFAULT 'published' CHECK (status IN ('draft','published','cancelled','completed')),
  passes_require_approval boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE event_registrations (
  id bigserial PRIMARY KEY, event_id bigint NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  user_id bigint REFERENCES users(id) ON DELETE SET NULL, org_id bigint REFERENCES organisations(id),
  attendees int NOT NULL DEFAULT 1, answers jsonb NOT NULL DEFAULT '{}', order_id bigint REFERENCES orders(id),
  status text NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','confirmed','waitlisted','cancelled','attended')),
  pass_code text UNIQUE, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE sponsorships (
  id bigserial PRIMARY KEY, event_id bigint REFERENCES events(id) ON DELETE CASCADE, podcast_id bigint,
  org_id bigint REFERENCES organisations(id), sponsor_name text NOT NULL, tier text NOT NULL, logo_url text, url text,
  amount_paise bigint, status text NOT NULL DEFAULT 'enquiry' CHECK (status IN ('enquiry','confirmed','cancelled')),
  contact_email text, message text, created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE podcasts (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL, kind text NOT NULL DEFAULT 'podcast' CHECK (kind IN ('podcast','webinar')),
  title text NOT NULL, guest text, guest_title text, summary text, body text, media_url text, cover_url text,
  audience text[] NOT NULL DEFAULT '{}', tags text[] NOT NULL DEFAULT '{}', duration_min int,
  published_at timestamptz, status text NOT NULL DEFAULT 'published', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE podcast_questions (
  id bigserial PRIMARY KEY, podcast_id bigint NOT NULL REFERENCES podcasts(id) ON DELETE CASCADE,
  user_id bigint REFERENCES users(id) ON DELETE SET NULL, question text NOT NULL, answer text,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','answered','published','rejected')),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE gallery_albums (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL, title text NOT NULL, description text,
  event_id bigint REFERENCES events(id) ON DELETE SET NULL, cover_url text, taken_on date,
  published boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE gallery_photos (
  id bigserial PRIMARY KEY, album_id bigint NOT NULL REFERENCES gallery_albums(id) ON DELETE CASCADE,
  url text NOT NULL, thumb_url text, caption text, consent_confirmed boolean NOT NULL DEFAULT false,
  sort int NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE newsletters (
  id bigserial PRIMARY KEY, kind text NOT NULL CHECK (kind IN ('industry','newsworms')),
  slug text UNIQUE NOT NULL, title text NOT NULL, issue_no int, summary text, body text, pdf_url text, cover_url text,
  age_band text, access text NOT NULL DEFAULT 'free' CHECK (access IN ('free','subscriber')),
  published_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE newsletter_subscriptions (
  id bigserial PRIMARY KEY, kind text NOT NULL, email citext NOT NULL, user_id bigint REFERENCES users(id) ON DELETE CASCADE,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','unsubscribed')),
  paid_until date, confirm_token text, consent_id bigint, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (kind, email)
);

CREATE TABLE resources (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL,
  kind text NOT NULL CHECK (kind IN ('worksheet','kids_newspaper','homeschool','learning_app','teacher_resource','guide')),
  title text NOT NULL, summary text, grade text, subject text, file_url text, external_url text,
  platform text, price_paise bigint NOT NULL DEFAULT 0, is_free boolean NOT NULL DEFAULT true,
  downloads int NOT NULL DEFAULT 0, published boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now()
);

-- Book club
CREATE TABLE books (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL, title text NOT NULL, author text, age_band text, language text,
  cover_url text, summary text, rating_avg numeric(3,2) NOT NULL DEFAULT 0, rating_count int NOT NULL DEFAULT 0,
  marketplace_product_id bigint, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE book_reviews (
  id bigserial PRIMARY KEY, book_id bigint NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  user_id bigint REFERENCES users(id) ON DELETE SET NULL, rating int NOT NULL CHECK (rating BETWEEN 1 AND 5),
  body text, status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','published','rejected')),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (book_id, user_id)
);
CREATE TABLE club_memberships (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE, club text NOT NULL,
  age_band text, status text NOT NULL DEFAULT 'active', created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (user_id, club)
);

-- Initiatives & CMS
CREATE TABLE initiatives (
  id bigserial PRIMARY KEY, slug text UNIQUE NOT NULL, title text NOT NULL, tagline text, summary text, body text,
  cta_label text, cta_url text, icon text, sort int NOT NULL DEFAULT 100, published boolean NOT NULL DEFAULT true
);
CREATE TABLE pages (slug text PRIMARY KEY, title text NOT NULL, body text NOT NULL, meta_description text, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE faqs (id bigserial PRIMARY KEY, section text NOT NULL, question text NOT NULL, answer text NOT NULL, sort int NOT NULL DEFAULT 100);
CREATE TABLE settings (key text PRIMARY KEY, value jsonb NOT NULL);

-- ============ Marketplace ============
CREATE TABLE products (
  id bigserial PRIMARY KEY, seller_org_id bigint REFERENCES organisations(id) ON DELETE CASCADE,  -- NULL = The School Expert
  slug text UNIQUE NOT NULL, title text NOT NULL, category text NOT NULL, brand text,
  summary text, description text, price_paise bigint NOT NULL, mrp_paise bigint, gst_rate numeric(4,2) NOT NULL DEFAULT 12,
  stock int NOT NULL DEFAULT 0, images text[] NOT NULL DEFAULT '{}', grade text, bulk_tiers jsonb NOT NULL DEFAULT '[]',
  is_tse boolean NOT NULL DEFAULT false, is_digital boolean NOT NULL DEFAULT false, digital_url text,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('draft','pending','published','rejected','archived')),
  rating_avg numeric(3,2) NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON products (category, status);
CREATE TABLE cart_items (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id bigint NOT NULL REFERENCES products(id) ON DELETE CASCADE, qty int NOT NULL CHECK (qty > 0),
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (user_id, product_id)
);
CREATE TABLE addresses (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE, org_id bigint REFERENCES organisations(id),
  label text, name text NOT NULL, phone text NOT NULL, line1 text NOT NULL, line2 text, city text NOT NULL, state text NOT NULL,
  pincode text NOT NULL, is_default boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE shipments (
  id bigserial PRIMARY KEY, order_id bigint NOT NULL REFERENCES orders(id) ON DELETE CASCADE, seller_org_id bigint,
  courier text, tracking_no text, status text NOT NULL DEFAULT 'pending', updated_at timestamptz NOT NULL DEFAULT now()
);

-- ============ Referrals / affiliates, ads ============
CREATE TABLE referral_codes (
  code text PRIMARY KEY, user_id bigint REFERENCES users(id) ON DELETE CASCADE, org_id bigint REFERENCES organisations(id),
  kind text NOT NULL DEFAULT 'ambassador', commission_pct numeric(5,2) NOT NULL DEFAULT 10, active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE referrals (
  id bigserial PRIMARY KEY, code text NOT NULL REFERENCES referral_codes(code), referred_user_id bigint REFERENCES users(id) ON DELETE SET NULL,
  referred_org_id bigint REFERENCES organisations(id), order_id bigint REFERENCES orders(id), commission_paise bigint NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','paid','rejected')), created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ad_placements (
  id bigserial PRIMARY KEY, placement text NOT NULL, org_id bigint REFERENCES organisations(id), title text NOT NULL,
  image_url text, link_url text NOT NULL, starts_on date NOT NULL, ends_on date NOT NULL, impressions int NOT NULL DEFAULT 0,
  clicks int NOT NULL DEFAULT 0, active boolean NOT NULL DEFAULT true
);

-- ============ Support, notifications, CRM ============
CREATE TABLE support_tickets (
  id bigserial PRIMARY KEY, org_id bigint REFERENCES organisations(id) ON DELETE CASCADE, user_id bigint REFERENCES users(id) ON DELETE SET NULL,
  subject text NOT NULL, status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','pending','resolved','closed')),
  priority text NOT NULL DEFAULT 'normal', assigned_to bigint REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE ticket_messages (
  id bigserial PRIMARY KEY, ticket_id bigint NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
  user_id bigint REFERENCES users(id) ON DELETE SET NULL, body text NOT NULL, staff boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE contact_messages (
  id bigserial PRIMARY KEY, name text NOT NULL, email citext NOT NULL, phone text, topic text, message text NOT NULL,
  status text NOT NULL DEFAULT 'new', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE notifications (
  id bigserial PRIMARY KEY, user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE, title text NOT NULL,
  body text, link text, read_at timestamptz, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON notifications (user_id, read_at);
CREATE TABLE outbox (                                    -- CRM / webhook / email delivery queue (at-least-once)
  id bigserial PRIMARY KEY, channel text NOT NULL, event text NOT NULL, payload jsonb NOT NULL,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed','skipped')),
  attempts int NOT NULL DEFAULT 0, last_error text, next_attempt_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now(), sent_at timestamptz
);
CREATE INDEX ON outbox (status, next_attempt_at);

-- ============ DPDP: consent, rights, audit, breaches ============
CREATE TABLE consent_notices (
  id bigserial PRIMARY KEY, purpose text NOT NULL, version int NOT NULL, lang text NOT NULL DEFAULT 'en',
  title text NOT NULL, body text NOT NULL, data_items text, retention text, active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(), UNIQUE (purpose, version, lang)
);
CREATE TABLE consents (
  id bigserial PRIMARY KEY, user_id bigint REFERENCES users(id) ON DELETE SET NULL, email citext,
  purpose text NOT NULL, notice_version int NOT NULL, granted boolean NOT NULL,
  method text NOT NULL,                                   -- checkbox | otp_guardian | cookie_banner | dashboard
  context text, ip inet, user_agent text, guardian jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), withdrawn_at timestamptz
);
CREATE INDEX ON consents (user_id, purpose);
CREATE TABLE data_requests (
  id bigserial PRIMARY KEY, user_id bigint REFERENCES users(id) ON DELETE SET NULL, email citext NOT NULL,
  kind text NOT NULL CHECK (kind IN ('access','correction','erasure','withdraw_consent','nomination','grievance')),
  details text, status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','completed','rejected')),
  response text, due_at timestamptz NOT NULL, closed_at timestamptz, handled_by bigint REFERENCES users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE audit_log (
  id bigserial PRIMARY KEY, actor_id bigint, actor_type text, action text NOT NULL, entity text, entity_id text,
  org_id bigint, ip inet, meta jsonb NOT NULL DEFAULT '{}', created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_log (created_at); CREATE INDEX ON audit_log (entity, entity_id);
CREATE TABLE breach_incidents (
  id bigserial PRIMARY KEY, detected_at timestamptz NOT NULL, summary text NOT NULL, data_categories text, affected_count int,
  likely_impact text, mitigation text, board_intimated_at timestamptz, board_report_at timestamptz, principals_notified_at timestamptz,
  status text NOT NULL DEFAULT 'open', created_by bigint REFERENCES users(id), created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
