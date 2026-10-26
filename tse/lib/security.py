"""Sessions (server-side, Postgres), CSRF, password hashing, field encryption, rate limiting, audit."""
import os, re, json, secrets, hashlib, base64, time, datetime, threading, functools
from flask import request, session, abort, g, current_app
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict
from werkzeug.security import generate_password_hash, check_password_hash
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from ..db import db

# ---------------- sessions ----------------
class DbSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, new=False):
        def on_update(self_): self_.modified = True
        super().__init__(initial, on_update)
        self.sid, self.new, self.modified = sid, new, False

class PgSessionInterface(SessionInterface):
    cookie = 'tse_session'
    def open_session(self, app, req):
        sid = req.cookies.get(('__Host-' if app.config['SESSION_COOKIE_SECURE'] else '') + self.cookie)
        if sid:
            row = db.one('SELECT data FROM sessions WHERE sid = %s AND expires_at > now()', hashlib.sha256(sid.encode()).hexdigest())
            if row: return DbSession(row['data'], sid=sid)
        return DbSession(sid=secrets.token_urlsafe(32), new=True)
    def save_session(self, app, sess, resp):
        key = hashlib.sha256(sess.sid.encode()).hexdigest()
        if not sess:
            if sess.modified:
                db.run('DELETE FROM sessions WHERE sid = %s', key)
                resp.delete_cookie(('__Host-' if app.config['SESSION_COOKIE_SECURE'] else '') + self.cookie, path='/', secure=app.config['SESSION_COOKIE_SECURE'])
            return
        days = app.config['SESSION_DAYS']
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)
        if sess.modified or sess.new or not getattr(g, '_sess_touched', False):
            db.run("""INSERT INTO sessions (sid, data, user_id, expires_at, ip, user_agent, last_seen_at) VALUES (%s, %s, %s, %s, %s, %s, now())
                      ON CONFLICT (sid) DO UPDATE SET data = EXCLUDED.data, user_id = EXCLUDED.user_id, expires_at = EXCLUDED.expires_at,
                      ip = EXCLUDED.ip, user_agent = EXCLUDED.user_agent, last_seen_at = now()""",
                   key, db.Json(dict(sess)), sess.get('uid'), expires, client_ip(), (request.headers.get('User-Agent') or '')[:200])
        resp.set_cookie(('__Host-' if app.config['SESSION_COOKIE_SECURE'] else '') + self.cookie, sess.sid, expires=expires, httponly=True,
                        secure=app.config['SESSION_COOKIE_SECURE'], samesite='Lax', path='/')

def rotate_session():
    """New session id on privilege change (login) to prevent fixation."""
    data = dict(session)
    old = hashlib.sha256(session.sid.encode()).hexdigest()
    db.run('DELETE FROM sessions WHERE sid = %s', old)
    session.sid = secrets.token_urlsafe(32); session.clear(); session.update(data); session.modified = True

# ---------------- CSRF ----------------
def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(24)
    return session['_csrf']

CSRF_EXEMPT = ('/webhooks/', '/cron/')
def csrf_protect():
    if request.method in ('POST', 'PUT', 'PATCH', 'DELETE') and not request.path.startswith(CSRF_EXEMPT):
        sent = request.form.get('_csrf') or request.headers.get('X-CSRF-Token')
        if not sent or not secrets.compare_digest(sent, session.get('_csrf', '')):
            abort(400, 'Your session expired or the form was tampered with. Please reload the page and try again.')

# ---------------- passwords ----------------
def hash_password(pw): return generate_password_hash(pw, method='scrypt')
def verify_password(h, pw): return check_password_hash(h, pw)
_COMMON = None
def _common():
    global _COMMON
    if _COMMON is None:
        path = os.path.join(os.path.dirname(__file__), 'common_passwords.txt')
        _COMMON = set(open(path, encoding='utf-8').read().split()) if os.path.exists(path) else set()
    return _COMMON

def password_problem(pw, email='', name=''):
    """NIST SP 800-63B style: length over complexity rules, block common/breached and personal passwords."""
    pw = pw or ''
    if len(pw) < 10: return 'Use at least 10 characters (a short phrase is easy to remember).'
    if len(pw) > 128: return 'Use at most 128 characters.'
    low = pw.lower(); core = re.sub(r'[^a-z]', '', low)
    if low in _common() or core in _common() or len(set(pw)) < 4: return 'That password is too common or predictable. Try a short phrase of unrelated words.'
    for part in [(email or '').split('@')[0].lower()] + [x.lower() for x in (name or '').split() if len(x) >= 4]:
        if part and len(part) >= 4 and part in low: return 'Please do not use your name or email in your password.'
    if any(w in low for w in ('schoolexpert', 'school123', 'password', 'qwerty', '12345678')): return 'That password is too easy to guess.'
    return None

