# Form fidelity audit — your uploaded documents vs. the live forms

All 19 registration forms you uploaded (`original_uploads/*.docx`) were re-checked line by line against the live form definitions (`tse/forms/*.json`):

* `audit/audit2.py` — every line of every document must appear in the form as a field label, an option, help text, section text or a consent statement.
* `audit/audit3.py` — every question followed by a list of choices must map to one field that carries **all** of those choices.

Corrections applied by `fixes.py` (re-runnable, documented per form):

| Form | What was corrected |
|---|---|
| K–12 Course Providers | Rebuilt directly from your specification table: all 60 fields with your exact types, required flags, options (e.g. 27 course categories + Other, 13 languages + Other), help text, character limits (1,000 / 500 / 2,000), file types, and conditional logic (certificate → certificate type & accreditation; assessment → progress reporting; school programme → partnership experience). **One provider → many courses**: "Add another course" copies provider details; each course gets its own Course ID (TSE-C-xxxxxx) and public listing. Your internal CRM block (credential status, listing status, the 12 lead statuses, lead score, salesperson, last contacted, next follow-up) is in the admin verification screen. |
| K–12 Curriculum Development Experts | Board list restored to all 14 boards + "Other State/UT Board"; projects now have separate *Scope of Work* and *Key Deliverables*; the three declaration statements restored word-for-word; typed e-signature; your *Internal use* block (Expert Registration ID, Profile Classification, Expertise Tags, the 7 verification checks, Engagement Status, Reviewer, Date) now drives the admin screen. |
| Educational Publishers | Curriculum / Boards restored to all 12 choices; "ISBN Registration / Publisher Details" added. |
| Principals Virtual Roundtable | Recording consent is now a choice between your two statements (it was wrongly one tick-box); "How did you hear…" restored to all 6 choices (two had split into a stray field); confirmation message added. |
| Principal Roundtable — Delegate | Closing note about the session link added. |
| Recreation, Hobbies & Enrichment | Trial-class fee appears only for "Yes – Paid", admission fee only for "Yes"; uploads limited to PDF/JPG/PNG as written; "Additional information" is a paragraph again; your submission message added. |
| Individual Online Tutors | The full declaration and all four consent statements restored word-for-word. "Date of Birth / Age Group" is collected as **age group** only (data minimisation). |
| Online Tutoring Institutions | Declaration text, privacy consent and authorised-representative confirmation restored. |
| Educational Consultants | Consent to Profile Listing / Communication are now *I Agree / I Do Not Agree* as written; final confirmation required; thank-you message added. |
| Student Ambassadors | Recognition is a single choice (public / limited-private); all four parent/guardian consent declarations restored; typed student and parent e-signatures (parent confirmed by OTP). Date of birth is **not** collected — age is enough and the student is a minor. |
| Nursery / Preschool | Daycare details appear only when daycare is available ("If Yes"). |
| Parent Ambassadors | The six ambassador activities from your introduction added to the form intro. |
| School / Inclusive School | "Co-educational" label as written. |
| 13 other forms | Help text and declaration wording that had been stored as fake options now shows correctly. |

After the corrections the only lines not mapped to a field are document headings, Google-Form type notes ("Short answer — Required"), CRM column names, letterhead and signature/date lines (replaced by typed e-signature and automatic timestamps).

**Forms without an uploaded document** (still provisional, rebuilt from section 1 of registration.schoolexpert.in): Online Schools, School Infrastructure Vendors, Transportation & Logistics, Uniform/Badge/Bag & Stationery, Fee Financing, Skill Development, Behaviour Consultants, Career Guidance, Mental Health Professionals, Teachers. Upload those documents and they get the same treatment.

## Round 2 — 13 Oct 2026 (Google Forms + 4 documents)

| Source | Result |
|---|---|
| TeacherAmbassadors.docx | New form `teacher-ambassador` (9 sections, 32 questions, word-for-word) in a new **Teacher Ambassadors** category; needs a teacher account; added to the Initiatives page. Q32 "Ambassador Declaration" has no wording in the document — placeholder used until you confirm it. |
| School_Registration_Form_Expanded.docx (updated) | "School Category" question removed, as in your update. |
| Student / Parent Ambassador documents | Byte-identical to the first upload — no change. |
| Preschool Google Form | Extracted to `google_forms/preschool.txt` and merged with `apply_gf.py`: 27 questions now required as in the Google Form, choices added (Live CCTV Access; Registered under State Preschool Guidelines; Other Professional Memberships). The Word version stays the base where it asks for more (e.g. actual fee amounts rather than ticks). Full list: `google_forms/preschool.changes.txt`. |
| 13 other Google Forms | Waiting for full `docs.google.com/forms/...` addresses (the forms.gle short links cannot be opened from the build environment). |
