# Moving to a cloud service later

The application was designed so a move from a GoDaddy VPS to AWS / Azure / Google Cloud is a configuration change, not a rewrite:

| Concern | Today (VPS) | Cloud |
|---|---|---|
| App | gunicorn + systemd | Same Docker image (`Dockerfile`) on AWS ECS/App Runner, Azure Container Apps, or Google Cloud Run |
| Database | PostgreSQL on the VPS | Amazon RDS / Aurora PostgreSQL (ap-south-1 Mumbai), Azure Database for PostgreSQL (Central India), Cloud SQL (asia-south1). Set `DATABASE_URL=...?sslmode=require` |
| Files | `var/uploads`, `var/private` on disk | `STORAGE_BACKEND=s3` + bucket settings (S3, or any S3-compatible store). Private files go under `private/` with no public ACL |
| Sessions | PostgreSQL table | unchanged (works with multiple app instances) |
| Background jobs | systemd worker + cron | a second container running `flask outbox-worker --loop`; scheduler (EventBridge / Cloud Scheduler) for `flask housekeeping` |
| Email | SMTP | Amazon SES / SendGrid via SMTP settings |
| TLS / CDN | nginx + Let's Encrypt | Load balancer certificate + CloudFront / Azure Front Door / Cloud CDN for `/static` and `/media` |

## Data migration steps
1. Put the site in maintenance (nginx `return 503` page) — usually under 15 minutes.
2. `pg_dump -Fc` on the VPS → `pg_restore` into the managed database (same schema, no conversion).
3. Copy uploads: `aws s3 sync var/uploads s3://BUCKET/public/` and `var/private` → `s3://BUCKET/private/` (server-side encryption on). Point the CDN path `/media/*` at the bucket's `public/` prefix so existing `/media/...` URLs keep working.
4. Copy `.env` values into the cloud secret manager; **keep the same `SECRET_KEY` and `FIELD_ENCRYPTION_KEY`**.
5. Run `flask migrate`, switch GoDaddy DNS A/CNAME records to the load balancer, verify, remove maintenance.

## DPDP notes for the move
- Choose an **India region**. If any processor stores data outside India, record it (transfers are permitted unless the Government restricts the destination country) and update the Privacy Policy section 22.
- Sign data-processing terms with the cloud provider; add it to the processor list in `docs/DPDP-COMPLIANCE.md`.
- Keep the 1-year log retention (CloudWatch / Log Analytics retention ≥ 365 days).
