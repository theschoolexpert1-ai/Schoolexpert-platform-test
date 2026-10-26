"""Idempotent seed: categories, forms, plans, communities, services, consent notices, CMS content; optional demo data."""
import os, json, glob, datetime, random
from . import db
from .content.faqs import FAQS
from .content.pages import PAGES

HERE = os.path.dirname(__file__)
FORMS_DIR = os.path.join(os.path.dirname(HERE), 'forms')

# access rules from the stakeholder journeys
ACCESS = {
  'schools':  dict(parent_access='browse', school_access='browse'),
  'vendors':  dict(parent_access='none',   school_access='browse'),
  'learning': dict(parent_access='browse', school_access='browse'),
  'experts':  dict(parent_access='ask',    school_access='ask'),
  'teachers': dict(parent_access='none',   school_access='browse', listed=False),
  'ambassadors': dict(parent_access='none', school_access='none', listed=False),
  'events':   dict(parent_access='none',   school_access='none', listed=False),
}
SPECIAL = {
  'teacher-training-institute-registration': dict(school_access='detailed_free'),
  'educational-consultant-registration': dict(parent_access='browse'),
  'fee-financing': dict(parent_access='ask', school_access='ask'),
}
GROUP_ORDER = {'schools': 10, 'learning': 30, 'experts': 40, 'vendors': 50, 'teachers': 60, 'ambassadors': 70, 'events': 80}

def upsert_form(d, bump=False):
    meta = {k: d.get(k) for k in ('category', 'label', 'entity')}
    acc = {'listed': True}; acc.update(ACCESS.get(meta['category'], {}))
    acc.update(SPECIAL.get(d['slug'], {}))
    db.run("""INSERT INTO categories (slug, grp, label, entity, parent_access, school_access, listed, sort)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
              ON CONFLICT (slug) DO UPDATE SET grp = EXCLUDED.grp, label = EXCLUDED.label, entity = EXCLUDED.entity,
                parent_access = EXCLUDED.parent_access, school_access = EXCLUDED.school_access, listed = EXCLUDED.listed""",
           d['slug'], meta['category'], meta['label'], meta['entity'], acc['parent_access'], acc['school_access'], acc['listed'],
           GROUP_ORDER.get(meta['category'], 90))
    body = {k: v for k, v in d.items() if k not in ('category', 'label', 'entity')}
    existing = db.one('SELECT version, definition FROM form_definitions WHERE slug = %s', d['slug'])
    if existing and existing['definition'] == body: return
    if existing:
        db.run('UPDATE form_definitions SET title = %s, definition = %s, provisional = %s, version = version + %s, updated_at = now() WHERE slug = %s',
               d['title'], db.Json(body), bool(d.get('provisional')), 1 if bump or existing else 0, d['slug'])
    else:
        db.insert('form_definitions', dict(slug=d['slug'], title=d['title'], definition=body, provisional=bool(d.get('provisional'))), returning=None)

P = lambda rupees: int(rupees * 100)
P = lambda rupees: int(rupees * 100)
U = None   # unlimited

def G(level, family, **kw):
    """Grants for a tier plan (see tse/lib/entitlements.py for every key)."""
    base = dict(level=level, published=True, dashboard=True, rank=level, tier={1: 'basic', 2: 'detailed', 3: 'featured'}[level])
    base.update(kw); return base

SCHOOL_BASIC = G(1, 'school', jobs_limit=2, photos_limit=5, analytics='basic', campuses_limit=1)
SCHOOL_PLUS = G(2, 'school', detailed_profile=True, leads=True, jobs_limit=U, photos_limit=30, directory_access=True, review_reply=True,
                analytics='standard', ai_match=True, lead_alerts=True, event_discount_pct=10, campuses_limit=1)
SCHOOL_PRO = G(3, 'school', detailed_profile=True, leads=True, jobs_limit=U, photos_limit=U, directory_access=True, review_reply=True,
               analytics='advanced', ai_match=True, lead_alerts=True, featured=True, teacher_search=True, featured_jobs=3, campuses_limit=U,
               newsletter_feature=True, podcast_feature=True, virtual_tour=True, account_manager=True, priority_support=True, event_discount_pct=25,
               ad_credit_days=30)
VENDOR_BASIC = G(1, 'vendor', jobs_limit=1, photos_limit=5, products_limit=5, commission_pct=15, analytics='basic')
VENDOR_PLUS = G(2, 'vendor', detailed_profile=True, leads=True, jobs_limit=5, photos_limit=30, products_limit=50, commission_pct=10,
                directory_access=True, review_reply=True, analytics='standard', lead_alerts=True, event_discount_pct=10, ai_match=True)
