# Team prototype on Vercel

## 1. Database (Neon, free)
Vercel project → Storage → Create Database → **Neon** → region **Singapore** (closest to Mumbai) → Connect to the project.
This adds `DATABASE_URL`, `DATABASE_URL_UNPOOLED` etc. The app automatically uses the **unpooled** URL
(row-level security needs a real session, not PgBouncer).

## 2. Environment variables (Settings → Environment Variables, all environments)
| Name | Value |
|---|---|
| `SECRET_KEY` | `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `FIELD_ENCRYPTION_KEYS` | `python -c "import os,base64;print('v1:'+base64.b64encode(os.urandom(32)).decode())"` — keep a copy safe |
| `CRON_SECRET` | any long random string |
| `STAGING_BASIC_AUTH` | `team:SomeSharedPassword` (optional — password-protects the prototype) |

Leave `TSE_ENV` unset: on Vercel it defaults to **staging** (banner, `noindex`, simulated payments, files stored in the database).

## 3. Build settings
Framework Preset: **Other**. No build command. `vercel.json` routes every request to `api/index.py`.
Redeploy after adding the variables.

## 4. Create the tables and demo data (once)
PowerShell:
```
curl.exe -X POST -H "Authorization: Bearer YOUR_CRON_SECRET" "https://YOUR-PROJECT.vercel.app/cron/setup?demo=1"
```
Re-run it after any update that adds a migration (it only applies what is new; seeding is idempotent).

Alternative from your PC (venv active): set `DATABASE_URL` to the Neon **unpooled** URL and run
`flask --app wsgi migrate` then `flask --app wsgi seed --demo`.

## Troubleshooting
`500 FUNCTION_INVOCATION_FAILED` → Vercel project → **Logs** → open the failed request; the Python traceback is there.
"Refusing to start in staging — set: …" lists the missing variables.
