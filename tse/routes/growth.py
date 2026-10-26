"""SEO / SEM acquisition surfaces, legacy-site integration, PWA and embeddable widgets.

Audience landing pages (each targets the search intent of one audience and ends in a registration CTA):
  /list-your-school, /list-your-school/<city>      schools  -> school registration (School - Basic/Plus/Pro)
  /become-a-vendor, /become-a-vendor/<category>    vendors  -> vendor registration (Vendor - Basic/Plus/Pro)
  /schools/<city>                                   parents  -> AI School Match / unlock pack
  /teacher-jobs/<city>, /for-teachers               teachers -> free teacher registration
  /guides, /guides/<slug>                           content marketing (articles)
"""
import json, re
from flask import Blueprint, render_template, request, redirect, url_for, abort, Response, current_app, g, make_response
from ..db import db
from ..lib import listings as L, entitlements as E, match as M

bp = Blueprint('growth', __name__)

TOP_CITIES = ['Bengaluru', 'Mumbai', 'Delhi', 'Chennai', 'Hyderabad', 'Pune', 'Kolkata', 'Ahmedabad', 'Mysuru', 'Coimbatore', 'Kochi', 'Jaipur',
              'Lucknow', 'Chandigarh', 'Indore', 'Gurugram', 'Noida', 'Thane', 'Navi Mumbai', 'Mangaluru', 'Hubballi', 'Visakhapatnam', 'Bhubaneswar', 'Nagpur']
def city_slug(c): return re.sub(r'[^a-z0-9]+', '-', (c or '').lower()).strip('-')
def city_from_slug(s):
    for c in TOP_CITIES:
        if city_slug(c) == s: return c
    row = db.one("SELECT city FROM listings WHERE is_published AND lower(regexp_replace(city, '[^A-Za-z0-9]+', '-', 'g')) = %s LIMIT 1", s)
    return row['city'] if row else None

def _school_counts(city):
    return db.one(f"""SELECT count(*) total, count(*) FILTER (WHERE tier IN ('detailed','featured')) detailed, COALESCE(sum(rating_count),0) reviews
                      FROM listings WHERE is_published AND lower(city) = lower(%s) AND category IN ({','.join(['%s'] * len(M.SCHOOL_CATEGORIES))})""", city, *M.SCHOOL_CATEGORIES)

# ---------- schools (B2B) ----------
@bp.route('/list-your-school')
@bp.route('/list-your-school/<city>')
def list_school(city=None):
    c = city_from_slug(city) if city else None
    if city and not c: abort(404)
    tiers = db.all("SELECT * FROM plans WHERE active AND family = 'school' AND stream <> 'founding_partner' ORDER BY level")
    demand = db.val("SELECT count(*) FROM school_match_sessions WHERE created_at > now() - interval '90 days' AND (%s::text IS NULL OR lower(prefs->>'city') = lower(%s::text))", c, c)
    counts = _school_counts(c) if c else None
    return render_template('growth/list_school.html', city=c, tiers=tiers, demand=demand, counts=counts, cities=TOP_CITIES, city_slug=city_slug)

# ---------- vendors (B2B) ----------
@bp.route('/become-a-vendor')
@bp.route('/become-a-vendor/<cat>')
def become_vendor(cat=None):
    cats = db.all("SELECT * FROM categories WHERE grp IN ('vendors','learning','experts') AND listed ORDER BY grp, sort")
    c = next((x for x in cats if x['slug'] == cat), None) if cat else None
    if cat and not c: abort(404)
    tiers = db.all("SELECT * FROM plans WHERE active AND family = 'vendor' AND stream <> 'founding_partner' ORDER BY level")
    stats = dict(schools=db.val("SELECT count(*) FROM listings l JOIN categories c ON c.slug = l.category WHERE c.grp = 'schools' AND l.is_published"),
                 parents=db.val("SELECT count(*) FROM users WHERE account_type = 'parent'"),
                 products=db.val("SELECT count(*) FROM products WHERE status = 'published'"))
    return render_template('growth/become_vendor.html', cat=c, cats=cats, tiers=tiers, stats=stats)

# ---------- parents (B2C) ----------
@bp.route('/schools/<city>')
def schools_city(city):
    c = city_from_slug(city) or abort(404)
    board = request.args.get('board') if request.args.get('board') in M.BOARDS else None
    rows, total = L.search(grp='schools', city=c, board=board, limit=30, sort='rating')   # neutral order for SEO pages
    counts = _school_counts(c)
    boards = db.all(f"""SELECT unnest(boards) b, count(*) n FROM listings WHERE is_published AND lower(city) = lower(%s)
                        AND category IN ({','.join(['%s'] * len(M.SCHOOL_CATEGORIES))}) GROUP BY 1 ORDER BY n DESC""", c, *M.SCHOOL_CATEGORIES)
    return render_template('growth/schools_city.html', city=c, rows=rows, total=total, counts=counts, board=board, boards=boards,
                           cities=TOP_CITIES, city_slug=city_slug)