VENDOR_PRO = G(3, 'vendor', detailed_profile=True, leads=True, jobs_limit=U, photos_limit=U, products_limit=U, commission_pct=7,
               directory_access=True, review_reply=True, analytics='advanced', lead_alerts=True, featured=True, webinar_partner=True,
               newsletter_feature=True, podcast_feature=True, account_manager=True, priority_support=True, event_discount_pct=25,
               ad_credit_days=60, ai_match=True)

# code, family, level, stream, name, price, interval, grants, features, description, badge, highlight
PLANS = [
 ('school_basic', 'school', 1, 'school_subscription', 'School - Basic', P(4999), 'annual', SCHOOL_BASIC,
  ['Verified school listing on the directory', 'School Account Dashboard', 'Basic profile visible to all parents', 'Up to 2 active teacher job posts', '5 photos', 'Request event passes', 'Support tickets'],
  'Get verified and visible to parents across India.', 'Basic', None),
 ('school_plus', 'school', 2, 'school_subscription', 'School - Plus', P(11999), 'annual', SCHOOL_PLUS,
  ['Everything in Basic', 'Detailed verified profile (fees, facilities, admissions contacts)', 'Verified admission leads from parents who unlock you', 'Lead manager + instant alerts', 'Unlimited teacher job posts', 'Reply to verified reviews', 'Full profile in AI School Match', 'See detailed vendor & partner profiles', '30 photos & videos, 30-day analytics', '10% off events'],
  'Turn profile views into admission enquiries.', 'Plus', 'Most popular'),
 ('school_pro', 'school', 3, 'school_subscription', 'School - Pro', P(24999), 'annual', SCHOOL_PRO,
  ['Everything in Plus', 'Featured: top of your city & board searches and the homepage', 'Pro badge', 'Teacher directory for recruitment', '3 featured jobs every month', 'Unlimited photos, videos & virtual tour', 'Multiple campuses', 'Podcast / webinar & newsletter feature', '30 days of sponsored banners', 'Dedicated account manager & priority support', 'Advanced analytics', '25% off events'],
  'Maximum visibility for admission season.', 'Pro', 'Best visibility'),
 ('vendor_basic', 'vendor', 1, 'partner_membership', 'Vendor - Basic', P(5999), 'annual', VENDOR_BASIC,
  ['Verified listing on the partner directory', 'Vendor Dashboard', 'Basic profile visible to schools & parents', 'Sell up to 5 marketplace products (15% commission)', '5 photos', 'Support tickets'],
  'Get verified and discovered by schools.', 'Basic', None),
 ('vendor_plus', 'vendor', 2, 'partner_membership', 'Vendor - Plus', P(14999), 'annual', VENDOR_PLUS,
  ['Everything in Basic', 'Detailed verified profile', 'Verified enquiries & leads from schools and parents', 'Lead manager + instant alerts', 'Sell up to 50 products (10% commission)', 'See detailed school profiles', 'Reply to reviews', '30 photos & videos, 30-day analytics', '10% off events & sponsorships'],
  'Turn school visits into business.', 'Plus', 'Most popular'),
 ('vendor_pro', 'vendor', 3, 'partner_membership', 'Vendor - Pro', P(29999), 'annual', VENDOR_PRO,
  ['Everything in Plus', 'Featured placement in your category & city', 'Pro badge', 'Unlimited products (7% commission)', 'Webinar partner slot & podcast feature', 'Newsletter feature', '60 days of sponsored banners', 'Dedicated account manager & priority support', 'Advanced analytics', '25% off events & sponsorships'],
  'Lead your category across India.', 'Pro', 'Best visibility'),
 ('school_founding', 'school', 3, 'founding_partner', 'Founding Partner — School', P(35000), 'one_time', dict(SCHOOL_PRO, founding_partner=True, waiver_years=3),
  ['One-time registration fee', 'School - Pro benefits', 'Three-year waiver of annual renewal fees', 'Lifetime Founding Partner badge', 'Committee & council invitations', 'Priority access to events', 'Partner references and introductions'], 'Subject to acceptance and the agreed terms of association.', 'Founding Partner', None),
 ('partner_founding', 'vendor', 3, 'founding_partner', 'Founding Partner — Vendor', P(25000), 'one_time', dict(VENDOR_PRO, founding_partner=True, waiver_years=3),
  ['One-time registration fee', 'Vendor - Pro benefits', 'Three-year waiver of annual renewal fees', 'Lifetime Founding Partner badge', 'Committee & council invitations', 'Priority access to events', 'Enhanced visibility'], 'Exclusive category partnership on request — write to shalini@schoolexpert.in.', 'Founding Partner', None),
 ('teacher_premium', 'teacher', None, 'teacher_membership', 'Teacher Premium', P(499), 'annual', {'teacher_premium': True},
  ['Unlimited AI CV versions tailored to each job', 'Premium badge on applications', 'Early access to new jobs', 'Discounts on workshops & webinars'], 'The basic teacher profile, community and job applications are free.', None, None),
 ('school_recruiter', 'addon', None, 'recruitment', 'Recruitment Plus (add-on)', P(4999), 'annual', {'teacher_search': True},
  ['Search the verified teacher directory', 'Invite teachers to apply'], 'For School - Plus; included in School - Pro.', None, None),
 ('job_boost', 'addon', None, 'recruitment', 'Featured Job (30 days)', P(999), 'one_time', {'job_boost_days': 30}, ['Top of the jobs board for 30 days', 'Highlighted in the teacher newsletter'], '', None, None),
 ('parent_unlock_10', 'parent', None, 'verified_leads', 'Ask The School Expert — 10 Detailed Views', P(499), 'one_time', {'unlocks': 10, 'days': 90},
  ['Detailed verified profiles of up to 10 schools in your locality', 'Contact schools directly (verified enquiry)', 'Rate the schools you unlock (Verified Reviews)', 'Valid for 90 days'], '', None, None),
 ('newsworms_annual', 'parent', None, 'product_subscription', 'NewsWorms — Annual Subscription', P(999), 'annual', {'newsworms': True}, ['Fortnightly kids newspaper (PDF)', 'Age-banded editions', 'Puzzles, science, current affairs'], '', None, None),
 ('bookclub_annual', 'parent', None, 'product_subscription', 'EverHungry Bookworms — Family Membership', P(1499), 'annual', {'bookclub': True}, ['Discounted storytelling sessions', 'Monthly reading list by age', 'Members-only author meetups'], '', None, None),
 ('sponsored_placement', 'addon', None, 'featured_placement', 'Sponsored Banner (30 days)', P(4999), 'one_time', {'ad_days': 30}, ['Banner on directory, AI School Match, jobs or resources pages', 'City targeting', 'Click & impression reporting'], '', None, None),
]
LEGACY_PLANS = {'school_detailed': 'school_plus', 'school_featured': 'school_pro', 'partner_membership': 'vendor_plus', 'partner_featured': 'vendor_pro',
                'provider_listing': 'vendor_basic', 'professional_listing': 'vendor_basic'}

