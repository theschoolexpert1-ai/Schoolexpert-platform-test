# The School Expert™ — integrated K-12 education ecosystem platform

A complete website, back office and database for **www.schoolexpert.in**, connecting parents, schools, teachers, experts and education partners across India.

- **Stack:** Python 3.11+ / Flask, server-rendered pages (fast, SEO-friendly), PostgreSQL 13+. No compiled dependencies; the PostgreSQL client is bundled (`tse/db/pgwire.py`).
- **Hosting:** GoDaddy VPS (Ubuntu) with nginx + gunicorn + PostgreSQL → see `docs/DEPLOYMENT-GODADDY.md`. Docker-ready for AWS/Azure/GCP → `docs/CLOUD-MIGRATION.md`.
- **Compliance:** built for the DPDP Act 2023 and DPDP Rules 2025 → `docs/DPDP-COMPLIANCE.md`.

## Quick start (development)

```bash
python3 -m venv venv && . venv/bin/activate && pip install -r requirements.txt
createdb schoolexpert            # PostgreSQL 13+; DATABASE_URL defaults to postgresql://tse:tse_dev_pw@127.0.0.1:5432/schoolexpert
export FLASK_APP=wsgi
flask migrate                    # create tables
flask seed --demo                # categories, 29 forms, plans, pages, FAQs + demo content
flask run --port 8000            # http://localhost:8000
```

Demo logins (password `DemoPass#2026`): `admin@demo.schoolexpert.in`, `support@demo.schoolexpert.in` (support desk only), `parent@demo.schoolexpert.in`, `teacher@demo.schoolexpert.in`; schools: `school2@…` **School - Pro**, `school1@…` **School - Plus**, `school4@…` **School - Basic**, `school7@…` **not yet paid**, `school0@…` Founding Partner; vendors: `partner1@…` **Vendor - Pro**, `partner0@…` **Vendor - Plus**, `partner2@…` **Vendor - Basic**. **Never run `seed --demo` in production** — use `flask seed` and `flask create-admin you@schoolexpert.in "Your Name"`.

Payments run in **test mode** (`PAYMENT_GATEWAY=mock`) until Razorpay keys are set.

## New in v4 — Teachers Hub (TeachersInn merged in) and team prototype hosting
| Area | Where | Docs |
|---|---|---|
| **Teachers Hub** — the former TeachersInn app, now inside The School Expert with the same login, database and security: 8 CPD courses (33 lessons) with verifiable certificates, workshops with CPD hours and calendar files, educator network with encrypted private messages, 9 teacher communities, mentorship (staff-approved mentors), 16 tutorials, private lesson planner, wellbeing, Hub profile & privacy | `/teachers`, teacher `/dashboard/` | `docs/TEACHERS-HUB.md` |
| Teachers Hub Desk for staff (mentor approvals, courses, tutorials, Hub metrics) | `/admin/teachers-hub` | `docs/ADMIN-DESKS.md` |
| Vercel + Neon hosting for the team prototype (staging mode, team password, files in the database, scheduled jobs) | `vercel.json`, `api/index.py` | `docs/DEPLOY-VERCEL.md` |

## New in v2 — integrated, pay-for-visibility platform
| Area | Where | Docs |
|---|---|---|
| School - Basic / Plus / Pro and Vendor - Basic / Plus / Pro, one-step upgrades with credit, renewals, add-ons; payment decides listing visibility, leads, featured placement, limits and commission | `/pricing`, Dashboard → Plan & upgrade | `docs/PLANS-AND-REVENUE.md` |
| Paid dashboards for every school & vendor (analytics, usage, upgrade prompts), free dashboard for every teacher and parent | `/dashboard` | |
| AI School Match — neutral ranked shortlist, reasons, unlock-to-see details, shortlist & compare, Claude advisor | `/school-match` | `docs/AI-SCHOOL-MATCH.md` |
| 13 admin team desks with role-based access | `/admin` | `docs/ADMIN-DESKS.md` |
| SEO/SEM: audience & city landing pages, guides, sitemap index, UTM attribution, consented conversion tracking, UTM builder | `/list-your-school`, `/become-a-vendor`, `/schools/<city>`, `/guides` | `docs/SEO-SEM.md` |
| Existing-site integration: legacy paths, 301 map, embeddable widgets | Site Integration Desk, `/widget.js` | `docs/GO-LIVE-ON-SCHOOLEXPERT-IN.md` |
| Mobile: installable PWA + bottom navigation, REST API v1, Capacitor Android/iOS project | `/manifest.webmanifest`, `/api/v1`, `mobile/` | `docs/API.md`, `mobile/README.md` |
| Referral / affiliate programme, sponsored banners, seller ledger & payouts | Dashboard → Refer & earn / Sponsored banners | |

