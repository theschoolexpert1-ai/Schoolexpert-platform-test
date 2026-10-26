"""Crawl every route as guest, parent, teacher, school, partner and admin; report non-2xx/3xx responses."""
import re, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tse import create_app
from tse.db import db

app = create_app({'TESTING': True})
app.logger.setLevel('ERROR')
BAD = []

def csrf(c):
    with c.session_transaction() as s:
        if '_csrf' not in s: s['_csrf'] = 'test-token'
        return s['_csrf']

def login(c, email):
    c.get('/login'); tok = csrf(c)
    r = c.post('/login', data={'email': email, 'password': 'DemoPass#2026', '_csrf': tok})
    assert r.status_code in (302, 303), (email, r.status_code)

def crawl(c, who, urls):
    for u in urls:
        r = c.get(u)
        if r.status_code >= 400 and not (r.status_code in (403, 404) and u.endswith('#expected')):
            BAD.append((who, u, r.status_code, re.sub(r'\s+', ' ', r.get_data(as_text=True))[:200] if r.status_code >= 500 else ''))

with app.app_context():
    L = db.one("SELECT slug FROM listings WHERE is_published AND tier = 'detailed' AND category = 'school-registration' LIMIT 1")['slug']
    LB = db.one("SELECT slug FROM listings WHERE is_published AND tier = 'basic' LIMIT 1")['slug']
    J = db.one("SELECT slug, id FROM jobs LIMIT 1")
    E = db.one("SELECT slug, id FROM events WHERE form_slug = 'principal-roundtable-virtual'")
    E2 = db.one("SELECT slug FROM events WHERE kind = 'storytelling' LIMIT 1")['slug']
    P = db.one("SELECT slug FROM podcasts LIMIT 1")['slug']
    PR = db.one("SELECT slug FROM products LIMIT 1")['slug']
    B = db.one("SELECT slug FROM books LIMIT 1")['slug']
    NL = db.one("SELECT slug FROM newsletters WHERE kind = 'newsworms' AND access = 'subscriber' LIMIT 1")['slug']
    POST = db.one("SELECT id FROM posts WHERE community = 'teachers' LIMIT 1")['id']
    CORNER = db.one("SELECT id FROM corner_submissions LIMIT 1")['id']
    REG = db.one("SELECT id FROM registrations WHERE form_slug = 'school-registration' LIMIT 1")['id']
    cats = [r['slug'] for r in db.all('SELECT slug FROM categories')]
    LID = db.val("SELECT id FROM listings WHERE slug = %s", L)

PUBLIC = ['/', '/search?q=school&city=Bengaluru', '/faq', '/contact', '/initiatives', '/for-schools', '/for-partners', '/founding-partners', '/revenue-streams',
          '/privacy-policy', '/terms', '/refund-policy', '/shipping-policy', '/cookie-policy', '/disclaimer', '/community-guidelines', '/about', '/p/about',
          '/robots.txt', '/sitemap.xml', '/directory/schools', '/directory/learning', '/directory/vendors', '/directory/experts',
          f'/l/{L}', f'/l/{LB}', '/ask', '/ask/schools', '/ask/schools?city=Bengaluru', '/personal-assistance', '/teachers', '/jobs', '/jobs?city=Bengaluru',
          f'/jobs/{J["slug"]}', '/teachers/meera-iyer-demo', '/community', '/community/teachers', f'/community/teachers/{POST}', '/community/parents',
          '/parents-corner', f'/parents-corner/{CORNER}', '/marketplace', '/marketplace?cat=Books', f'/marketplace/p/{PR}', '/events', '/events?when=past',
          f'/events/{E["slug"]}', f'/events/{E2}', '/podcasts', f'/podcasts/{P}', '/gallery', '/gallery/leadership-summit-2025-demo', '/newsletter',
          '/newsletter/industry-issue-1-demo', f'/newsletter/{NL}', '/newsworms', '/bookclub', f'/bookclub/{B}', '/homeschoolers-hub', '/resources',
          '/privacy-centre', '/cookie-settings', '/register', '/pricing', '/pricing?for=vendor', '/school-match', '/list-your-school', '/list-your-school/mysuru',
          '/become-a-vendor', '/become-a-vendor/uniform-vendor', '/schools/bengaluru', '/schools/chennai?board=CBSE', '/for-teachers', '/teacher-jobs/bengaluru',
          '/guides', '/guides/cbse-icse-state-ib-igcse', '/guides?for=schools', '/manifest.webmanifest', '/sw.js', '/offline', '/widget.js', '/embed/school-search',
          '/sitemaps/core-0.xml', '/sitemaps/listings-0.xml', '/sitemaps/content-0.xml', '/api/v1/listings', '/api/v1/plans', '/api/v1/jobs'] + [f'/register/{c}' for c in cats] + [f'/c/{c}' for c in cats]
