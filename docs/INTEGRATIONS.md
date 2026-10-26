# Integrations

## Payment gateway — Razorpay
Implemented with Razorpay **Orders API + Standard Checkout + webhooks** (`tse/lib/payments.py`, `tse/routes/pay.py`).
1. Razorpay Dashboard → API Keys → set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `PAYMENT_GATEWAY=razorpay`.
2. Webhooks → URL `https://www.schoolexpert.in/webhooks/razorpay`, events `payment.captured`, `order.paid`, secret → `RAZORPAY_WEBHOOK_SECRET`.
3. Every payment is verified by HMAC signature (browser callback) **and** by webhook; fulfilment is idempotent.
4. Razorpay website-compliance pages already exist: Terms, Privacy, Refund & Cancellation, Shipping & Delivery, Contact.

All revenue streams share one checkout. Order kinds: `plan` (school / partner / professional / teacher plans, Founding Partner), `unlock_pack` (verified school leads for parents), `personal_assistance`, `expert`, `event_pass`, `marketplace`, `subscription` (NewsWorms, Book Club), `job_boost`. Refunds from Admin → Orders. GST is added (18% services; marketplace prices include GST). To switch to PayU/Cashfree, implement `gateway_checkout`, signature verification and refund in `payments.py` — nothing else changes.

## CRM
Business events are written to the `outbox` table and delivered by the worker with retries (`tse/lib/crm.py`):
`lead.created · lead.updated · registration.submitted · registration.verified · order.paid · expert_request.created · pa_request.created · job_application.created · contact.created · newsletter.subscribed · sponsorship.enquiry · event.registration`

| `CRM_PROVIDER` | Setup |
|---|---|
| `zoho` (recommended for Indian SMEs) | Zoho API console → self client → scope `ZohoCRM.modules.ALL` → refresh token; `ZOHO_DC=in`. Leads are upserted by email. |
| `hubspot` | Private app token with `crm.objects.contacts.write`. Contacts upserted by email. |
| `leadsquared` | Host, access key and secret key. |
| `webhook` | Any system (Zapier, Make, n8n, custom CRM): JSON POST with `X-TSE-Signature` = HMAC-SHA256(body, `CRM_WEBHOOK_SECRET`). |

Until a CRM is connected, Admin → Leads / Ask The School Expert / Personal Assistance act as a built-in CRM, and organisations manage their own leads in their dashboards. Only data the person consented to share is sent (DPDP purpose limitation); add the CRM vendor to your processor list.

## Email & SMS
- SMTP: GoDaddy Professional Email (`smtpout.secureserver.net:587`), Microsoft 365, Google Workspace or Amazon SES. Emails are queued in the outbox and retried.
- SMS OTP (guardian consent): MSG91 (`SMS_PROVIDER=msg91`). Register a DLT template, for example: "The School Expert: OTP {#var#} to give consent for the Student Ambassador application. Valid 15 minutes."

## AI CV builder
Set `ANTHROPIC_API_KEY` to have Claude draft CVs. Only professional fields are sent (no phone, email, DOB, address) and only with the teacher's consent. Without a key the builder uses a deterministic template, so the feature always works.

## Analytics & ads
`GA4_ID` and `GOOGLE_ADS_ID` load **only after the visitor accepts analytics cookies**. Recommended GA4 conversions: `sign_up`, `purchase` (order paid), `generate_lead` (enquiry), `begin_checkout`. See `docs/SEO-SEM.md`.

## Object storage
`STORAGE_BACKEND=s3` with `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` (and `S3_ENDPOINT` for non-AWS S3-compatible stores). Uploads are signed with AWS SigV4 without an SDK.
