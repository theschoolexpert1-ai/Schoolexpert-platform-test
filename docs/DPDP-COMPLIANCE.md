# DPDP Act 2023 & DPDP Rules 2025 — compliance register

The Digital Personal Data Protection Rules were notified on **13 November 2025**. Most substantive obligations apply **18 months later (May 2027)**, and consent-manager provisions apply after 12 months. The platform implements them now. *This is an engineering control map, not legal advice — have it reviewed by Indian counsel together with the Privacy Policy.*

## Control map

| Obligation | Where it is implemented |
|---|---|
| **Notice before consent** (s.5, Rule 3): itemised data, purposes, how to withdraw and complain, in clear language | Purpose-specific notices in `consent_notices` (data items + retention), shown beside every consent box: signup, registration, listing publication, enquiries, job applications, Personal Assistance, expert requests, AI CV, community, marketing, cookies. Versioned. |
| **Free, specific, informed, unambiguous consent** (s.6) | Separate unticked checkboxes per purpose; marketing is optional; nothing pre-ticked; cookie banner offers "Essential only" as an equal choice. |
| **Consent records & proof** (s.6(10)) | Append-only `consents` table: purpose, notice version, method, context, IP, user agent, timestamp, withdrawal time. |
| **Withdrawal as easy as giving** (s.6(4)) | Privacy Centre one-click withdraw per purpose; withdrawing listing consent unpublishes the listing / hides the teacher profile; marketing withdrawal unsubscribes newsletters. |
| **Purpose limitation & minimisation** | Forms tag each field public / detailed / private. Leads share only name, phone, email and message, and only with the chosen organisation. AI CV sends no contact data. Student Ambassador DOB dropped (age kept). Parents' Corner and community block children's identifiers. |
| **Children** (s.9, Rule 10): verifiable parental consent; no tracking, behavioural monitoring or targeted ads | Accounts are 18+ (declaration at signup). Children's services (Book Club, NewsWorms, storytelling) run from the parent account without child details. Student Ambassador (14–18) requires OTP verification of the parent/guardian mobile before submission, recorded as `guardian_student_ambassador` consent; all answers private and encrypted. Analytics load only after cookie consent and are never targeted at children. |
| **Accuracy** (s.8(3)) | Users edit their own profiles; correction requests in the Privacy Centre; verified fields locked to protect parents with a change-request path. |
| **Reasonable security safeguards** (s.8(5), Rule 6) | TLS (HSTS), scrypt password hashing, AES-256-GCM encryption of private registration fields, private files never web-served (authorised route + audit), server-side sessions, CSRF protection, rate limiting, CSP and security headers, image re-encoding that strips EXIF/GPS, role-based access, tenant isolation, encrypted nightly backups. |
| **Logs retained ≥ 1 year** (Rule 6/8) | `audit_log` records logins, private-data views, admin actions, exports and consent changes; kept 24 months (`flask housekeeping`). |
| **Breach intimation** (s.8(6), Rule 7): to each affected person without delay; to the Board without delay and a detailed report within 72 hours | Admin → Breach register (`breach_incidents`) records detection, categories, affected count, impact, mitigation, Board intimation, 72-hour report and notification timestamps. Procedure below. |
| **Retention & erasure** (s.8(7)) | `flask housekeeping`: abandoned drafts deleted after 12 months; rejected registrations scrubbed after 12 months; contact messages after 24 months; sessions/tokens expire; erasure requests anonymise accounts after a 30-day grace period (invoices kept 8 years under CGST s.36). |
| **Rights: access, correction, erasure, grievance, nomination** (s.11–14) | Privacy Centre: instant JSON export (data + consents + with whom shared), request forms for correction/erasure/withdrawal/grievance, nominee registration. Admin → Data-principal requests with due dates; requester emailed on every update. |
| **Grievance redressal within the prescribed period** (Rule 14: ≤ 90 days) | Every request gets a `due_at` 90 days out (internal target 30); overdue requests are highlighted on the admin dashboard. Grievance Officer contact in the footer, Privacy Centre and Privacy Policy. |
| **Processors** (s.8(2)) | Use only with written contracts: hosting (GoDaddy / cloud), Razorpay, CRM (Zoho/HubSpot/LeadSquared), email (SMTP provider), SMS (MSG91), Anthropic (AI CV, optional). Keep this list in your records of processing. |
| **Cross-border transfers** (s.16) | Host in India. If an optional processor processes outside India (e.g. AI provider), it is disclosed in the notice; transfers are allowed unless a country is restricted by the Government. |
| **Publicly available data** | Only fields the user marks for publication via the listing consent appear publicly; detailed fields only for entitled viewers. |

## Retention schedule
| Data | Retention |
|---|---|
| Account & profile | while account is active; anonymised 30 days after an erasure request |
| Registration drafts | 12 months of inactivity |
| Rejected registrations | 12 months, then scrubbed |
| Leads shared with organisations | organisations are asked to keep them ≤ 12 months (Terms) |
| Job applications | vacancy + 12 months |
| Orders & invoices | 8 years (tax law) |
| Audit / processing logs | 24 months (Rules require ≥ 1 year) |
| Contact messages | 24 months |
| Backups | 30 days rolling |

## Breach response procedure
1. **Detect & contain** (hour 0): isolate affected systems, rotate keys/passwords, open a breach record.
2. **Assess**: what data, whose, how many, likely impact.
3. **Intimate the Data Protection Board without delay**, and send the **detailed report within 72 hours** (facts, timing, cause, mitigation, notifications made). Record timestamps in the register.
4. **Inform affected people without delay** in plain language: what happened, likely consequences, what we did, what they can do, and our contact.
5. **Review**: root cause, fixes, update this document.

## Items for your legal team
- Section 46 of the Privacy Policy reads like an internal drafting note ("should be reviewed… before publication"). It is published verbatim as supplied; remove it after legal review.
- Confirm Grievance Officer name and contact; DPO appointment is mandatory only if notified as a Significant Data Fiduciary.
- Translate the short consent notices into Indian languages your users prefer (the `consent_notices.lang` column is ready for this).
- Data processing agreements with every processor listed above.
