# Architecture

```
Browser ── nginx (TLS, static, /media) ── gunicorn ── Flask app (tse/) ── PostgreSQL
                                                  │                        ├─ outbox ──► worker ──► CRM / SMTP
                                                  └─ storage (local disk │ S3) ├─ cron ──► housekeeping (DPDP retention)
                                                  └─ Razorpay (orders, checkout, webhooks)   └─ Anthropic (AI CV, optional)
```

## Code layout
| Path | Purpose |
|---|---|
| `tse/__init__.py` | app factory, security headers, template helpers, blueprints |
| `tse/db/pgwire.py`, `db.py` | bundled PostgreSQL client (extended protocol, bound parameters, SCRAM) + pool & helpers |
| `tse/db/migrations/*.sql` | schema (≈60 tables) |
| `tse/db/seed.py`, `demo.py`, `content/` | categories, plans, communities, notices, FAQs, policies, initiatives; demo data |
| `tse/forms/*.json` | the 29 registration form definitions |
| `tse/lib/` | `forms` (dynamic form engine), `listings` (sync/search/access rules), `payments`, `crm`, `notify`, `consent`, `moderation`, `cv`, `storage`, `security`, `auth`, `retention`, `html` |
| `tse/routes/` | `public, auth, register, directory, ask, teachers, community, marketplace, events, content, pay, privacy, dashboard, admin` |
| `tse/templates/`, `tse/static/` | Jinja templates, CSS, JS, logo |

## Multi-tenancy
Each school, business or professional practice is an **organisation** (tenant) with members (owner / admin / editor / viewer), invitations and multiple listings (campuses / categories). Every tenant-owned row carries `org_id`; dashboard routes load rows through `tenant_guard()` (404 on mismatch), which the tests verify. Users can belong to several organisations and switch between them.

## Who sees what (stakeholder journeys)
| Viewer | Schools | Tutors/classes/consultants | Experts (mental health, behaviour, special ed., careers, fee financing) | Vendors | Teachers community | Parents community |
|---|---|---|---|---|---|---|
| Guest / parent | basic free; detailed after paid unlock (10 per locality pack) | browse | via **Ask The School Expert** | — | — | parents only |
| School / organisation | browse; detailed with a paid plan | browse | via Ask The School Expert (separate in-house pricing) | browse; detailed with a paid plan; teacher-training institutes detailed free | read (post only as teacher) | hidden |
| Teacher | browse | browse | via Ask | — | read & post | — |

Schools cannot rate schools; only parents who unlocked a school can leave **verified reviews**. After verification, school basic details are locked; photos, videos, Principal name and Contact Person name stay editable.

## Revenue streams → features
| # | Stream (from your diagram) | Implementation |
|---|---|---|
| 1 | School subscription plans | `plans` school_detailed / school_featured; registration → plan → dashboard |
| 2 | Verified school leads | parent unlock packs → verified enquiries in school dashboard + CRM |
| 4 | Featured / sponsored placement | featured tier, featured jobs, `ad_placements`, sponsored newsletter |
| 5 | Education partner memberships | partner / provider / professional plans |
| 6 | Founding Partner Programme | one-time plans, 3-year renewal waiver, badge, exclusivity flag |
| 7 | Teacher memberships | Teacher Premium (unlimited AI CVs, badge, discounts) |
| 8 | Podcasts & webinars | podcast/webinar pages, listener questions, sponsorships, paid webinars |
| 10 | Workshops | events of kind `workshop` with paid passes |
| 10 | Product marketplace | TSE + vendor products, bulk pricing, seller dispatch |
| 11 | Events & sponsorships | events, pass requests (schools), sponsorship enquiries |
| 12 | Recruitment marketplace | free job posts, Recruitment Plus (teacher directory), Featured Job |
| 14 | Affiliate / referral | `referral_codes` / `referrals` (Parent Ambassador commissions) |
| 15 | Product / service subscriptions | NewsWorms, Book Club membership |
| 16 | Homeschoolers meetups | paid `homeschool_meetup` events |
| — | Ask The School Expert & Personal Assistance | quoted expert services; PA service menu with location pricing |

All prices are placeholders, editable in Admin → Content manager → Plans / Personal Assistance services.
