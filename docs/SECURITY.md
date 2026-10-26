# Security — defence in depth

Every layer assumes the one in front of it can fail. A bug in one place should not expose a school's, vendor's, teacher's or parent's data.
**`python tests/security.py`** proves each control below (71 checks); `tests/e2e.py` and `tests/smoke.py` prove nothing broke.

| Layer | Controls | Where |
|---|---|---|
| **1. Edge / network** | HTTPS only (TLS 1.2/1.3, HSTS preload, OCSP stapling); rate limits on sign-in, API and pages; connection limits; scanner/probe blocking; dotfiles and non-Python paths blocked; uploads can never be served as HTML/JS/SVG; optional office/VPN allow-list for `/admin` | `deploy/nginx-schoolexpert.conf`, `deploy/nginx-snippets.conf` |
| **2. Server / OS** | Firewall (only 22/80/443), SSH keys only and no root login, fail2ban for SSH and repeated sign-in failures, automatic security updates, kernel hardening, auditd, ClamAV, PostgreSQL bound to localhost with SCRAM | `deploy/harden-server.sh` |
| **3. Process / container** | App runs as an unprivileged user in a systemd sandbox (read-only system, no new privileges, no capabilities, syscall filter, memory cap); container is non-root, read-only, all capabilities dropped, bound to localhost | `deploy/schoolexpert.service`, `Dockerfile`, `docker-compose.yml` |
| **4. Browser** | Content-Security-Policy with per-request nonces (no inline scripts or handlers), frame protection, COOP/CORP, nosniff, strict referrer, permissions policy, personal pages `no-store`; `__Host-` session cookie (Secure, HttpOnly, SameSite) | `tse/__init__.py` |
| **5. Identity** | scrypt password hashing; NIST-style password rules (length, common/personal passwords blocked); generic errors and equal timing (no account enumeration); lock after 5 failures with email alert; new-network sign-in alerts; **two-step verification (TOTP) — mandatory for staff**, optional for everyone, replay-proof, single-use recovery codes; step-up re-authentication before private documents, refunds, user/role changes and DPDP requests | `tse/routes/auth.py`, `tse/lib/mfa.py`, `tse/lib/auth.py` |
| **6. Sessions** | Server-side sessions (only a random id in the cookie, stored hashed); id rotated at sign-in; idle time-out (staff 30 min, others 72 h) and absolute lifetime; "where you're signed in" + sign out all other devices; password change/reset revokes other sessions | `tse/lib/security.py`, Account security page |
| **7. Authorisation** | Role checks per account type; organisation roles (owner/admin/editor/viewer — viewers can never change anything); tenant guard on every record (IDOR returns not-found); staff see only their desks; API uses bearer tokens only (ignores cookies → no CSRF); CSRF tokens on every form; honeypots against bots | `tse/lib/auth.py`, `tse/routes/admin_desks.py` |
| **8. Database** | **Row-level security inside PostgreSQL** on 15 tenant tables — even raw SQL from a buggy page only returns the signed-in user's / organisation's rows; least-privilege roles (app has no DDL; read-only reporting role); statement/idle time-outs; parameterised queries everywhere; TLS required to remote databases | `tse/db/migrations/004_security.sql`, `tse/db/db.py` |
| **9. Data** | Private form answers (IDs, PAN/GST, personal contacts, references, minors' data) AES-256-GCM encrypted; private documents encrypted at rest; key ring with rotation (`flask rotate-keys`); photos re-encoded (location/EXIF removed); PDFs with scripts, Office files with macros, disguised executables and zip-bombs rejected; virus scan; private files only through an authorised, audited route | `tse/lib/security.py`, `tse/lib/storage.py` |
| **10. Audit & monitoring** | Append-only, hash-chained audit log (edits/deletes impossible; nightly `flask verify-audit` detects tampering); Security monitoring desk (failed sign-ins, lock-outs, staff 2-step status, hot IPs); personal data and secrets redacted from logs; `/healthz`; `/.well-known/security.txt` | `tse/routes/admin_desks.py`, `deploy/crontab.txt` |
| **11. Operations** | App refuses to start in production with weak/missing secrets, insecure cookies, test payments or an unencrypted remote database; encrypted nightly backups with checksums + off-site copy + monthly restore drill; outbound calls limited to public HTTPS (SSRF guard); dependency pinning | `tse/__init__.py`, `deploy/backup.sh`, `deploy/restore-test.sh` |

## Going live checklist
1. `deploy/harden-server.sh`, then nginx snippets + certbot.
2. Create `.env` from `.env.example`: long `SECRET_KEY`, `FIELD_ENCRYPTION_KEYS` (store an offline copy), `tse_app` database password, `MFA_REQUIRED_FOR_STAFF=true`, `CLAMD_HOST`.
3. `MIGRATION_DATABASE_URL=… flask migrate` (creates the least-privilege roles), set the `tse_app` password, then start the service.
4. Every staff member signs in and sets up two-step verification (enforced).
5. Root crontab: backups and restore drill; app crontab: housekeeping and audit verification.
6. Optional: `ADMIN_IP_ALLOWLIST` with office/VPN addresses.

## If something goes wrong (incident & DPDP breach)
1. Contain: lock affected accounts (Security monitoring desk), sign out sessions, rotate keys/secrets, block IPs.
2. Record it in Admin → Privacy & Compliance → **Breach register** (what, when, data types, people affected).
3. DPDP Rules 2025: intimate the Data Protection Board **without delay**, send the detailed report **within 72 hours**, and inform affected people in plain language with steps they can take.
4. Preserve evidence: audit log (verify the chain), nginx/app logs, backups.
5. Review and fix the root cause; add a test to `tests/security.py`.

Responsible disclosure: security@schoolexpert.in (published at `/.well-known/security.txt`).