COMMON = ['/dashboard/', '/dashboard/notifications', '/dashboard/orders', '/dashboard/subscriptions', '/dashboard/events', '/dashboard/settings', '/dashboard/support', '/privacy-centre', '/privacy-centre/export', '/cart']

c = app.test_client(); crawl(c, 'guest', PUBLIC)
for who, email, extra in [
    ('parent', 'parent@demo.schoolexpert.in', ['/shortlist', '/dashboard/referrals', '/dashboard/requests', '/dashboard/personal-assistance', '/parents-corner/submit']),
    ('teacher', 'teacher@demo.schoolexpert.in', ['/dashboard/applications', '/teachers/cv']),
    ('school', 'school0@demo.schoolexpert.in', ['/dashboard/promote', '/dashboard/referrals', '/dashboard/profile', '/dashboard/leads', '/dashboard/reviews', '/dashboard/plans', '/dashboard/jobs', '/dashboard/jobs/new',
        f'/dashboard/jobs/{J["id"]}', '/dashboard/team', '/dashboard/products', '/dashboard/sales', f'/dashboard/media/{LID}', '/teachers/directory', f'/register/r/{REG}/0', f'/register/r/{REG}/3', f'/register/r/{REG}/review']),
    ('partner', 'partner0@demo.schoolexpert.in', ['/dashboard/profile', '/dashboard/products', '/dashboard/products/new', '/dashboard/plans', '/dashboard/leads']),
    ('admin', 'admin@demo.schoolexpert.in', ['/admin/', '/admin/registrations', f'/admin/registrations/{REG}', '/admin/registrations?export=csv', '/admin/listings', '/admin/users',
        '/admin/organisations', '/admin/orders', '/admin/revenue', '/admin/leads', '/admin/expert-requests', '/admin/pa', '/admin/moderation', f'/admin/events/{E["id"]}',
        '/admin/cms', '/admin/forms', '/admin/forms/school-registration/preview', '/admin/forms/k12-curriculum-development-expert-registration/preview', '/admin/forms/school-registration.json',
        '/admin/dsr', '/admin/audit', '/admin/outbox', '/admin/contact', '/admin/tickets'] + [f'/admin/cms/{t}' for t in ['events','podcasts','gallery_albums','newsletters','resources','books','products','initiatives','faqs','pages','plans','pa_services','pa_cities','communities','ad_placements','referral_codes','breach_incidents']]
        + ['/admin/subscriptions', '/admin/payouts', '/admin/growth', '/admin/growth/utm', '/admin/site', '/admin/health', '/admin/events-desk', '/admin/cms/articles']
        + [f'/admin/cms/{t}/new' for t in ['events','products','plans','breach_incidents','articles','ad_placements']] + ['/admin/cms/pages/privacy-policy', '/admin/cms/plans/school_plus'] + [f'/admin/forms/{c}/preview' for c in cats]),
]:
    c = app.test_client(); login(c, email); crawl(c, who, COMMON + extra + PUBLIC[:12])

for b in BAD: print('BAD', b)
print('checked; failures:', len(BAD))
