"""Operational commands:
  flask --app wsgi migrate            apply SQL migrations
  flask --app wsgi seed               load categories, forms, plans, CMS content (idempotent)
  flask --app wsgi seed --demo        also create demo accounts and sample listings
  flask --app wsgi create-admin EMAIL NAME
  flask --app wsgi outbox-worker      deliver CRM events + emails (run every minute via cron/systemd)
  flask --app wsgi housekeeping       DPDP retention, expiries, reminders (run daily)
  flask --app wsgi import-form FILE   load/replace a form definition JSON (when you upload a new/updated form)
  flask --app wsgi rotate-keys        re-encrypt private data with the newest FIELD_ENCRYPTION_KEYS key
  flask --app wsgi verify-audit       check the tamper-evident audit-log hash chain
"""
import os, glob, json, click, getpass
from .db import db

def apply_migrations():
    """Apply pending SQL migrations in order; returns the versions applied. Used by `flask migrate` and /cron/setup."""
    applied = []
    db.script('CREATE TABLE IF NOT EXISTS schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())')
    done = {r['version'] for r in db.all('SELECT version FROM schema_migrations')}
    for path in sorted(glob.glob(os.path.join(os.path.dirname(__file__), 'db', 'migrations', '*.sql'))):
        v = os.path.basename(path)
        if v in done: continue
        sql = open(path, encoding='utf-8').read()
        with db.transaction():
            db.script(sql.replace('CREATE TABLE schema_migrations', 'CREATE TABLE IF NOT EXISTS schema_migrations'))
            db.run('INSERT INTO schema_migrations (version) VALUES (%s)', v)
        applied.append(v)
    return applied

def register(app):
    @app.cli.command('migrate')
    def migrate():
        mig = os.getenv('MIGRATION_DATABASE_URL')
        if mig: db.init(mig, 2)        # schema changes run as the owner role; the app itself runs as tse_app (no DDL)
        for v in apply_migrations(): click.echo(f'applied {v}')
        click.echo('migrations up to date')

    @app.cli.command('seed')
    @click.option('--demo', is_flag=True)
    def seed(demo):
        from .db import seed as s
        s.run(demo=demo); click.echo('seed complete')

    @app.cli.command('create-admin')
    @click.argument('email')
    @click.argument('name')
    def create_admin(email, name):
        from .lib.security import hash_password
        pw = os.getenv('ADMIN_PASSWORD') or getpass.getpass('Password: ')
        db.run("""INSERT INTO users (email, name, password_hash, account_type, is_adult, email_verified_at, staff_role)
                  VALUES (%s, %s, %s, 'admin', true, now(), 'admin') ON CONFLICT (email) DO UPDATE SET account_type = 'admin', password_hash = EXCLUDED.password_hash""",
               email, name, hash_password(pw))
        click.echo('admin ready')

    @app.cli.command('outbox-worker')
    @click.option('--loop', is_flag=True)
    def outbox_worker(loop):
        import time
        from .lib import crm
        while True:
            n = crm.deliver_pending(); click.echo(f'delivered {n}')
            if not loop: break
            time.sleep(30)

    @app.cli.command('housekeeping')
    def housekeeping():
        from .lib import retention; click.echo(json.dumps(retention.run(), indent=1))

    @app.cli.command('import-form')
    @click.argument('path')
    def import_form(path):
        from .db.seed import upsert_form
        d = json.load(open(path, encoding='utf-8')); upsert_form(d, bump=True); click.echo(f"imported {d['slug']}")

    @app.cli.command('rotate-keys')
    def rotate_keys():
        """Re-encrypt every encrypted field with the newest key in FIELD_ENCRYPTION_KEYS (run after adding a new key)."""
        from .lib.security import encrypt_json, decrypt_json, _key
        kid = _key()[0]; n = 0
        for r in db.all("SELECT id, private_enc FROM registrations WHERE private_enc IS NOT NULL AND private_enc NOT LIKE %s", kid + ':%'):
            db.run('UPDATE registrations SET private_enc = %s WHERE id = %s', encrypt_json(decrypt_json(r['private_enc'])), r['id']); n += 1
        for r in db.all("SELECT id, mfa_secret_enc FROM users WHERE mfa_secret_enc IS NOT NULL AND mfa_secret_enc NOT LIKE %s", kid + ':%'):
            db.run('UPDATE users SET mfa_secret_enc = %s WHERE id = %s', encrypt_json(decrypt_json(r['mfa_secret_enc'])), r['id']); n += 1
        click.echo(f're-encrypted {n} records with key {kid}')

    @app.cli.command('verify-audit')
    def verify_audit():
        """Recompute the audit-log hash chain; any edited or deleted row breaks the chain."""
        rows = db.all("""SELECT id, prev_hash, row_hash, encode(digest(prev_hash || '|' || coalesce(actor_id::text, '') || '|' || coalesce(action, '') || '|' ||
                         coalesce(entity, '') || '|' || coalesce(entity_id, '') || '|' || coalesce(org_id::text, '') || '|' || coalesce(host(ip), '') || '|' ||
                         meta::text || '|' || created_at::text, 'sha256'), 'hex') AS recomputed FROM audit_log WHERE row_hash IS NOT NULL ORDER BY id""")
        prev = None; bad = []
        for r in rows:
            if r['row_hash'] != r['recomputed'] or (prev is not None and r['prev_hash'] != prev): bad.append(r['id'])
            prev = r['row_hash']
        click.echo(f'{len(rows)} entries checked; ' + ('chain intact' if not bad else f'TAMPERING DETECTED at ids {bad[:20]}'))
        if bad: raise SystemExit(1)
