import functools
from flask import g, session, redirect, url_for, request, abort, flash, current_app
from ..db import db

def _bearer_uid():
    """Mobile app / partner API: `Authorization: Bearer <token>` (tokens are stored hashed in api_tokens)."""
    h = request.headers.get('Authorization', '')
    if not (request.path.startswith('/api/') and h.startswith('Bearer ')): return None
    import hashlib
    with db.elevated():   # authentication lookup by secret hash (before any user context exists)
        row = db.one('SELECT id, user_id FROM api_tokens WHERE token_hash = %s AND expires_at > now()', hashlib.sha256(h[7:].strip().encode()).hexdigest())
        if not row: return None
        db.run('UPDATE api_tokens SET last_used_at = now() WHERE id = %s AND (last_used_at IS NULL OR last_used_at < now() - interval \'5 minutes\')', row['id'])
    g.api_token_id = row['id']
    return row['user_id']

def load_user():
    g.user = None; g.org = None; g.orgs = []
    # The API authenticates only with bearer tokens (never the browser cookie), so it is not exposed to CSRF.
    uid = _bearer_uid() if request.path.startswith('/api/') else session.get('uid')
    if not uid: return
    u = db.one("SELECT * FROM users WHERE id = %s AND status IN ('active','pending_deletion')", uid)
    if not u:
        session.pop('uid', None); return
    g.user = u
    if u['account_type'] == 'organisation':
        g.orgs = db.all("""SELECT o.*, m.role AS member_role FROM organisations o JOIN org_members m ON m.org_id = o.id
                           WHERE m.user_id = %s AND o.status <> 'closed' ORDER BY o.id""", u['id'])
        oid = request.headers.get('X-Org-Id', type=int) if getattr(g, 'api_token_id', None) else session.get('org_id')
        g.org = next((o for o in g.orgs if o['id'] == oid), g.orgs[0] if g.orgs else None)

def login_required(fn):
    @functools.wraps(fn)
    def w(*a, **kw):
        if not g.user:
            flash('Please log in to continue.', 'info')
            return redirect(url_for('auth.login', next=request.full_path))
        return fn(*a, **kw)
    return w

def roles(*types):
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **kw):
            if not g.user:
                return redirect(url_for('auth.login', next=request.full_path))
            if g.user['account_type'] not in types and g.user['account_type'] != 'admin':
                abort(403)
            return fn(*a, **kw)
        return w
    return deco

def staff_required(*staff_roles):
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **kw):
            if not g.user: return redirect(url_for('auth.login', next=request.full_path))
            if g.user['account_type'] == 'admin': return fn(*a, **kw)
            if g.user['account_type'] != 'staff' or (staff_roles and g.user['staff_role'] not in staff_roles): abort(403)
            return fn(*a, **kw)
        return w
    return deco

def org_required(min_role='viewer'):
    order = ['viewer', 'editor', 'admin', 'owner']
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **kw):
            if not g.user: return redirect(url_for('auth.login', next=request.full_path))
            if not g.org:
                flash('Register your organisation first.', 'info'); return redirect(url_for('register.index'))
            need = min_role
            if request.method not in ('GET', 'HEAD') and order.index(need) < order.index('editor'):
                need = 'editor'    # viewers can look, never change (least privilege inside a tenant)
            if order.index(g.org['member_role']) < order.index(need): abort(403)
            return fn(*a, **kw)
        return w
    return deco

def is_staff():
    u = getattr(g, 'user', None)
    return bool(u and u['account_type'] in ('admin', 'staff'))

def tenant_guard(table, row_id, column='org_id'):
    """Fetch a tenant-owned row, 404 unless it belongs to the active organisation (multi-tenant isolation)."""
    row = db.one(f'SELECT * FROM {table} WHERE id = %s', row_id)
    if not row or (not is_staff() and (not g.org or row[column] != g.org['id'])):
        abort(404)
    return row


def fresh_auth(minutes=15):
    """Step-up authentication: sensitive actions need a password (and 2-step code) entered in the last few minutes."""
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **kw):
            import time
            if not g.user: return redirect(url_for('auth.login', next=request.full_path))
            if getattr(g, 'api_token_id', None) or current_app.testing and not current_app.config.get('ENFORCE_FRESH_AUTH'):
                return fn(*a, **kw)
            if time.time() - (session.get('auth_at') or 0) > minutes * 60:
                return redirect(url_for('auth.reauth', next=request.full_path))
            return fn(*a, **kw)
        return w
    return deco
