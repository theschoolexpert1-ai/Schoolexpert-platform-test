# Integrating with the existing www.schoolexpert.in (GoDaddy)

The new platform **replaces and absorbs** the current site on the same domain, keeping every old link working.

## Option A — recommended: move the domain to the platform (one cut-over)
1. **Server:** a GoDaddy VPS (Ubuntu 22.04, 2 vCPU / 4 GB to start) or any cloud VM. Follow `DEPLOYMENT-GODADDY.md`.
2. **Content:** for each page of the current site, create it in Admin → Content Studio → Pages (paste text or HTML) and give it the **same path** in Site Integration Desk (e.g. `/about-us`). Or map old URLs to the new equivalents as 301 redirects (CSV import). Common ones are pre-loaded.
3. **registration.schoolexpert.in:** point this sub-domain at the same server; nginx 301-redirects it to `/register` (see `deploy/nginx-schoolexpert.conf`). All 26 forms already live in the Registration Centre.
4. **DNS (GoDaddy → My Products → DNS):** `A @ → <server IP>`, `CNAME www → @`, `A registration → <server IP>`. Keep MX records unchanged so email keeps working. Lower TTL to 600 a day before.
5. **SSL:** `certbot --nginx -d schoolexpert.in -d www.schoolexpert.in -d registration.schoolexpert.in`.
6. **Search Console:** verify the domain, submit `/sitemap.xml`, and use *Change of address* only if the domain changes (it doesn't). Watch the redirect "hits" column in Site Integration Desk for the first weeks.

## Option B — phased: keep the old site while the platform runs on a sub-domain
Run the platform at `app.schoolexpert.in`, then add widgets to the old pages:
```html
<div data-tse-widget="school-search"></div>
<script async src="https://app.schoolexpert.in/widget.js"></script>
```
School websites can show a verified badge with `data-tse-widget="school-card" data-slug="<listing-slug>"`. Move to Option A when ready.

## What we need from you
- Which builder the current site uses (GoDaddy Website Builder, WordPress, other) and an export or list of its pages/URLs.
- GoDaddy DNS access (or a delegate login) and a VPS/cloud account.
- Razorpay live keys, SMTP (e.g. Google Workspace/Zoho) or SES credentials, MSG91/WhatsApp keys, GA4 + Google Ads IDs and conversion labels, Anthropic API key (AI CV & School Match advisor).
