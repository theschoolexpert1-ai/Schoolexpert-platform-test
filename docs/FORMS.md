# Registration forms inventory

Every registration form is stored as JSON in `tse/forms/` and loaded into the `form_definitions` table. One definition drives the multi-step registration form, the public profile page, the paid detailed view and directory filters.

| Category | Form (slug) | Fields | Source |
|---|---|---|---|
| Schools | `school-registration` | 56 | From your uploaded form |
| Alternative Schools | `alternative-school` | 43 | From your uploaded form |
| Inclusive Schools | `inclusive-school` | 58 | From your uploaded form |
| Nursery / Preschools | `preschool` | 69 | From your uploaded form |
| Special Schools | `special-school` | 38 | From your uploaded form |
| Online Schools | `online-school-registration` | 29 | **Provisional** — rebuilt from section 1 of the live form |
| EdTech Companies | `edtech-company` | 24 | From your uploaded form |
| Educational Publishers | `educational-publisher` | 39 | From your uploaded form |
| School Infrastructure Vendors | `infrastructure-vendor` | 30 | **Provisional** — rebuilt from section 1 of the live form |
| Transportation & Logistics | `transport-logistics` | 25 | **Provisional** — rebuilt from section 1 of the live form |
| Uniform, Badge, Bag & Stationery | `uniform-vendor` | 26 | **Provisional** — rebuilt from section 1 of the live form |
| Fee Financing Companies | `fee-financing` | 18 | **Provisional** — rebuilt from section 1 of the live form |
| K-12 Course Providers | `course-provider` | 60 | From your uploaded form |
| Online Tutoring Institutions | `online-tutoring-support-provider-institution-registration` | 67 | From your uploaded form |
| Individual Online Tutors | `individual-online-tutor-registration` | 84 | From your uploaded form |
| Hobby & Enrichment Classes | `recreation-hobbies-enrichment-provider` | 73 | From your uploaded form |
| Skill Development Institutes | `skill-development` | 28 | **Provisional** — rebuilt from section 1 of the live form |
| Teacher Training Institutes | `teacher-training-institute-registration` | 76 | From your uploaded form |
| Education Consultants | `educational-consultant-registration` | 53 | From your uploaded form |
| Behaviour Consultants & Therapists | `behaviour-consultant` | 33 | **Provisional** — rebuilt from section 1 of the live form |
| Career Guidance & Counselling | `career-guidance` | 22 | **Provisional** — rebuilt from section 1 of the live form |
| Mental Health Professionals | `mental-health` | 27 | **Provisional** — rebuilt from section 1 of the live form |
| Special Educators | `special-educator-registration` | 36 | From your uploaded form |
| Curriculum Development Experts | `k12-curriculum-development-expert-registration` | 86 | From your uploaded form |
| Teachers | `teacher-registration` | 51 | **Provisional** — rebuilt from section 1 of the live form |
| Parent Ambassadors | `parent-ambassador` | 34 | From your uploaded form |
| Student Ambassadors | `student-ambassador` | 37 | From your uploaded form |
| Principals Virtual Roundtable | `principal-roundtable-virtual` | 28 | From your uploaded form |
| Principal Roundtables – Delegate | `principal-roundtable-delegate` | 14 | From your uploaded form |

**29 forms, 1264 fields.** 10 are provisional because the full form was not uploaded: `online-school-registration`, `infrastructure-vendor`, `transport-logistics`, `uniform-vendor`, `fee-financing`, `skill-development`, `behaviour-consultant`, `career-guidance`, `mental-health`, `teacher-registration`.

## Field visibility (DPDP)
Each field carries a `visibility` tier:
- `public` — shown free on the basic listing (name, logo, type, city, boards, grades…).
- `detailed` — shown only to entitled viewers (parents who unlocked the profile, organisations on paid plans) and only if the listing has a paid detailed plan.
- `private` — never published: IDs, PAN/GST, certificates, personal contacts of individuals, references, declarations. Stored AES-256-GCM encrypted, visible only to the verification team (audited).

## Updating or adding a form
1. Admin → Registration forms → download any form as JSON (a working template).
2. Edit sections/fields. Field types: `text textarea email tel url number year date pincode state yesno radio select checkbox boolean consent heading file files matrix repeat`. Options: `options`, `other: true`, `maxSelect`, `help`, `required`, `visibility`, `role` (`name logo city state email phone whatsapp website about headline`), `showIf: {field, equals|notEquals}`.
3. Upload it (Admin → Registration forms → Import) or run `flask --app wsgi import-form path.json`. The version is bumped; existing registrations keep their answers.

Top-level keys: `slug, title, intro[], sections[], category (schools|learning|experts|vendors|teachers|ambassadors|events), label, entity (organisation|individual|minor), provisional?`.

## Notes on specific forms
- **School Registration Form**: marked "All fields are mandatory" in your document, so every field is required at submission (drafts can be saved any time). Principal / Contact Person name and photos/videos stay editable after verification.
- **Student Ambassador**: for ages 14–18. Completed from a parent account; submission requires OTP verification of the parent/guardian mobile (verifiable parental consent). Date of birth was dropped for data minimisation (age is kept); all answers are private.
- **Principal Roundtables (2 forms)**: attached to roundtable events as their registration forms (₹599 fee from your form).
- **K-12 Course Providers**: your document was a Google-Form/CRM specification table; the CRM column names map to the outbox payload and internal fields (verification status, lead status, salesperson) live in the admin verification panel.
- **Curriculum Development Expert**: the "For The School Expert — internal use" block (profile classification, tags, verification checklist, engagement status) is implemented in Admin → Registration → Verification for every category.
- **Fee Financing Companies**: new category referenced in the parent journey (no source form); asks for RBI registration as lending must be by a regulated entity.
