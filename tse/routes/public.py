import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_from_directory, current_app, Response, g
from ..db import db
from ..lib import listings as L, crm, notify
from ..lib.security import limited

bp = Blueprint('public', __name__)

@bp.route('/')
def home():
    counts = {r['grp']: r['n'] for r in db.all("""SELECT c.grp, count(*) n FROM listings l JOIN categories c ON c.slug = l.category
                                                  WHERE l.is_published GROUP BY c.grp""")}
    featured = db.all("""SELECT l.*, c.label AS category_label FROM listings l JOIN categories c ON c.slug = l.category
                         WHERE l.is_published ORDER BY (l.featured_until >= current_date) DESC NULLS LAST, l.rating_avg DESC, l.id DESC LIMIT 6""")
    events = db.all("SELECT * FROM events WHERE status = 'published' AND starts_at >= now() ORDER BY starts_at LIMIT 3")
    podcasts = db.all("SELECT * FROM podcasts WHERE status = 'published' ORDER BY published_at DESC NULLS LAST LIMIT 3")
    jobs = db.all("""SELECT j.*, o.name AS org_name FROM jobs j JOIN organisations o ON o.id = j.org_id
                     WHERE j.status = 'published' ORDER BY j.published_at DESC LIMIT 4""")
    initiatives = db.all('SELECT * FROM initiatives WHERE published ORDER BY sort LIMIT 6')
    cities = db.all("SELECT city, count(*) n FROM listings WHERE is_published AND city <> '' GROUP BY city ORDER BY n DESC LIMIT 12")
    return render_template('public/home.html', counts=counts, featured=featured, events=events, podcasts=podcasts, jobs=jobs,
                           initiatives=initiatives, cities=cities)

@bp.route('/search')
def search():
    q = request.args.get('q', '').strip()[:100]; city = request.args.get('city', '').strip()[:60]; grp = request.args.get('grp') or None
    page = max(1, request.args.get('page', 1, type=int))
    rows, total = ([], 0)
    if q or city or grp:
        rows, total = L.search(q=q or None, city=city or None, grp=grp, limit=24, offset=(page - 1) * 24)
    jobs = db.all("""SELECT j.*, o.name AS org_name FROM jobs j JOIN organisations o ON o.id = j.org_id WHERE j.status = 'published'
                     AND (j.title ILIKE %s OR %s = ANY(j.subjects)) ORDER BY j.published_at DESC LIMIT 5""", f'%{q}%', q) if q else []
    products = db.all("SELECT * FROM products WHERE status = 'published' AND title ILIKE %s LIMIT 6", f'%{q}%') if q else []
    cities = [r['city'] for r in db.all("SELECT DISTINCT city FROM listings WHERE is_published AND city <> '' ORDER BY city")]
    return render_template('public/search.html', q=q, city=city, grp=grp, rows=rows, total=total, page=page, jobs=jobs, products=products, cities=cities)

@bp.route('/faq')
def faq():
    rows = db.all('SELECT * FROM faqs ORDER BY sort')
    sections = {}
    for r in rows: sections.setdefault(r['section'], []).append(r)
    return render_template('public/faq.html', sections=sections, rows=rows)

@bp.route('/contact', methods=['GET', 'POST'])
@limited(5, 600, 'contact')
def contact():
    if request.method == 'POST':
        from ..lib.security import honeypot_tripped
        if honeypot_tripped(): abort(400)
        f = request.form
        if f.get('website'):  # honeypot
            return redirect(url_for('public.contact'))
        if not f.get('name') or not f.get('email') or not f.get('message') or not f.get('consent'):
            flash('Please fill in your name, email and message and accept the privacy notice.', 'error')
            return render_template('public/contact.html', form=f), 400
        mid = db.insert('contact_messages', dict(name=f['name'][:120], email=f['email'][:200], phone=f.get('phone', '')[:20],
                        topic=f.get('topic', '')[:60], message=f['message'][:4000]))
        crm.emit('contact.created', {'id': mid, 'name': f['name'], 'email': f['email'], 'phone': f.get('phone'), 'topic': f.get('topic'), 'message': f['message'][:1000]})
        notify.notify_staff('New contact message', f"{f['name']}: {f.get('topic')}", '/admin/contact')
        flash('Thank you — we have received your message and will respond soon.', 'success')
        return redirect(url_for('public.contact'))
    return render_template('public/contact.html', form={})