COMMUNITIES = [
 ('teachers', 'Teachers Community', 'Share lesson ideas, classroom strategies and professional growth. Readable by verified schools; only teachers post.', ['teacher', 'organisation', 'admin', 'staff'], ['teacher'], False, True, 10),
 ('parents', 'Parents Community', 'Parents helping parents — admissions, learning at home, wellbeing. Visible only to parents.', ['parent', 'admin', 'staff'], ['parent'], False, True, 20),
 ('homeschoolers', 'Homeschoolers Circle', 'For homeschooling families and educators: curriculum, resources and meetups.', ['parent', 'teacher', 'admin', 'staff'], ['parent', 'teacher'], False, True, 30),
 ('principals', 'Principals & School Leaders', 'A private circle for heads of school — the year-round home of Principal Roundtables India.', ['organisation', 'admin', 'staff'], ['organisation'], False, True, 40),
 ('special-education', 'Special Education Network', 'Special educators and inclusive-education practitioners.', ['teacher', 'admin', 'staff'], ['teacher'], False, True, 50),
]

PA_SERVICES = [
 ('standard', 'Standard coordination fee', 'One standard fee covering coordination with the school (always included).', P(999), 10),
 ('collect_form', 'Collect application form', 'We visit the school and collect the application form / prospectus.', P(499), 20),
 ('fill_form', 'Fill the application for you', 'We fill the application with the details you provide and share it for your approval.', P(399), 30),
 ('submit_form', 'Submit the application', 'We submit the completed application at the school and share the acknowledgement.', P(499), 40),
 ('fee_info', 'Fee information', 'We obtain fee information that is not available online.', P(299), 50),
 ('fee_coordination', 'Fee payment coordination', 'We coordinate the payment process — you pay the school directly online. We never pay on your behalf.', P(299), 60),
 ('collect_tc', 'Collect Transfer Certificate (TC)', 'We collect the TC on your behalf (authorisation letter required).', P(799), 70),
 ('post_back', 'Post documents to you', 'We courier documents to your address (courier charges at actuals).', P(249), 80),
]
PA_CITIES = [('Bengaluru', 'Karnataka', P(0), P(20)), ('Mysuru', 'Karnataka', P(150), P(20)), ('Chennai', 'Tamil Nadu', P(200), P(20)),
             ('Hyderabad', 'Telangana', P(200), P(20)), ('Pune', 'Maharashtra', P(200), P(20)), ('Mumbai', 'Maharashtra', P(300), P(25))]