| Security at every layer — database row-level security, encryption at rest with key rotation, two-step verification (mandatory for staff), lockout, step-up re-authentication, nonce-based CSP, safe uploads, tamper-evident audit log, hardened server/nginx/systemd/backups | Account security page, Admin → Security monitoring | `docs/SECURITY.md` |
| Registration forms re-audited line-by-line against your 19 uploaded documents and corrected (Course Providers rebuilt from your specification, incl. one provider → many courses) | `/register` | `forms_src/AUDIT.md` |

Tests: `python tests/e2e.py` (end-to-end journeys incl. upgrades, AI Match, desks, API, SEO), `python tests/security.py` (71 security checks across every layer and the document-fidelity fixes) and `python tests/smoke.py` (crawls every page per role).

## What's inside

| Area | Where |
|---|---|
| Registration Centre — 29 forms (all 26 from registration.schoolexpert.in + roundtables + fee financing), save-and-continue, review, consent, plan & payment | `/register`, `tse/routes/register.py`, `tse/forms/*.json` |
| Directory: schools, tutors/classes, experts, vendors — free basic profile, paid detailed profile, filters, verified badge, ratings | `/directory/*`, `/c/<category>`, `/l/<listing>` |
| Ask The School Expert — locality packs unlocking 10 detailed school profiles, verified leads, verified reviews; expert requests (in-house panel / referral, quoted & paid) | `/ask`, `/ask/schools` |
| Personal Assistance — our own staff, selected cities, service menu, location-based fee, step-by-step tracking | `/personal-assistance` |
| Teachers — profile, AI CV builder (PDF), jobs board, apply from school pages, Teacher Premium | `/teachers`, `/jobs` |
| Safe communities (teachers, parents, homeschoolers, principals, special-education) + Parents' Corner (submissions only) | `/community`, `/parents-corner` |
| Marketplace — TSE products + vendor products, cart, address & phone, bulk pricing for schools, seller dispatch | `/marketplace` |
| Events & passes (roundtables with their forms, conferences, workshops, webinars, homeschool meetups, storytelling), sponsorships | `/events` |
| Podcasts & webinars with listener questions, Photo Gallery, Industry Newsletter, NewsWorms, The EverHungry Bookworms Bookclub, Homeschoolers Hub, worksheets | `/podcasts`, `/gallery`, `/newsletter`, `/newsworms`, `/bookclub`, `/homeschoolers-hub`, `/resources` |
| The School Expert Initiatives page | `/initiatives` |
| FAQs (verbatim), Privacy Policy (verbatim from your document), Terms, Refund, Shipping, Cookies, Disclaimer, Community Guidelines, Contact | `/faq`, `/privacy-policy`, … |
| Dashboards — parent, teacher, organisation (multi-tenant: team members, campuses, leads, reviews, jobs, products, sales, plans, support) | `/dashboard` |
| Back office — verification checklist, listings, tenants, users, orders/refunds, revenue by stream, CRM-lite leads, expert desk, PA desk, moderation, CMS, form manager, DPDP requests, breach register, audit log, outbox | `/admin` |
| Privacy Centre — consents, data export, correction, erasure, nomination, grievance | `/privacy-centre` |

## Operations

| Command | When |
|---|---|
| `flask migrate` | after every deploy |
| `flask seed` | first deploy / to add new built-in content (idempotent) |
| `flask outbox-worker --loop` | always running (systemd) — delivers CRM events & emails with retries |
| `flask housekeeping` | daily (cron) — DPDP retention, expiries |
| `flask import-form file.json` | when you update a registration form |

## Tests

```bash
python3 tests/e2e.py      # 116 end-to-end checks across every journey (needs a seeded demo DB)
python3 tests/security.py # 71 security checks
python3 tests/hub.py      # 74 Teachers Hub checks (courses, certificates, network, messages, planner, mentors, isolation, DPDP)
python3 tests/smoke.py   # loads every page as guest/parent/teacher/school/partner/admin
```

## Documentation
`docs/TEACHERS-HUB.md` · `docs/DEPLOY-VERCEL.md` · `docs/DEPLOYMENT-GODADDY.md` · `docs/CLOUD-MIGRATION.md` · `docs/INTEGRATIONS.md` · `docs/DPDP-COMPLIANCE.md` · `docs/SEO-SEM.md` · `docs/FORMS.md` · `docs/ARCHITECTURE.md`