@bp.route('/initiatives')
def initiatives():
    rows = db.all('SELECT * FROM initiatives WHERE published ORDER BY sort')
    return render_template('public/initiatives.html', rows=rows)

def _tiers(fam):
    return db.all("SELECT * FROM plans WHERE active AND family = %s AND stream <> 'founding_partner' AND level IS NOT NULL ORDER BY level", fam)

@bp.route('/for-schools')
def for_schools():
    return render_template('public/for_schools.html', tiers=_tiers('school'))

@bp.route('/for-partners')
def for_partners():
    return render_template('public/for_partners.html', tiers=_tiers('vendor'))

@bp.route('/pricing')
def pricing():
    fam = request.args.get('for') if request.args.get('for') in ('school', 'vendor') else 'school'
    other = db.all("SELECT * FROM plans WHERE active AND family IN ('addon','parent','teacher') ORDER BY family, sort")
    founding = db.all("SELECT * FROM plans WHERE active AND stream = 'founding_partner' ORDER BY sort")
    return render_template('public/pricing.html', fam=fam, school=_tiers('school'), vendor=_tiers('vendor'), other=other, founding=founding)

@bp.route('/founding-partners')
def founding():
    faqs = db.all("SELECT * FROM faqs WHERE section = 'Founding Partner Programme' ORDER BY sort")
    return render_template('public/founding.html', plans=db.all("SELECT * FROM plans WHERE stream = 'founding_partner' AND active ORDER BY sort"), faqs=faqs)

@bp.route('/revenue-streams')
def streams():
    return render_template('public/streams.html')

@bp.route('/media/<path:path>')
def media(path):
    if current_app.config['STORAGE_BACKEND'] == 'local':
        return send_from_directory(current_app.config['UPLOAD_DIR'], path, max_age=60 * 60 * 24 * 30)
    from ..lib import storage
    import re as _re
    if not _re.fullmatch(r'[a-z_-]+/\d{4}/\d{2}/[0-9a-f]{32}\.[a-z0-9]{2,5}', path): abort(404)
    data, mime = storage.read_public(path)
    if data is None: abort(404)
    if mime in ('text/html', 'image/svg+xml', 'application/javascript', 'text/xml'): mime = 'application/octet-stream'
    return Response(data, mimetype=mime, headers={'Cache-Control': 'public, max-age=2592000, immutable', 'X-Content-Type-Options': 'nosniff',
                                                   'Content-Security-Policy': "default-src 'none'; img-src 'self'; media-src 'self'; sandbox"})

@bp.route('/robots.txt')
def robots():
    if current_app.config['ENV'] == 'staging':   # team prototype: never indexed
        return Response('User-agent: *\nDisallow: /\n', mimetype='text/plain')
    body = f"""User-agent: *
Disallow: /dashboard
Disallow: /admin
Disallow: /register/
Disallow: /pay/
Disallow: /cart
Disallow: /privacy-centre
Disallow: /school-match/r/
Disallow: /shortlist
Disallow: /compare
Disallow: /embed/
Disallow: /api/
Allow: /
Sitemap: {current_app.config['SITE_URL']}/sitemap.xml
"""
    return Response(body, mimetype='text/plain')

SITEMAP_PAGE = 20000   # well under the 50,000-URL limit per sitemap file