NOTICES = {
 'account': ('Your account', 'We use your name, email and phone to create and secure your account, send service messages and let you use the platform.', 'Name, email, phone, city', 'Until you delete your account'),
 'registration': ('Registration & verification', 'We use the information in your registration form to verify you and create your listing. Private items (IDs, certificates, personal contacts, references) are encrypted and seen only by our verification team.', 'Registration form answers and documents', 'While registered; drafts are deleted after 12 months of inactivity'),
 'profile_listing': ('Publishing your profile', 'With your consent we publish the profile fields marked public, and — if you buy a detailed plan — the detailed fields, to parents and schools who are entitled to see them. Private fields are never published.', 'Public and detailed profile fields', 'While your listing is active'),
 'lead_sharing': ('Sharing your enquiry', 'When you contact a school or provider, we share your name, phone, email and message with that organisation only, so it can respond to you.', 'Name, phone, email, message', 'Kept by the organisation for up to 12 months'),
 'hub_directory': ('Educator directory (Teachers Hub)', 'If you switch this on, other signed-in teachers can find you in the Teachers Hub directory and send you a connection request. They see your name, city, designation, school, subjects, grades, board, years of experience and short bio — never your email or phone. Messages are possible only after you accept a request.', 'Name, city, designation, school, subjects, grades, board, experience, bio', 'Until you switch it off or delete your account'),
 'job_application': ('Job application', 'We share your teacher profile and CV with the school you apply to, for recruitment only.', 'Teacher profile, CV, cover letter', 'Until the vacancy closes + 12 months'),
 'personal_assistance': ('Personal Assistance', 'Our own staff use the school name, your contact details, the documents you authorise and your postal address to carry out the services you select. We never pay fees on your behalf.', 'Contact details, postal address, authorisation letters', 'Until service completion + 12 months'),
 'expert_request': ('Ask The School Expert', 'We use your question (and, only if you choose to share it, limited information about your child\'s need) to match you with an in-house expert or a referral partner.', 'Contact details and the details you provide', 'Until the request is closed + 12 months'),
 'marketing': ('Newsletters & updates', 'We send newsletters, event invitations and offers. You can unsubscribe any time.', 'Email, name, interests', 'Until you withdraw'),
 'analytics_cookies': ('Analytics & advertising cookies', 'With consent we load Google Analytics and advertising tags to measure usage and campaigns. Never used for children.', 'Device, pages viewed, approximate location', '14 months'),
 'guardian_student_ambassador': ('Parent / guardian consent', 'As parent or lawful guardian you allow us to process your child\'s Student Ambassador application only for the programme. We do not track, profile or show targeted advertising to children.', 'Student details, your details', 'Programme duration + 12 months'),
 'community': ('Community posts', 'Your display name and posts are visible to members of the community you post in.', 'Display name, posts, comments', 'Until you delete them or your account'),
 'school_match': ('AI School Match', 'We use the preferences you enter (city, area, PIN code, grade, board, budget band and priorities) to rank verified schools for you, and — if you are signed in — save your matches and shortlist. We never ask for your child\'s name, age or date of birth. Only school summaries, never your contact details, are sent to our AI provider.', 'Location, grade, board, budget band, priorities', '24 months, or until you delete them'),
 'ai_cv': ('AI CV builder', 'We send only your professional details (no phone, email, date of birth or address) to our AI provider to draft your CV. The draft is stored in your account.', 'Professional profile fields', 'Until you delete the CV or account'),
}

