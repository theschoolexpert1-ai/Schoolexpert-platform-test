# Teachers Hub (formerly TeachersInn)

TeachersInn is no longer a separate Node.js app. Everything it did now lives inside The School Expert™ as the **Teachers Hub**, so a teacher has
**one account, one login and one dashboard** for learning, networking, planning and their career. Schools, parents and vendors are unaffected.

## What a teacher gets

| TeachersInn screen | Where it lives now | Notes |
|---|---|---|
| Dashboard (CPD ring, stats, continue learning, weekly activity, upcoming workshops, plans, community feed) | `/dashboard/` (teacher accounts) | Career widgets (profile, AI CV, applications, jobs) on the same page |
| Upskilling: courses, lessons, progress, certificates | `/teachers/learn`, `/teachers/certificates` | First lesson is a free preview; certificate on completing every lesson |
| Public certificate verification | `/teachers/certificates/verify?code=…` | Shows name, course, hours and date only |
| Workshops (register, cancel, .ics, CPD hours) | `/teachers/workshops` → standard event pages | Workshops are ordinary **events** (kind workshop/webinar, audience `teachers`) with new `cpd_hours`, `facilitator`, `category` fields, so payments, passes, forms and the Events Desk all apply. Attended (or confirmed and finished) workshops count towards CPD |
| Educator directory, connection requests | `/teachers/network`, `/teachers/network/connections` | **Opt-in**: teachers are hidden until they switch the directory on (recorded as a `hub_directory` consent) |
| Private messaging | `/teachers/messages` | Only between accepted connections or active mentor pairs; bodies AES-256-GCM encrypted at rest; 60 messages/hour limit |
| 8 subject / role communities | `/teachers/communities` → `/community/<slug>` | Uses the existing moderated community engine (personal-data and abuse checks, reporting, moderation desk). Teacher-only visibility |
| Helpdesk tickets | `/dashboard/support` | The platform's existing support desk |
| Mentorship | `/teachers/mentors` | Teachers offer to mentor from Hub profile; staff approve in the Teachers Hub Desk |
| Tutorials library, save for later | `/teachers/tutorials` | 16 guides |
| Lesson planner (private, printable) | `/teachers/planner` | Row-level security: only the owner can read it |
| Careers board | `/jobs` | Real jobs posted by verified schools (replaces TeachersInn's admin-typed jobs) |
| Profile & privacy, export, deletion, sessions, password | `/teachers/hub/profile`, Privacy Centre, Account security | DPDP export now includes all Hub data (messages decrypted for the owner); erasure deletes it |
| Admin console | `/admin/teachers-hub` + Content Studio (`courses`, `course_lessons`, `tutorials`) + Events Desk | Staff never see message contents |

## Security (same layers as the rest of the platform)
- Teachers-only access (`hub_required`); parents/schools see a friendly gate page.
- PostgreSQL **row-level security** (FORCE) on `course_enrolments`, `lesson_progress`, `tutorial_saves`, `lesson_plans`, `connections`, `direct_messages`, `mentorships`.
- CSRF on every form, rate limits on enrol / connect / mentorship requests / messages, length limits on every field.
- Directory never exposes email or phone; strangers cannot open or send message threads.
- Audit log entries for course completion, profile/privacy changes, connection removal and mentor decisions.
- No student or child data is collected; plans, messages and mentorship requests remind teachers not to enter students' details.

## Data model (migration `006_teachers_hub.sql`)
`hub_members`, `courses`, `course_lessons`, `course_enrolments`, `lesson_progress`, `tutorials`, `tutorial_saves`, `lesson_plans`, `connections`,
`direct_messages`, `mentorships`; `events.cpd_hours / facilitator / category`.

Starter content (courses, lessons, tutorials, communities) is loaded by `flask --app wsgi seed` from `tse/db/content/teachers_hub.json` and never overwrites
edits made in the admin. `seed --demo` also adds 8 demo educators (5 approved mentors), 6 CPD workshops and sample discussions.

## Moving existing TeachersInn users
If TeachersInn ever had real users, export its SQLite tables and import them into these tables; teachers sign in with their School Expert account
(ask them to reset their password, because TeachersInn password hashes use a different scheme).