# ---------- teachers ----------
@bp.route('/for-teachers')
@bp.route('/teacher-jobs/<city>')
def teacher_jobs(city=None):
    c = city_from_slug(city) if city else None
    if city and not c: abort(404)
    jobs = db.all("""SELECT j.*, o.name AS org_name FROM jobs j JOIN organisations o ON o.id = j.org_id WHERE j.status = 'published'
                     AND (%s::text IS NULL OR lower(j.city) = lower(%s::text)) ORDER BY (j.featured_until >= current_date) DESC NULLS LAST, j.published_at DESC LIMIT 20""", c, c)
    return render_template('growth/teacher_jobs.html', city=c, jobs=jobs, cities=TOP_CITIES, city_slug=city_slug)

# ---------- guides (content marketing) ----------
@bp.route('/guides')
def guides():
    aud = request.args.get('for')
    rows = db.all("SELECT * FROM articles WHERE published_at <= now() AND (%s::text IS NULL OR audience = %s::text) ORDER BY published_at DESC LIMIT 60", aud, aud)
    return render_template('growth/guides.html', rows=rows, aud=aud)

@bp.route('/guides/<slug>')
def guide(slug):
    a = db.one('SELECT * FROM articles WHERE slug = %s AND published_at <= now()', slug) or abort(404)
    more = db.all('SELECT slug, title, summary FROM articles WHERE published_at <= now() AND audience = %s AND id <> %s ORDER BY published_at DESC LIMIT 4', a['audience'], a['id'])
    return render_template('growth/guide.html', a=a, more=more)

# ---------- legacy website integration ----------
def legacy_fallback(path):
    """Called from the 404 handler: serve CMS pages at their old www.schoolexpert.in paths, or follow the redirect map."""
    p = path.rstrip('/') or '/'
    page = db.one('SELECT * FROM pages WHERE path = %s OR path = %s', p, p + '/')
    if page: return render_template('public/page.html', page=page)
    r = db.one('SELECT * FROM redirects WHERE from_path = %s', p)
    if r:
        db.run('UPDATE redirects SET hits = hits + 1 WHERE from_path = %s', p)
        return redirect(r['to_url'], code=r['code'])
    return None

# ---------- PWA (installable mobile app) ----------
@bp.route('/manifest.webmanifest')
def manifest():
    m = {'name': 'The School Expert™', 'short_name': 'School Expert', 'description': 'Find verified schools, teachers, experts and education partners across India.',
         'start_url': '/?source=pwa', 'scope': '/', 'display': 'standalone', 'background_color': '#F5F7FC', 'theme_color': '#0B2A6B', 'lang': 'en-IN',
         'icons': [{'src': url_for('static', filename=f'img/icon-{s}.png'), 'sizes': f'{s}x{s}', 'type': 'image/png', 'purpose': 'any maskable'} for s in (192, 512)],
         'shortcuts': [{'name': 'AI School Match', 'url': '/school-match'}, {'name': 'Teaching jobs', 'url': '/jobs'}, {'name': 'Dashboard', 'url': '/dashboard/'}],
         'categories': ['education']}
    return Response(json.dumps(m), mimetype='application/manifest+json')

@bp.route('/sw.js')
def service_worker():
    resp = make_response(render_template('growth/sw.js', version=current_app.config.get('ASSET_VERSION', '4')))
    resp.headers['Content-Type'] = 'application/javascript'; resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp

@bp.route('/offline')
def offline():
    return render_template('growth/offline.html')

# ---------- embeddable widgets (for the existing site, partner sites, school websites) ----------
@bp.route('/widget.js')
def widget_js():
    resp = make_response(render_template('growth/widget.js', site=current_app.config['SITE_URL']))
    resp.headers['Content-Type'] = 'application/javascript'; resp.headers['Cache-Control'] = 'public, max-age=3600'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    return resp

@bp.route('/embed/<kind>')
def embed(kind):
    if kind not in ('school-search', 'school-match', 'school-card'): abort(404)
    listing = None
    if kind == 'school-card':
        listing = db.one('SELECT * FROM listings WHERE slug = %s AND is_published', request.args.get('slug', '')) or abort(404)
    g.embeddable = True   # after_request relaxes frame-ancestors for these public, read-only pages
    return render_template('growth/embed.html', kind=kind, l=listing, cities=TOP_CITIES, M=M)
