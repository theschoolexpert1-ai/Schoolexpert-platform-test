"""REST API v1 — used by the mobile app (Capacitor / native) and future integrations.

Auth: POST /api/v1/auth/token {email, password} -> {token}. Send `Authorization: Bearer <token>`; organisation users may
send `X-Org-Id` to choose the active organisation. Bearer requests are CSRF-exempt; cookie requests are not.
Responses are JSON; lists are paginated with ?page=&per= (max 50). Payment-gated rules are the same as the website.
"""
import datetime, hashlib, secrets
from flask import Blueprint, request, g, abort, current_app, jsonify
from ..db import db
from ..lib import listings as L, entitlements as E, match as M
from ..lib.security import verify_password, limited, audit, attribution

bp = Blueprint('api', __name__, url_prefix='/api/v1')

def _need_user():
    if not g.user: abort(401, 'Authentication required')

def _page():
    page = max(1, request.args.get('page', 1, type=int)); per = max(1, min(50, request.args.get('per', 20, type=int)))
    return page, per

def _listing_public(l):
    return {k: l.get(k) for k in ('slug', 'name', 'headline', 'city', 'state', 'logo_url', 'boards', 'verified', 'category', 'category_label')} | {
        'rating': float(l['rating_avg'] or 0), 'reviews': l['rating_count'], 'featured': bool(l.get('featured_until') and l['featured_until'] >= datetime.date.today()),
        'url': f"{current_app.config['SITE_URL']}/l/{l['slug']}"}

@bp.after_request
def _no_store(resp):
    resp.headers['Cache-Control'] = 'no-store'
    return resp

@bp.route('/auth/token', methods=['POST'])
@limited(10, 300, 'api_login')
def token():
    d = request.get_json(silent=True) or {}
    u = db.one("SELECT * FROM users WHERE email = %s AND status = 'active'", (d.get('email') or '').strip().lower())
    if not u or not verify_password(u['password_hash'], d.get('password') or ''):
        audit('api.login_failed', 'user', u['id'] if u else None); abort(401, 'Invalid email or password')
    raw = secrets.token_urlsafe(32)
    db.insert('api_tokens', dict(user_id=u['id'], token_hash=hashlib.sha256(raw.encode()).hexdigest(), device=(d.get('device') or request.user_agent.string)[:120],
              expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=current_app.config['API_TOKEN_DAYS'])), returning=None)
    audit('api.token_issued', 'user', u['id'], actor_id=u['id'])
    return {'token': raw, 'token_type': 'Bearer', 'expires_in_days': current_app.config['API_TOKEN_DAYS']}

@bp.route('/auth/token', methods=['DELETE'])
def revoke():
    _need_user()
    if getattr(g, 'api_token_id', None): db.run('DELETE FROM api_tokens WHERE id = %s', g.api_token_id)
    return {'ok': True}

@bp.route('/me')
def me():
    _need_user(); u = g.user
    out = {'id': u['id'], 'name': u['name'], 'email': u['email'], 'account_type': u['account_type'], 'city': u['city'],
           'organisations': [{'id': o['id'], 'name': o['name'], 'category': o['category']} for o in g.orgs]}
    if g.org:
        e = E.current()
        out['active_org'] = {'id': g.org['id'], 'name': g.org['name'], 'plan': e.get('plan_name'), 'level': e['level'], 'tier': E.tier_label(e['level']),
                             'ends_at': e.get('ends_at').isoformat() if e.get('ends_at') else None,
                             'features': {k: e.get(k) for k in E.FEATURE_LABELS}}
    return out

@bp.route('/listings')
def listings():
    page, per = _page(); a = request.args
    rows, total = L.search(grp=a.get('group') if a.get('group') in ('schools', 'learning', 'vendors') else 'schools', category=a.get('category') or None,
                           q=(a.get('q') or '')[:100] or None, city=a.get('city') or None, board=a.get('board') or None, limit=per, offset=(page - 1) * per)
    return {'items': [_listing_public(r) for r in rows], 'page': page, 'per': per, 'total': total}

@bp.route('/listings/<slug>')
def listing(slug):
    l = db.one("""SELECT l.*, c.label AS category_label, c.grp FROM listings l JOIN categories c ON c.slug = l.category WHERE l.slug = %s AND l.is_published""", slug) or abort(404)
    E.bump_stat(l['id'], 'views')
    out = _listing_public(l) | {'about': l['about'], 'public': l['public_data']}
    if L.can_view_detailed(g.user, l): out['detailed'] = l['detailed_data']
    else: out['detailed_locked'] = True
    return out