def token_hash(t): return hashlib.sha256(t.encode()).hexdigest()

def make_token(purpose, target, user_id=None, minutes=60, data=None, numeric=False):
    raw = f'{secrets.randbelow(10**6):06d}' if numeric else secrets.token_urlsafe(32)
    db.insert('tokens', dict(purpose=purpose, target=target, token_hash=token_hash(raw), user_id=user_id, data=data or {},
              expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)))
    return raw

def use_token(purpose, raw, target=None, consume=True):
    sql = 'SELECT * FROM tokens WHERE purpose = %s AND token_hash = %s AND used_at IS NULL AND expires_at > now()'
    args = [purpose, token_hash(raw)]
    if target is not None: sql += ' AND target = %s'; args.append(target)
    row = db.one(sql + ' ORDER BY id DESC LIMIT 1', *args)
    if row and consume: db.run('UPDATE tokens SET used_at = now() WHERE id = %s', row['id'])
    return row

def check_otp(purpose, target, code):
    row = db.one('SELECT * FROM tokens WHERE purpose = %s AND target = %s AND used_at IS NULL AND expires_at > now() ORDER BY id DESC LIMIT 1', purpose, target)
    if not row or row['attempts'] >= 5: return None
    if not secrets.compare_digest(row['token_hash'], token_hash((code or '').strip())):
        db.run('UPDATE tokens SET attempts = attempts + 1 WHERE id = %s', row['id']); return None
    db.run('UPDATE tokens SET used_at = now() WHERE id = %s', row['id'])
    return row

# ---------------- field encryption (AES-256-GCM) ----------------
def _keys():
    """Key ring for AES-256-GCM. FIELD_ENCRYPTION_KEYS="v2:<base64>,v1:<base64>" (newest first) allows rotation:
    new data uses the first key, old data stays readable; `flask rotate-keys` re-encrypts everything with the newest key."""
    ring = current_app.config.get('FIELD_ENCRYPTION_KEYS') or ''
    out = []
    for part in [x.strip() for x in ring.split(',') if x.strip()]:
        kid, b64 = part.split(':', 1); out.append((kid, base64.b64decode(b64)))
    if not out and current_app.config.get('FIELD_ENCRYPTION_KEY'):
        out = [('v1', base64.b64decode(current_app.config['FIELD_ENCRYPTION_KEY']))]
    if not out:   # development only — production refuses to start without a key (see create_app)
        out = [('v1', hashlib.sha256((current_app.config['SECRET_KEY'] + ':fields').encode()).digest())]
    return out

def _key(kid=None):
    ks = _keys()
    if kid is None: return ks[0]
    for k, v in ks:
        if k == kid: return k, v
    raise ValueError('unknown encryption key id ' + kid)

def encrypt_bytes(data, aad=b'tse-file'):
    kid, key = _key(); nonce = os.urandom(12)
    return b'TSEENC1' + kid.encode().ljust(8, b' ') + nonce + AESGCM(key).encrypt(nonce, data, aad)

def decrypt_bytes(blob, aad=b'tse-file'):
    if not blob.startswith(b'TSEENC1'): return blob          # legacy unencrypted file
    kid = blob[7:15].decode().strip(); nonce = blob[15:27]
    return AESGCM(_key(kid)[1]).decrypt(nonce, blob[27:], aad)

def encrypt_json(obj):
    if not obj: return None
    kid, key = _key(); nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, json.dumps(obj, default=str).encode(), b'tse-v1')
    return f'{kid}:' + base64.b64encode(nonce + ct).decode()

def decrypt_json(blob):
    if not blob: return {}
    kid, b64 = blob.split(':', 1)
    raw = base64.b64decode(b64)
    return json.loads(AESGCM(_key(kid)[1]).decrypt(raw[:12], raw[12:], b'tse-v1'))