def _sitemap_urls(part, n):
    from .growth import TOP_CITIES, city_slug
    off = n * SITEMAP_PAGE
    if part == 'core':
        urls = ['/', '/search', '/faq', '/contact', '/initiatives', '/for-schools', '/for-partners', '/pricing', '/founding-partners', '/school-match',
                '/ask', '/ask/schools', '/personal-assistance', '/teachers', '/for-teachers', '/jobs', '/marketplace', '/events', '/podcasts', '/gallery',
                '/newsletter', '/newsworms', '/bookclub', '/homeschoolers-hub', '/resources', '/parents-corner', '/register', '/guides',
                '/list-your-school', '/become-a-vendor', '/directory/schools', '/directory/learning', '/directory/vendors']
        urls += [f'/schools/{city_slug(c)}' for c in TOP_CITIES] + [f'/list-your-school/{city_slug(c)}' for c in TOP_CITIES] + [f'/teacher-jobs/{city_slug(c)}' for c in TOP_CITIES]
        urls += [f'/become-a-vendor/{r["slug"]}' for r in db.all("SELECT slug FROM categories WHERE grp IN ('vendors','learning','experts') AND listed")]
        urls += [f'/c/{r["slug"]}' for r in db.all('SELECT slug FROM categories WHERE listed')]
        urls += [r['path'] or f'/p/{r["slug"]}' for r in db.all('SELECT slug, path FROM pages')]
        urls += [f'/guides/{r["slug"]}' for r in db.all('SELECT slug FROM articles WHERE published_at <= now()')]
        return urls
    q = {'listings': ("SELECT '/l/' || slug u FROM listings WHERE is_published ORDER BY id", None),
         'jobs': ("SELECT '/jobs/' || slug u FROM jobs WHERE status = 'published' ORDER BY id", None),
         'content': ("""SELECT '/events/' || slug u FROM events WHERE status IN ('published','completed') UNION ALL
                        SELECT '/podcasts/' || slug FROM podcasts WHERE status = 'published' UNION ALL
                        SELECT '/marketplace/p/' || slug FROM products WHERE status = 'published' UNION ALL
                        SELECT '/teachers/' || slug FROM teacher_profiles WHERE visibility = 'public' AND slug IS NOT NULL""", None)}
    sql = q[part][0]
    return [r['u'] for r in db.all(f'SELECT u FROM ({sql}) x LIMIT %s OFFSET %s', SITEMAP_PAGE, off)]

@bp.route('/sitemap.xml')
def sitemap():
    """Sitemap index — scales to millions of listings by splitting into numbered files."""
    base = current_app.config['SITE_URL']
    counts = {'core': 1, 'listings': db.val('SELECT count(*) FROM listings WHERE is_published'), 'jobs': db.val("SELECT count(*) FROM jobs WHERE status = 'published'"),
              'content': SITEMAP_PAGE}
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for part, n in counts.items():
        for i in range(max(1, -(-n // SITEMAP_PAGE))):
            xml.append(f'<sitemap><loc>{base}/sitemaps/{part}-{i}.xml</loc></sitemap>')
    xml.append('</sitemapindex>')
    return Response('\n'.join(xml), mimetype='application/xml', headers={'Cache-Control': 'public, max-age=3600'})

@bp.route('/sitemaps/<any("core","listings","jobs","content"):part>-<int:n>.xml')
def sitemap_part(part, n):
    base = current_app.config['SITE_URL']
    urls = _sitemap_urls(part, n)
    if not urls and n > 0: abort(404)
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    xml += [f'<url><loc>{base}{u}</loc></url>' for u in dict.fromkeys(urls)]
    xml.append('</urlset>')
    return Response('\n'.join(xml), mimetype='application/xml', headers={'Cache-Control': 'public, max-age=3600'})

@bp.route('/p/<slug>')
@bp.route('/<any("privacy-policy","terms","refund-policy","shipping-policy","cookie-policy","disclaimer","community-guidelines","about"):slug>')
def page(slug):
    p = db.one('SELECT * FROM pages WHERE slug = %s', slug) or abort(404)
    return render_template('public/page.html', p=p)


@bp.route('/go/ad/<int:ad_id>')
def ad_click(ad_id):
    ad = db.one('SELECT * FROM ad_placements WHERE id = %s', ad_id) or abort(404)
    db.run('UPDATE ad_placements SET clicks = clicks + 1 WHERE id = %s', ad_id)
    url = ad['link_url'] or '/'
    if not (url.startswith('/') and not url.startswith('//')) and not url.startswith('https://'): url = '/'
    return redirect(url)


@bp.route('/.well-known/security.txt')
def security_txt():
    """Responsible-disclosure contact (RFC 9116)."""
    exp = (datetime.date.today() + datetime.timedelta(days=365)).isoformat()
    body = (f"Contact: mailto:security@schoolexpert.in\nContact: mailto:info@schoolexpert.in\nExpires: {exp}T00:00:00Z\n"
            f"Preferred-Languages: en, hi, kn\nPolicy: {current_app.config['SITE_URL']}/p/security\nCanonical: {current_app.config['SITE_URL']}/.well-known/security.txt\n")
    return Response(body, mimetype='text/plain')

@bp.route('/healthz')
def healthz():
    """Liveness/readiness for the load balancer — reveals nothing beyond up/down."""
    try:
        db.val('SELECT 1'); return Response('ok', mimetype='text/plain')
    except Exception:
        return Response('db unavailable', status=503, mimetype='text/plain')