INITIATIVES = [
 ('newsworms', 'NewsWorms', 'The newspaper for curious kids', 'A fortnightly children\'s newspaper — current affairs, science, puzzles and stories written for young readers, in age-banded editions. Subscribed and downloaded by parents.', '/newsworms', 'Read NewsWorms', 'newspaper', 10),
 ('bookclub', 'The EverHungry Bookworms Bookclub', 'Reading clubs for every age', 'Book reviews and ratings by families, monthly reading lists, and live online storytelling sessions for children. Young authors can be published with The School Expert™.', '/bookclub', 'Join the Book Club', 'book', 20),
 ('homeschoolers-hub', 'Homeschoolers Hub', 'Support for homeschooling families', 'Meetups in cities across India, curated resources, learning apps (free and paid) and access to homeschooling experts.', '/homeschoolers-hub', 'Visit the Hub', 'home', 30),
 ('principal-roundtables', 'Principal Roundtables India', 'Peer conversations for school leaders', 'Candid virtual roundtables where principals and heads of school share challenges and solutions.', '/events?kind=roundtable', 'Register for a roundtable', 'roundtable', 40),
 ('parents-corner', "Parents' Corner", 'Craft projects & model-making tutorials', 'Parents share school craft projects and model-making tutorials for other parents to use.', '/parents-corner', "Open Parents' Corner", 'craft', 50),
 ('teachers-community', 'Teachers Community', 'A safe professional space for teachers', 'Profiles, AI-assisted CVs, school jobs and a moderated community to share what works.', '/teachers', 'For teachers', 'teacher', 60),
 ('parent-ambassadors', 'Parent Ambassador Programme', 'Parents know better. We help them choose the best.', 'A voluntary community role for parents who want to strengthen the ecosystem, with referral commissions for verified school sign-ups.', '/register/parent-ambassador', 'Become a Parent Ambassador', 'ambassador', 70),
 ('teacher-ambassadors', 'Teacher Ambassador Programme', 'Be the voice of teachers. Be part of the change.', 'For teachers who want to connect educators, share experiences, amplify teacher voices and lead conversations about education. Registration is free.', '/register/teacher-ambassador', 'Become a Teacher Ambassador', 'teacher', 75),
 ('student-ambassadors', 'Student Ambassador Programme', 'The student voice of The School Expert™', 'For students aged 14–18, with parent/guardian consent: share what works for students and volunteer at selected events.', '/register/student-ambassador', 'Apply with your parent', 'student', 80),
 ('founding-partners', 'Founding Partner Programme', 'Build India\'s education ecosystem with us', 'One-time registration fee, three-year renewal waiver, lifetime badge, committee invitations and priority event access.', '/founding-partners', 'Become a Founding Partner', 'badge', 90),
 ('podcasts-webinars', 'Podcasts & Webinars', 'Conversations with educators', 'Watch educators and experts, and leave your questions to be answered in future episodes.', '/podcasts', 'Watch & listen', 'mic', 100),
 ('industry-newsletter', 'The School Expert™ Industry Newsletter', 'For school leaders and education businesses', 'News, policy updates (NEP, CBSE, state boards), partner spotlights and opportunities.', '/newsletter', 'Subscribe', 'mail', 110),
]