# ---------------- rate limiting (per-process sliding window) ----------------
_hits = {}; _hl = threading.Lock()
def rate_limit(key, limit, per_seconds):
    """Sliding-window limit shared by every app worker/server (UNLOGGED Postgres table), with an in-process fallback."""
    try:
        n = db.val("SELECT count(*) FROM rate_events WHERE bucket = %s AND at > now() - make_interval(secs => %s)", key, per_seconds)
        if n >= limit: return False
        db.run('INSERT INTO rate_events (bucket) VALUES (%s)', key)
        return True
    except Exception:
        pass
    now = time.time()
    with _hl:
        arr = [t for t in _hits.get(key, []) if now - t < per_seconds]
        if len(arr) >= limit:
            _hits[key] = arr; return False
        arr.append(now); _hits[key] = arr
        if len(_hits) > 50000: _hits.clear()
    return True

def limited(limit, per_seconds, scope=None):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            if request.method == 'POST' and not (current_app.testing and not current_app.config.get('ENFORCE_RATE_LIMITS')):
                k = f'{scope or fn.__name__}:{client_ip()}'
                if not rate_limit(k, limit, per_seconds):
                    abort(429)
            return fn(*a, **kw)
        return wrapper
    return deco

def client_ip():
    # ProxyFix (TRUSTED_PROXIES) has already resolved the real client address; raw X-Forwarded-For is never trusted.
    return request.remote_addr or '0.0.0.0'

# ---------------- audit ----------------
def audit(action, entity=None, entity_id=None, meta=None, org_id=None, actor_id=None):
    try:
        u = getattr(g, 'user', None)
        db.insert('audit_log', dict(actor_id=actor_id or (u['id'] if u else None), actor_type=(u['account_type'] if u else 'system'),
                  action=action, entity=entity, entity_id=str(entity_id) if entity_id is not None else None,
                  org_id=org_id, ip=client_ip() if request else None, meta=meta or {}), returning=None)
    except Exception as e:  # audit must never break the request
        current_app.logger.warning('audit failed: %s', e)


def attribution():
    """First-touch marketing attribution for the current visitor (see app._capture_attribution)."""
    from flask import g
    return (getattr(g, 'attrib', None) or {}).get('src')

def referral_code():
    from flask import g, request
    return (request.form.get('ref') if request.method == 'POST' else None) or (getattr(g, 'attrib', None) or {}).get('ref')


def conversion(name, ads_label=None, **params):
    """Queue a GA4 / Google Ads conversion event; rendered by base.html only if the visitor accepted analytics cookies."""
    from flask import session
    try:
        q = list(session.get('_conv') or [])[-5:]
        q.append({'name': name, 'params': params, 'ads_label': ads_label}); session['_conv'] = q
    except Exception:
        pass

def pop_conversions():
    from flask import session
    try: return session.pop('_conv', None) or []
    except Exception: return []


# ---------------- outbound requests (SSRF guard) ----------------
def safe_outbound_url(url):
    """Only https URLs that resolve to public internet addresses (blocks internal network / cloud metadata endpoints)."""
    import socket, ipaddress, urllib.parse
    u = urllib.parse.urlparse(url or '')
    if u.scheme != 'https' or not u.hostname: raise ValueError('outbound URL must be https')
    for info in socket.getaddrinfo(u.hostname, u.port or 443, proto=socket.IPPROTO_TCP):
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise ValueError('outbound URL resolves to a non-public address')
    return url

# ---------------- bots ----------------
def honeypot_tripped():
    """Hidden form field that people never see; automated sign-up/contact bots fill it in."""
    return bool(request.form.get('hp_website'))

# ---------------- log redaction ----------------
import logging
class RedactFilter(logging.Filter):
    """Keep personal data and secrets out of server logs (DPDP: data minimisation; also limits breach impact)."""
    PATTERNS = [(re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '[email]'), (re.compile(r'(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)'), '[phone]'),
                (re.compile(r'(?i)(password|token|secret|otp|code|authorization)(["\'=:\s]+)[^\s&"\',]+'), r'\1\2[redacted]'),
                (re.compile(r'\b\d{4}\s?\d{4}\s?\d{4}\b'), '[id-number]'), (re.compile(r'\b[A-Z]{5}\d{4}[A-Z]\b'), '[pan]')]
    def filter(self, record):
        try:
            msg = record.getMessage()
            for rx, sub in self.PATTERNS: msg = rx.sub(sub, msg)
            record.msg, record.args = msg, ()
        except Exception:
            pass
        return True
