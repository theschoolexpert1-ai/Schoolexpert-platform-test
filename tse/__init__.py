"""The School Expert™ — integrated K-12 education ecosystem platform."""
import os, logging, datetime, json, re
from flask import Flask, g, request, render_template, session, send_from_directory, abort, url_for
from markupsafe import Markup, escape
from .config import Config
from .db import db
from .lib import security, auth
from .lib.payments import inr

def create_app(config=None):
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config.from_object(Config)
    if config: app.config.update(config)
    if app.config['ENV'] in ('production', 'staging'):
        problems = []
        if app.config['SECRET_KEY'].startswith('dev-') or len(app.config['SECRET_KEY']) < 32: problems.append('SECRET_KEY (32+ random characters)')
        if not (app.config.get('FIELD_ENCRYPTION_KEYS') or app.config.get('FIELD_ENCRYPTION_KEY')): problems.append('FIELD_ENCRYPTION_KEYS')
        if not app.config['SESSION_COOKIE_SECURE']: problems.append('SESSION_COOKIE_SECURE=true')
        if app.config.get('PAYMENT_GATEWAY') == 'mock' and app.config['ENV'] == 'production': problems.append('PAYMENT_GATEWAY=razorpay')
        if 'sslmode=require' not in app.config['DATABASE_URL'] and '127.0.0.1' not in app.config['DATABASE_URL'] and 'localhost' not in app.config['DATABASE_URL'] and '/var/run' not in app.config['DATABASE_URL']:
            problems.append('DATABASE_URL with sslmode=require for a remote database')
        if problems: raise RuntimeError(f"Refusing to start in {app.config['ENV']} — set: " + ', '.join(problems))
    logging.basicConfig(level=logging.INFO)
    db.init(app.config['DATABASE_URL'], app.config['DB_POOL_SIZE'])
    app.session_interface = security.PgSessionInterface()
    from werkzeug.middleware.proxy_fix import ProxyFix   # trust X-Forwarded-* only from our own reverse proxy (nginx)
    if app.config['TRUSTED_PROXIES']:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=app.config['TRUSTED_PROXIES'], x_proto=1, x_host=1)
    if app.config['STORAGE_BACKEND'] == 'local':
        for d in (app.config['UPLOAD_DIR'], app.config['PRIVATE_UPLOAD_DIR']): os.makedirs(d, exist_ok=True)

    def _db_ctx():
        """Row-level-security context for every SQL statement in this request (see migrations/004_security.sql)."""
        from flask import has_request_context
        if not has_request_context() or getattr(g, 'db_bypass', False): return ('on', '', '')
        u = getattr(g, 'user', None)
        if not u: return ('off', '', '')
        if u['account_type'] in ('admin', 'staff'): return ('on', str(u['id']), '')
        return ('off', str(u['id']), ','.join(str(o['id']) for o in (getattr(g, 'orgs', None) or [])))
    db.set_context_provider(_db_ctx)
    import logging as _logging
    for _name in (None, 'werkzeug', 'gunicorn.access', 'gunicorn.error'):
        _lg = _logging.getLogger(_name)
        if not any(isinstance(f, security.RedactFilter) for f in _lg.filters): _lg.addFilter(security.RedactFilter())
    for _h in _logging.getLogger().handlers: _h.addFilter(security.RedactFilter())

    @app.before_request
    def _before():
        g.now = datetime.datetime.now(datetime.timezone.utc)
        import secrets as _secrets; g.csp_nonce = _secrets.token_urlsafe(16)
        if request.endpoint in ('static', 'public.media'): return
        gate = _staging_gate()
        if gate is not None: return gate
        auth.load_user()
        _session_policies()
        if not request.path.startswith('/api/'):   # API ignores cookies (bearer tokens only) -> no CSRF surface
            security.csrf_protect()
        _capture_attribution()

    def _staging_gate():
        """Optional team password for the shared prototype (STAGING_BASIC_AUTH="user:password")."""
        cred = app.config.get('STAGING_BASIC_AUTH')
        if not cred or request.path.startswith(('/webhooks/', '/cron/', '/healthz', '/api/')): return None
        a = request.authorization
        import hmac as _h
        if a and a.type == 'basic' and _h.compare_digest(f'{a.username}:{a.password}', cred): return None
        from flask import Response as _R
        return _R('The School Expert™ prototype — team access only.', 401, {'WWW-Authenticate': 'Basic realm="The School Expert prototype"'})

    MFA_SETUP_OK = {'auth.security', 'auth.logout', 'auth.mfa_verify', 'public.page', 'static'}
    def _session_policies():
        """Idle time-outs (staff 30 min, others 3 days) and mandatory two-step verification for staff."""
        import time
        if not getattr(g, 'user', None) or getattr(g, 'api_token_id', None): return
        staff = g.user['account_type'] in ('admin', 'staff')
        now = int(time.time()); seen = session.get('seen') or now
        limit = app.config['IDLE_MINUTES_STAFF'] * 60 if staff else app.config['IDLE_HOURS_USER'] * 3600
        if now - seen > limit:
            security.audit('auth.idle_timeout', 'user', g.user['id'], actor_id=g.user['id'])
            session.clear(); session.modified = True; g.user = None; g.org = None; g.orgs = []
            from flask import flash; flash('You were signed out after a period of inactivity.', 'info')
            return
        if now - seen > 60: session['seen'] = now
        if staff and app.config['MFA_REQUIRED_FOR_STAFF'] and not g.user['mfa_enabled'] and request.endpoint not in MFA_SETUP_OK:
            from flask import redirect as _r
            g._force_redirect = _r(url_for('auth.security'))

    @app.before_request
    def _enforce_mfa_setup():
        r = getattr(g, '_force_redirect', None)
        if r is not None: return r

    ATTR_KEYS = ('utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content', 'gclid', 'fbclid', 'msclkid')
    def _capture_attribution():
        """SEM/SEO attribution without a server session per visitor (scales to bot/crawler traffic):
        first-touch UTM / click ids / landing page and the ?ref= referral code live in a small signed cookie and are
        copied onto users, organisations and orders at conversion. No personal data is stored in it."""
        from itsdangerous import URLSafeSerializer, BadSignature
        ser = URLSafeSerializer(app.secret_key, salt='attr')
        try: g.attrib = ser.loads(request.cookies.get('tse_attr', '')) if request.cookies.get('tse_attr') else {}
        except BadSignature: g.attrib = {}
        g._attr_dirty = False
        if request.method != 'GET' or not request.endpoint or request.path.startswith(('/api/', '/static', '/media')): return
        a = request.args
        if a.get('ref') and re.fullmatch(r'[A-Za-z0-9_-]{3,40}', a['ref']) and g.attrib.get('ref') != a['ref']:
            g.attrib['ref'] = a['ref']; g._attr_dirty = True
        if not g.attrib.get('src'):
            got = {k: a[k][:120] for k in ATTR_KEYS if a.get(k)}
            ref = request.referrer or ''
            if not got and ref and not ref.startswith(app.config.get('SITE_URL', '~')):
                host = re.sub(r'^https?://([^/]+).*$', r'\1', ref)[:80]
                got = {'utm_source': host, 'utm_medium': 'organic' if any(x in host for x in ('google.', 'bing.', 'duckduckgo.', 'yahoo.')) else 'referral'}
            got = got or {'utm_source': '(direct)', 'utm_medium': '(none)'}
            got['landing'] = request.path[:200]; got['at'] = datetime.date.today().isoformat()
            g.attrib['src'] = got; g._attr_dirty = True
        g._attr_ser = ser

    @app.after_request
    def _headers(resp):
        if getattr(g, '_attr_dirty', False):
            resp.set_cookie('tse_attr', g._attr_ser.dumps(g.attrib), max_age=60 * 60 * 24 * 90, httponly=True, samesite='Lax',
                            secure=app.config['SESSION_COOKIE_SECURE'])
        resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
        if app.config['ENV'] == 'staging': resp.headers['X-Robots-Tag'] = 'noindex, nofollow'   # keep the prototype out of Google
        embeddable = getattr(g, 'embeddable', False)
        if not embeddable: resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
        resp.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin-allow-popups')     # Razorpay checkout opens a popup
        resp.headers.setdefault('Cross-Origin-Resource-Policy', 'same-site' if not request.path.startswith(('/widget.js', '/embed/', '/static/')) else 'cross-origin')
        resp.headers.setdefault('X-Permitted-Cross-Domain-Policies', 'none')
        if getattr(g, 'user', None) and 'Cache-Control' not in resp.headers:
            resp.headers['Cache-Control'] = 'private, no-store'     # personal pages never cached by browsers/proxies
        resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
        resp.headers.setdefault('Permissions-Policy', 'geolocation=(), camera=(), microphone=()')
        if app.config['SESSION_COOKIE_SECURE']:
            resp.headers.setdefault('Strict-Transport-Security', 'max-age=63072000; includeSubDomains; preload')
        resp.headers.setdefault('Content-Security-Policy',
            "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'nonce-" + getattr(g, 'csp_nonce', 'none') + "' https://checkout.razorpay.com https://www.googletagmanager.com https://connect.facebook.net; "
            "frame-src https://api.razorpay.com https://checkout.razorpay.com https://www.youtube-nocookie.com https://www.youtube.com https://open.spotify.com https://www.google.com; "
            "connect-src 'self' https://lumberjack.razorpay.com https://www.google-analytics.com https://*.analytics.google.com; "
            "font-src 'self' data:; frame-ancestors " + (app.config['EMBED_FRAME_ANCESTORS'] if embeddable else "'self'") +
            "; form-action 'self' https://api.razorpay.com")
        return resp

    @app.context_processor
    def _ctx():
        unread = 0; cart = 0
        if getattr(g, 'user', None):
            unread = db.val('SELECT count(*) FROM notifications WHERE user_id = %s AND read_at IS NULL', g.user['id'])
            cart = db.val('SELECT COALESCE(sum(qty),0) FROM cart_items WHERE user_id = %s', g.user['id'])
        return dict(csrf_token=security.csrf_token, current_user=getattr(g, 'user', None), current_org=getattr(g, 'org', None),
                    user_orgs=getattr(g, 'orgs', []), cfg=app.config, unread_count=unread, cart_count=cart, inr=inr,
                    is_staff=auth.is_staff(), csp_nonce=getattr(g, 'csp_nonce', ''), cookie_choice=request.cookies.get('tse_cookie_consent'), now=g.get('now'))

    from .lib import entitlements as _E, ads as _ads
    app.jinja_env.globals.update(csp_nonce_fn=lambda: getattr(g, 'csp_nonce', ''), csrf_token=security.csrf_token, inr=inr, today=lambda: datetime.date.today(), compare=_E.comparison,
                                 tier_label=_E.tier_label, feature_labels=_E.FEATURE_LABELS, ads=_ads.pick, pop_conversions=security.pop_conversions,
                                 footer_pages=lambda: db.all("SELECT title, path FROM pages WHERE show_in_footer AND path IS NOT NULL ORDER BY title LIMIT 8"))

    @app.template_filter('dt')
    def _dt(v, fmt='%d %b %Y'):
        if not v: return ''
        if isinstance(v, str): return v
        if isinstance(v, datetime.datetime):
            v = v.astimezone(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
        return v.strftime(fmt)
    @app.template_filter('dtt')
    def _dtt(v): return _dt(v, '%d %b %Y, %I:%M %p IST')
    @app.template_filter('nl2br')
    def _nl2br(v): return Markup('<br>'.join(escape(v or '').split('\n')))
    @app.template_filter('md')
    def _md(v):
        import markdown
        from .lib.html import clean
        return Markup(clean(markdown.markdown(v or '', extensions=['extra', 'sane_lists'])))
    @app.template_filter('initials')
    def _initials(v): return ''.join(w[0] for w in (v or '?').split()[:2]).upper()
    @app.template_filter('stars')
    def _stars(v):
        v = float(v or 0); full = int(round(v))
        return Markup('<span class="stars" aria-label="%.1f out of 5">%s%s</span>' % (v, '★' * full, '<span class="off">' + '★' * (5 - full) + '</span>'))
    @app.template_filter('json')
    def _json(v): return Markup(json.dumps(v, default=str))

    from .routes import public, auth as auth_routes, directory, register, dashboard, teachers, community, ask, marketplace, events, content, pay, privacy, admin, school_match, growth, api, cron, hub
    for m in (public, auth_routes, directory, register, dashboard, teachers, community, ask, marketplace, events, content, pay, privacy, admin, school_match, growth, api, cron, hub):
        app.register_blueprint(m.bp)

    @app.errorhandler(400)
    @app.errorhandler(401)
    @app.errorhandler(403)
    @app.errorhandler(405)
    @app.errorhandler(404)
    @app.errorhandler(413)
    @app.errorhandler(429)
    def _err(e):
        code = getattr(e, 'code', 500)
        if code == 404 and request.method == 'GET' and not request.path.startswith(('/api/', '/static/', '/admin', '/dashboard')):
            try:
                hit = growth.legacy_fallback(request.path)
                if hit is not None: return hit
            except Exception:
                app.logger.exception('legacy fallback failed')
        if request.path.startswith('/api/'):
            return {'error': getattr(e, 'description', 'error'), 'status': code}, code
        msgs = {403: 'You do not have access to this page.', 404: 'We could not find that page.', 413: 'That upload is too large.',
                429: 'Too many attempts. Please wait a minute and try again.'}
        return render_template('error.html', code=code, message=msgs.get(code) or getattr(e, 'description', 'Something went wrong.')), code

    @app.errorhandler(500)
    def _500(e):
        return render_template('error.html', code=500, message='Something went wrong on our side. Our team has been notified.'), 500

    from . import cli; cli.register(app)
    return app