@bp.route('/school-match', methods=['POST'])
@limited(20, 600, 'api_match')
def school_match():
    from .school_match import _prefs
    from werkzeug.datastructures import MultiDict
    d = request.get_json(silent=True) or {}
    md = MultiDict([(k, v) for k, vals in d.items() for v in (vals if isinstance(vals, list) else [vals])])
    p = _prefs(md)
    if not p['city'] and not p['pincode']: abort(400, 'city or pincode is required')
    results, _ = M.run(p)
    summary, ai = M.ai_summary(p, results)
    sid = db.insert('school_match_sessions', dict(user_id=g.user['id'] if g.user else None, prefs=p, results=[{'id': r['id'], 'score': r['score']} for r in results],
                    summary=summary, ai_used=ai, attribution=attribution()), returning='public_id')
    for r in results[:10]: E.bump_stat(r['id'], 'match_appearances')
    unlocked = set()
    if g.user:
        unlocked = {x['listing_id'] for x in db.all('SELECT listing_id FROM unlocks WHERE user_id = %s', g.user['id'])}
    return {'id': str(sid), 'summary': summary, 'ai': ai, 'results': [
        {'slug': r['slug'], 'name': r['name'], 'city': r['city'], 'score': r['score'], 'verified': r['verified'], 'category': r['category_label'],
         'reasons': [x['text'] for x in r['reasons'] if not x['detail'] or r['id'] in unlocked],
         'locked_reasons': sum(1 for x in r['reasons'] if x['detail'] and r['id'] not in unlocked)} for r in results]}

@bp.route('/jobs')
def jobs():
    page, per = _page(); city = request.args.get('city')
    rows = db.all("""SELECT j.slug, j.title, j.city, j.employment_type, j.subjects, j.published_at, o.name AS school FROM jobs j JOIN organisations o ON o.id = j.org_id
                     WHERE j.status = 'published' AND (%s::text IS NULL OR lower(j.city) = lower(%s::text))
                     ORDER BY (j.featured_until >= current_date) DESC NULLS LAST, j.published_at DESC LIMIT %s OFFSET %s""", city, city, per, (page - 1) * per)
    return {'items': [dict(r, published_at=r['published_at'].isoformat() if r['published_at'] else None) for r in rows], 'page': page, 'per': per}

@bp.route('/plans')
def plans():
    fam = request.args.get('family') if request.args.get('family') in ('school', 'vendor', 'addon', 'parent', 'teacher') else None
    rows = db.all("SELECT code, family, level, name, description, price_paise, interval, features, badge, highlight FROM plans WHERE active AND (%s::text IS NULL OR family = %s::text) ORDER BY family, sort", fam, fam)
    return {'items': rows}

@bp.route('/notifications')
def notifications():
    _need_user()
    rows = db.all('SELECT id, title, body, link, read_at, created_at FROM notifications WHERE user_id = %s ORDER BY id DESC LIMIT 50', g.user['id'])
    return {'items': [dict(r, created_at=r['created_at'].isoformat(), read_at=r['read_at'].isoformat() if r['read_at'] else None) for r in rows]}

@bp.route('/dashboard')
def dashboard():
    """Organisation dashboard summary for the app (same pay-gating as the website)."""
    _need_user()
    if not g.org: abort(403, 'Organisation account required')
    e = E.current()
    if not e.get('dashboard'): return {'active': False, 'message': 'Activate a plan to unlock your dashboard.', 'upgrade': _quote()}, 402
    lids = [r['id'] for r in db.all('SELECT id FROM listings WHERE org_id = %s', g.org['id'])] or [0]
    s = db.one("""SELECT COALESCE(sum(views),0) views, COALESCE(sum(leads),0) leads, COALESCE(sum(unlocks),0) unlocks, COALESCE(sum(match_appearances),0) matches
                  FROM listing_stats WHERE listing_id = ANY(%s) AND day > current_date - 30""", lids)
    leads = db.all('SELECT id, name, status, source, created_at FROM leads WHERE org_id = %s ORDER BY id DESC LIMIT 20', g.org['id']) if e.get('leads') else []
    return {'active': True, 'plan': e.get('plan_name'), 'tier': E.tier_label(e['level']), 'last_30_days': s,
            'leads': [dict(l, created_at=l['created_at'].isoformat()) for l in leads], 'leads_locked': not e.get('leads'), 'upgrade': _quote()}

def _quote():
    q = E.upgrade_quote(g.org['id'])
    return {'plan': q['plan']['code'], 'name': q['plan']['name'], 'price_paise': q['price'], 'credit_paise': q['credit']} if q else None