def run(demo=False):
    with db.transaction():
        for p in sorted(glob.glob(os.path.join(FORMS_DIR, '*.json'))):
            if os.path.basename(p).startswith('_'): continue
            upsert_form(json.load(open(p, encoding='utf-8')))
        for i, (code, fam, level, stream, name, price, interval, grants, feats, desc, badge, hl) in enumerate(PLANS):
            aud = {'school': 'school', 'vendor': 'vendor', 'teacher': 'teacher', 'parent': 'parent'}.get(fam, 'school' if code.startswith('school') or code == 'job_boost' else 'vendor')
            db.run("""INSERT INTO plans (code, audience, family, level, stream, name, description, price_paise, interval, grants, features, sort, badge, highlight)
                      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
                      stream = EXCLUDED.stream, grants = EXCLUDED.grants, features = EXCLUDED.features, family = EXCLUDED.family, level = EXCLUDED.level,
                      badge = EXCLUDED.badge, highlight = EXCLUDED.highlight, audience = EXCLUDED.audience, sort = EXCLUDED.sort""",
                   code, aud, fam, level, stream, name, desc, price, interval, db.Json(grants), db.Json(feats), i, badge, hl)
        for old, new in LEGACY_PLANS.items():
            if db.val('SELECT 1 FROM plans WHERE code = %s', old):
                db.run('UPDATE subscriptions SET plan_code = %s WHERE plan_code = %s', new, old)
                db.run('UPDATE plans SET active = false, family = NULL WHERE code = %s', old)
        for slug, name, desc, view, post, pre, comments, sort in COMMUNITIES:
            db.run("""INSERT INTO communities (slug, name, description, view_roles, post_roles, premoderate, allow_comments, sort) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description, view_roles = EXCLUDED.view_roles, post_roles = EXCLUDED.post_roles""",
                   slug, name, desc, view, post, pre, comments, sort)
        from ..lib import hub
        hub.seed_content()          # Teachers Hub: courses, tutorials, subject communities
        for code, name, desc, price, sort in PA_SERVICES:
            db.run('INSERT INTO pa_services (code, name, description, price_paise, sort) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (code) DO NOTHING', code, name, desc, price, sort)
        for city, state, base, perkm in PA_CITIES:
            db.run('INSERT INTO pa_cities (city, state, base_paise, per_km_paise) VALUES (%s,%s,%s,%s) ON CONFLICT (city) DO NOTHING', city, state, base, perkm)
        for purpose, (title, body, items, ret) in NOTICES.items():
            db.run("""INSERT INTO consent_notices (purpose, version, lang, title, body, data_items, retention) VALUES (%s, 1, 'en', %s, %s, %s, %s)
                      ON CONFLICT (purpose, version, lang) DO NOTHING""", purpose, title, body, items, ret)
        if not db.val('SELECT count(*) FROM faqs'):
            for i, (sec, q, a) in enumerate(FAQS):
                db.insert('faqs', dict(section=sec, question=q, answer=a, sort=i), returning=None)
        pp = open(os.path.join(HERE, 'content', 'privacy-policy.md'), encoding='utf-8').read()
        db.run("INSERT INTO pages (slug, title, body, meta_description) VALUES ('privacy-policy', 'Privacy Policy', %s, %s) ON CONFLICT (slug) DO NOTHING",
               pp, 'How The School Expert™ collects, uses, shares and protects personal data, and your rights under Indian law.')
        for slug, (title, body) in PAGES.items():
            db.run('INSERT INTO pages (slug, title, body) VALUES (%s,%s,%s) ON CONFLICT (slug) DO NOTHING', slug, title, body.strip())
        for slug, title, tag, summ, url, cta, icon, sort in INITIATIVES:
            db.run("""INSERT INTO initiatives (slug, title, tagline, summary, cta_url, cta_label, icon, sort) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                      ON CONFLICT (slug) DO NOTHING""", slug, title, tag, summ, url, cta, icon, sort)
        db.run("""INSERT INTO settings (key, value) VALUES ('site', %s) ON CONFLICT (key) DO NOTHING""",
               db.Json({'announcement': 'Admissions 2027–28: Ask The School Expert for verified details of schools near you.', 'pa_enabled': True}))
        # SEO guides (content marketing) — editable in Admin → Content Studio → Guides
        import glob as _glob, re as _re
        for path in sorted(_glob.glob(os.path.join(HERE, "content", "guides", "*.md"))):
            raw = open(path, encoding='utf-8').read()
            m = _re.match(r'---\n(.*?)\n---\n(.*)', raw, _re.S)
            meta = dict(line.split(': ', 1) for line in m.group(1).splitlines() if ': ' in line)
            db.run("""INSERT INTO articles (slug, title, audience, summary, keywords, body, published_at) VALUES (%s,%s,%s,%s,%s,%s, now())
                      ON CONFLICT (slug) DO NOTHING""", os.path.basename(path)[:-3], meta['title'], meta.get('audience', 'parents'), meta.get('summary'),
                   meta.get('keywords'), m.group(2).strip())
        # Common URLs from the previous website, so old links and search results keep working (edit in Site Integration Desk)
        for src, dst in [('/about-us', '/p/about'), ('/contact-us', '/contact'), ('/home', '/'), ('/index.html', '/'), ('/registration', '/register'),
                         ('/register-now', '/register'), ('/faqs', '/faq'), ('/privacy', '/privacy-policy'), ('/terms-and-conditions', '/terms'),
                         ('/schools', '/directory/schools'), ('/vendors', '/directory/vendors'), ('/partners', '/for-partners'), ('/blog', '/guides')]:
            db.run('INSERT INTO redirects (from_path, to_url) VALUES (%s,%s) ON CONFLICT DO NOTHING', src, dst)
    if demo:
        from . import demo as d
        d.run()
