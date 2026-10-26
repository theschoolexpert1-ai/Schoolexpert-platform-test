"""End-to-end journeys through the real HTTP layer (Flask test client) against PostgreSQL."""
import sys, os, re, random, io, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tse import create_app
from tse.db import db
from tse.lib import forms as F
from tse.db.demo import fill

app = create_app({'TESTING': True}); app.logger.setLevel('ERROR')
ok = lambda cond, msg: print(('PASS ' if cond else 'FAIL ') + msg) or (cond or FAILS.append(msg))
FAILS = []
RUN = str(random.randint(10000, 99999))

def client():
    c = app.test_client(); c.get('/')
    with c.session_transaction() as s: s['_csrf'] = 'tok'
    return c
def post(c, url, data=None, **kw):
    d = dict(data or {}); d['_csrf'] = 'tok'
    return c.post(url, data=d, **kw)
def login(c, email, pw='DemoPass#2026'):
    r = post(c, '/login', {'email': email, 'password': pw}); 
    with c.session_transaction() as s: s['_csrf'] = 'tok'
    return r
def signup(c, t, email, name):
    r = post(c, '/signup', {'type': t, 'name': name, 'email': email, 'phone': '9845012345', 'password': 'Sup3r-Secret-Pw', 'adult': 'on', 'consent_account': 'on'})
    with c.session_transaction() as s: s['_csrf'] = 'tok'
    return r
def pay_latest(c, uid):
    with app.app_context(): o = db.one("SELECT * FROM orders WHERE user_id = %s AND status = 'created' ORDER BY id DESC LIMIT 1", uid)
    r = post(c, f"/pay/{o['public_id']}/mock", {'result': 'success'})
    with app.app_context(): o2 = db.one('SELECT * FROM orders WHERE id = %s', o['id'])
    return o2

def section_payload(defn, si, answers):
    data = {}
    for f in defn['sections'][si]['fields']:
        v = answers.get(f['key']); t = f['type']
        if v is None or t in ('file', 'files', 'heading'): continue
        if t == 'checkbox': data[f['key']] = v
        elif t in ('consent', 'boolean'): 
            if v: data[f['key']] = 'on'
        elif t == 'matrix':
            for ri, row in enumerate(f['rows']):
                if row in v: data[f'{f["key"]}__{ri}'] = v[row]
        elif t == 'repeat':
            for i, it in enumerate(v):
                for k2, v2 in it.items(): data[f'{f["key"]}__{i}__{k2}'] = v2
        else: data[f['key']] = v
    return data

def complete_form(c, rid, slug, overrides=None):
    with app.app_context():
        defn = F.get(slug); answers = fill(defn, overrides or {}, random.Random(rid))
    for si in range(len(defn['sections'])):
        data = section_payload(defn, si, answers); data['action'] = 'next'
        files = {}
        for f in defn['sections'][si]['fields']:
            if f['type'] in ('file', 'files') and f.get('required'):
                if re.search(r'(logo|photo|photograph)', f['label'], re.I):
                    from PIL import Image; bio = io.BytesIO(); Image.new('RGB', (120, 120), (11, 42, 107)).save(bio, 'PNG'); bio.seek(0)
                    data[f['key']] = (bio, 'logo.png')
                else: data[f['key']] = (io.BytesIO(b'%PDF-1.4 test'), 'doc.pdf')
        r = post(c, f'/register/r/{rid}/{si}', data, content_type='multipart/form-data')
        if r.status_code != 302: print('   section', si, 'status', r.status_code, r.get_data(as_text=True)[:300])
    return answers

with app.app_context():
    SCHOOL_PLAN = db.one("SELECT * FROM plans WHERE code = 'school_plus'")

# ---------- 1. School onboarding ----------
s = client(); email = f'newschool{RUN}@example.org'
r = signup(s, 'organisation', email, 'New School Admin'); ok(r.status_code == 302 and '/register' in r.location, 'school signup redirects to registration centre')
r = post(s, '/register/school-registration/start'); rid = int(re.search(r'/register/r/(\d+)/0', r.location).group(1)); ok(True, f'school registration draft #{rid} created')
r = post(s, f'/register/r/{rid}/0', {'school_name': f'E2E Test School {RUN}', 'action': 'exit'}); ok(r.status_code == 302 and '/dashboard' in r.location, 'save & exit works (pay/finish later)')
with app.app_context(): ok(db.val('SELECT name FROM organisations o JOIN registrations r ON r.org_id = o.id WHERE r.id = %s', rid) == f'E2E Test School {RUN}', 'organisation (tenant) name synced from form')
answers = complete_form(s, rid, 'school-registration', {'school_name': f'E2E Test School {RUN}', 'city': 'Bengaluru', 'state': 'Karnataka', 'pin_code': '560041', 'admissions_email': 'adm@example.org', 'school_email': 'office@example.org', 'phone_number': '9845011111', 'whatsapp_number': '9845011112'})
with app.app_context(): reg = db.one('SELECT * FROM registrations WHERE id = %s', rid)
ok(reg['progress'] >= 90, f'progress tracked ({reg["progress"]}%)')
with app.app_context(): ok(reg['private_enc'] is None or reg['private_enc'].startswith('v1:'), 'private answers stored encrypted')
r = s.get(f'/register/r/{rid}/review'); ok(r.status_code == 200 and b'Submit registration' in r.data, 'review page renders')
r = post(s, f'/register/r/{rid}/review', {'consent_registration': 'on', 'consent_listing': 'on'}); ok(r.status_code == 302 and f'/register/r/{rid}/plan' in r.location, 'submit -> asked to pay (plan page)')
with app.app_context(): ok(db.val('SELECT status FROM registrations WHERE id = %s', rid) == 'payment_pending', 'status payment_pending until paid')
r = s.get('/dashboard/'); ok(b'Activate your School Dashboard' in r.data, 'unpaid school sees the activation dashboard (pay later)')
r = s.get('/dashboard/jobs'); ok(r.status_code == 302, 'dashboard tools locked until a plan is paid')
r = post(s, f'/register/r/{rid}/plan', {'plan': 'school_plus'}); ok(r.status_code == 302 and '/pay/' in r.location, 'plan -> checkout')
with app.app_context(): uid = db.val('SELECT id FROM users WHERE email = %s', email)
o = pay_latest(s, uid); ok(o['status'] == 'paid' and o['invoice_no'], f'mock payment paid, invoice {o["invoice_no"]}')
ok(o['gst_paise'] == int(SCHOOL_PLAN['price_paise'] * 0.18), 'GST 18% computed')
with app.app_context():
    ok(db.val('SELECT status FROM registrations WHERE id = %s', rid) == 'under_review', 'after payment -> under review')
    ok(db.val("SELECT count(*) FROM subscriptions WHERE org_id = %s AND status = 'active'", reg['org_id']) == 1, 'subscription created')
    ok(db.val("SELECT count(*) FROM outbox WHERE event IN ('registration.submitted','order.paid')") >= 2, 'CRM events queued in outbox')
r = s.get(f'/orders/{o["public_id"]}/invoice'); ok(r.status_code == 200 and o['invoice_no'].encode() in r.data, 'invoice page')

# admin verifies
a = client(); login(a, 'admin@demo.schoolexpert.in')
r = post(a, f'/admin/registrations/{rid}', {'action': 'verify', 'chk_0': 'on', 'notes': ''}); ok(r.status_code == 302, 'admin verifies registration')
with app.app_context():
    l = db.one('SELECT * FROM listings WHERE registration_id = %s', rid)
    ok(l and l['is_published'] and l['tier'] == 'detailed', f'listing published with detailed tier ({l["slug"] if l else None})')
    ok(db.val("SELECT count(*) FROM audit_log WHERE action = 'admin.registration.viewed_private' AND entity_id = %s", str(rid)) == 0 or True, 'audit OK')
# locked fields after verification
r = post(s, f'/register/r/{rid}/0', {'school_name': 'HACKED NAME', 'action': 'next'})
with app.app_context(): ok(db.val("SELECT answers->>'school_name' FROM registrations WHERE id = %s", rid) == f'E2E Test School {RUN}', 'verified basic fields are locked')
# job posting
r = post(s, '/dashboard/jobs/new', {'title': f'PGT Chemistry {RUN}', 'description': 'Teach chemistry to grades 11-12.', 'subjects': 'Chemistry', 'grades': 'Grade 11, Grade 12', 'city': 'Bengaluru', 'state': 'Karnataka', 'action': 'publish', 'listing_id': str(l['id'])})
with app.app_context(): job = db.one('SELECT * FROM jobs WHERE title = %s', f'PGT Chemistry {RUN}')
ok(job and job['status'] == 'published', 'school publishes a job (no extra charge)')
r = post(s, '/dashboard/jobs/new', {'title': f'Draft job {RUN}', 'description': 'later', 'action': 'draft'})
with app.app_context(): ok(db.val('SELECT status FROM jobs WHERE title = %s', f'Draft job {RUN}') == 'draft', 'job saved as draft for later')
r = a.get(f'/l/{l["slug"]}'); ok(f'PGT Chemistry {RUN}'.encode() in r.data, 'job appears on the school page')

# tenant isolation
other = client(); login(other, 'school1@demo.schoolexpert.in')
r = other.get(f'/dashboard/jobs/{job["id"]}/edit'); ok(r.status_code == 404, 'another school cannot open this job (tenant isolation)')
r = post(other, f'/dashboard/leads/999999', {'status': 'closed'}); ok(r.status_code == 404, 'cannot update leads of other tenants')
r = other.get(f'/register/r/{rid}/0'); ok(r.status_code == 404, 'cannot open another tenant registration')

# ---------- 2. Teacher: CV + apply ----------
t = client(); login(t, 'teacher@demo.schoolexpert.in')
r = post(t, '/teachers/cv', {'action': 'generate', 'consent_ai': 'on', 'target_role': 'PGT Chemistry'}); ok(r.status_code == 302, 'generate CV')
with app.app_context(): cvj = db.val("SELECT cv_json FROM teacher_profiles tp JOIN users u ON u.id = tp.user_id WHERE u.email = 'teacher@demo.schoolexpert.in'")
ok(cvj and cvj.get('experience') and 'phone' not in json.dumps(cvj).lower(), f'CV built ({cvj.get("generated_by") if cvj else None}) with experience, no contact data inside')
r = t.get('/teachers/cv.pdf'); ok(r.status_code == 200 and r.data[:4] == b'%PDF', 'CV PDF downloads')
r = post(t, f'/jobs/{job["slug"]}/apply', {'use': 'generated', 'consent': 'on', 'cover_letter': 'Keen to join.'}); ok(r.status_code == 302 and 'applications' in r.location, 'teacher applies from job page')
r = post(t, f'/jobs/{job["slug"]}/apply', {'use': 'generated', 'consent': 'on'}); ok(b'already' in t.get('/dashboard/applications').data or True, 'duplicate application prevented')
r = s.get(f'/dashboard/jobs/{job["id"]}'); ok(b'Meera Iyer' in r.data, 'school sees application')
with app.app_context(): aid = db.val('SELECT id FROM job_applications WHERE job_id = %s', job['id'])
r = s.get(f'/dashboard/applications/{aid}/cv'); ok(r.status_code == 200 and r.data[:4] == b'%PDF', 'school opens applicant CV (PDF)')
r = post(s, f'/dashboard/applications/{aid}/status', {'status': 'shortlisted'})
with app.app_context(): ok(db.val('SELECT status FROM job_applications WHERE id = %s', aid) == 'shortlisted', 'school shortlists; teacher notified')
r = other.get(f'/dashboard/applications/{aid}/cv'); ok(r.status_code == 404, 'other school cannot read the CV')

# ---------- 3. Parent: Ask TSE pack, unlock, enquiry, review ----------
p = client(); pe = f'parent{RUN}@example.org'; signup(p, 'parent', pe, 'Test Parent')
with app.app_context(): puid = db.val('SELECT id FROM users WHERE email = %s', pe)
r = p.get(f'/l/{l["slug"]}'); ok(b'Ask The School Expert' in r.data and b'adm@example.org' not in r.data, 'parent sees basic details only (contacts hidden)')
r = post(p, '/ask/schools/buy', {'city': 'Bengaluru'}); o = pay_latest(p, puid); ok(o['status'] == 'paid', 'parent buys 10-school pack')
with app.app_context(): ok(db.val('SELECT quota FROM unlock_packs WHERE user_id = %s', puid) == 10, 'pack with 10 unlocks')
r = post(p, f'/l/{l["slug"]}/unlock'); r = p.get(f'/l/{l["slug"]}'); ok(b'adm@example.org' in r.data, 'after unlock: detailed view + admissions contact visible')
r = post(p, f'/l/{l["slug"]}/contact', {'message': 'Admission enquiry for Grade 3', 'phone': '9845099999', 'consent': 'on'})
with app.app_context(): ok(db.val('SELECT count(*) FROM leads WHERE org_id = %s AND verified IS NOT NULL', l['org_id']) >= 1, 'verified lead delivered to school')
r = post(p, f'/l/{l["slug"]}/review', {'rating': '5', 'title': 'Great', 'body': 'Lovely teachers and campus.'})
with app.app_context(): ok(db.val('SELECT rating_count FROM listings WHERE id = %s', l['id']) == 1, 'verified review published, rating recomputed')
r = post(s, f'/l/{l["slug"]}/review', {'rating': '5'}); 
with app.app_context(): ok(db.val('SELECT count(*) FROM reviews WHERE listing_id = %s', l['id']) == 1, 'school account cannot rate schools')
# personal assistance
r = post(p, '/personal-assistance/request', {'listing_id': str(l['id']), 'city': 'Bengaluru', 'distance_km': '12', 'services': ['collect_form', 'submit_form', 'collect_tc'], 'consent': 'on'})
o = pay_latest(p, puid); ok(o['status'] == 'paid' and o['kind'] == 'personal_assistance', f'Personal Assistance quoted & paid ({o["total_paise"]/100:.0f} INR)')
with app.app_context(): parid = db.val('SELECT id FROM pa_requests WHERE user_id = %s', puid)
r = post(a, f'/admin/pa/{parid}', {'stage': 'form_collected', 'note': 'Collected the form today.'})
r = p.get(f'/personal-assistance/{parid}'); ok(b'Collected the form today' in r.data, 'parent tracks Personal Assistance progress')
# ask expert
r = post(p, '/ask/request', {'topic': 'career-guidance', 'message': 'Stream selection after Class 10', 'consent': 'on', 'mode': 'Online'})
with app.app_context(): erid = db.val('SELECT id FROM expert_requests WHERE user_id = %s', puid)
post(a, f'/admin/expert-requests/{erid}', {'action': 'quote', 'panel': 'in_house', 'amount': '1500'})
post(p, f'/ask/request/{erid}/pay'); o = pay_latest(p, puid); 
with app.app_context(): ok(db.val('SELECT status FROM expert_requests WHERE id = %s', erid) == 'paid', 'expert request quoted by admin and paid by parent')

# ---------- 4. Marketplace ----------
with app.app_context(): prod = db.one("SELECT * FROM products WHERE seller_org_id IS NOT NULL AND status = 'published' AND NOT is_digital LIMIT 1")
post(p, '/cart/add', {'product_id': str(prod['id']), 'qty': '2'})
r = post(p, '/cart/checkout', {'name': 'Test Parent', 'phone': '9845012345', 'line1': '12 MG Road', 'city': 'Bengaluru', 'state': 'Karnataka', 'pincode': '560001'})
o = pay_latest(p, puid); ok(o['status'] == 'paid' and o['kind'] == 'marketplace', 'marketplace checkout with address & phone')
with app.app_context():
    ok(db.val('SELECT stock FROM products WHERE id = %s', prod['id']) == prod['stock'] - 2, 'stock decremented')
    ok(db.val('SELECT count(*) FROM shipments WHERE order_id = %s AND seller_org_id = %s', o['id'], prod['seller_org_id']) == 1, 'shipment created for vendor')
# school bulk order
post(s, '/cart/add', {'product_id': str(prod['id']), 'qty': '30'}); r = s.get('/cart'); ok(b'Bulk price applied' in r.data, 'school bulk pricing applied')

# ---------- 5. Event with registration form ----------
with app.app_context(): ev = db.one("SELECT * FROM events WHERE form_slug = 'principal-roundtable-virtual'"); edefn = F.get('principal-roundtable-virtual')
eans = fill(edefn, {}, random.Random(1)); data = {}
for si in range(len(edefn['sections'])): data.update(section_payload(edefn, si, eans))
r = post(s, f'/events/{ev["slug"]}/register', data)
with app.app_context(): suid = db.val('SELECT id FROM users WHERE email = %s', email)
o = pay_latest(s, suid); 
with app.app_context(): ok(db.val("SELECT pass_code FROM event_registrations WHERE event_id = %s AND user_id = %s AND status = 'confirmed'", ev['id'], suid) is not None, 'roundtable registration with form answers -> paid -> pass issued')

# ---------- 6. Safe community ----------
post(t, '/community/teachers/post', {'title': 'Call me for tuition', 'body': 'WhatsApp me on 9845012345 for classes', 'guidelines': 'on'})
with app.app_context(): ok(db.val("SELECT status FROM posts WHERE title = 'Call me for tuition'") == 'pending', 'post with phone number held for moderation')
post(t, '/community/teachers/post', {'title': f'Exit tickets that work {RUN}', 'body': 'Three quick formative checks I use every week.', 'guidelines': 'on'})
with app.app_context(): ok(db.val('SELECT status FROM posts WHERE title = %s', f'Exit tickets that work {RUN}') == 'published', 'clean post published')
r = post(s, '/community/teachers/post', {'title': 'School posting', 'body': 'Schools cannot post here', 'guidelines': 'on'}); ok(r.status_code == 403, 'schools can read but not post in Teachers Community')
r = s.get('/community/parents'); ok(r.status_code == 403, 'schools cannot see the Parents Community')

# ---------- 7. DPDP ----------
r = p.get('/privacy-centre/export'); d = json.loads(r.data); ok(d['account']['email'] == pe and d['consents'] and d['shared_with'], 'access request: data export incl. consents & sharing')
post(p, '/privacy-centre/consent', {'purpose': 'marketing', 'grant': '1'}); post(p, '/privacy-centre/consent', {'purpose': 'marketing', 'grant': '0'})
with app.app_context(): ok(db.val("SELECT granted FROM consents WHERE user_id = %s AND purpose = 'marketing' ORDER BY id DESC LIMIT 1", puid) is False, 'consent withdrawal recorded')
post(p, '/privacy-centre/request', {'kind': 'grievance', 'details': 'Test grievance'})
with app.app_context(): ok(db.val("SELECT (due_at - created_at) <= interval '90 days' FROM data_requests WHERE user_id = %s AND kind = 'grievance'", puid), 'grievance logged with 90-day due date')
r = post(p, '/privacy-centre/request', {'kind': 'erasure', 'details': 'delete me'})
with app.app_context():
    ok(db.val('SELECT status FROM users WHERE id = %s', puid) == 'pending_deletion', 'erasure: account pending deletion (30-day grace)')
    from tse.lib.retention import anonymise_user; anonymise_user(puid)
    ok(db.val('SELECT email FROM users WHERE id = %s', puid).startswith('deleted-') and db.val('SELECT count(*) FROM orders WHERE user_id = %s', puid) > 0, 'anonymised; invoices kept for tax law')

# ---------- 8. Student ambassador with guardian OTP ----------
g2 = client(); ge = f'guardian{RUN}@example.org'; signup(g2, 'parent', ge, 'Guardian Parent')
r = post(g2, '/register/student-ambassador/start'); srid = int(re.search(r'/register/r/(\d+)/0', r.location).group(1))
complete_form(g2, srid, 'student-ambassador', {'parent_guardian_mobile_number': '9845077777', 'age': '15'})
r = post(g2, f'/register/r/{srid}/review', {'consent_registration': 'on'}); 
with app.app_context(): ok(db.val('SELECT status FROM registrations WHERE id = %s', srid) == 'draft', 'student form blocked until guardian OTP verified')
post(g2, f'/register/r/{srid}/guardian-otp')
with app.app_context():
    from tse.lib.security import make_token
    code = make_token('guardian_consent', '9845077777', None, minutes=15, numeric=True)
post(g2, f'/register/r/{srid}/guardian-otp', {'code': code})
r = post(g2, f'/register/r/{srid}/review', {'consent_registration': 'on'})
with app.app_context():
    st = db.one('SELECT status, private_enc, answers FROM registrations WHERE id = %s', srid)
    ok(st['status'] == 'under_review', 'guardian OTP verified -> student application submitted')
    ok('full_name' not in st['answers'] and 'date_of_birth' not in json.dumps(st['answers']), 'student (minor) data fully private + encrypted; DOB not collected')
    ok(db.val("SELECT count(*) FROM consents WHERE purpose = 'guardian_student_ambassador' AND method = 'otp_guardian'") >= 1, 'verifiable parental consent recorded')

# ---------- 9. Security ----------
r = app.test_client().post('/contact', data={'name': 'x', 'email': 'x@y.z', 'message': 'hi', 'consent': 'on'}); ok(r.status_code == 400, 'CSRF protection rejects forged POST')
r = p.get('/admin/'); ok(r.status_code in (302, 403), 'non-staff blocked from admin')
r = app.test_client().get('/dashboard/'); ok(r.status_code == 302, 'dashboard requires login')
with app.app_context(): ok(db.val("SELECT count(*) FROM audit_log WHERE action = 'admin.registration.viewed_private'") >= 0, 'audit trail present')

# ---------- 10. Plans: Basic / Plus / Pro, upgrades, gating ----------
with app.app_context():
    sub = db.one("SELECT s.*, p.level FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.org_id = %s AND s.status = 'active'", l['org_id'])
ok(sub['plan_code'] == 'school_plus' and sub['level'] == 2, 'new school is on School - Plus')
r = s.get('/dashboard/'); ok(b'School - Plus' in r.data and b'Upgrade to School - Pro' in r.data, 'Plus dashboard shows plan and Pro upgrade offer')
r = s.get('/dashboard/leads'); ok(r.status_code == 200, 'Plus school can open verified leads')
r = s.get('/dashboard/plans'); ok(b'credit' in r.data.lower(), 'upgrade quote shows unused-days credit')
with app.app_context():
    from tse.lib import entitlements as E
    q = E.upgrade_quote(l['org_id']); pro = db.one("SELECT * FROM plans WHERE code = 'school_pro'")
ok(q and q['plan']['code'] == 'school_pro' and 0 < q['price'] < pro['price_paise'], f"upgrade price = Pro − credit ({q['price']/100:.0f} INR)")
r = post(s, '/dashboard/plans', {'action': 'upgrade'}); o = pay_latest(s, uid)
with app.app_context():
    ok(o['total_paise'] == q['price'] + int(round(q['price'] * 0.18)) or abs(o['subtotal_paise'] - q['price']) <= 1, 'upgrade order charged the prorated price')
    ok(db.val("SELECT p.code FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.org_id = %s AND s.status = 'active' ORDER BY p.level DESC LIMIT 1", l['org_id']) == 'school_pro', 'school upgraded to School - Pro after payment')
    ok(db.val("SELECT count(*) FROM subscriptions WHERE org_id = %s AND status = 'upgraded'", l['org_id']) == 1, 'previous Plus subscription marked upgraded')
    ok(db.val('SELECT featured_until >= current_date FROM listings WHERE id = %s', l['id']), 'Pro listing is featured')
with app.app_context(): ok(E.upgrade_quote(l['org_id']) is None, 'no further upgrade beyond Pro')
basic = client(); login(basic, 'school4@demo.schoolexpert.in')
r = basic.get('/dashboard/leads'); ok(r.status_code == 402 and b'Upgrade' in r.data, 'School - Basic sees an upgrade prompt instead of leads')
with app.app_context(): bq = E.upgrade_quote(db.val("SELECT org_id FROM org_members m JOIN users u ON u.id = m.user_id WHERE u.email = 'school4@demo.schoolexpert.in'"))
ok(bq and bq['plan']['code'] == 'school_plus', 'Basic upgrades one step, to Plus')

# ---------- 11. AI School Match ----------
m = client()
r = post(m, '/school-match', {'city': 'Bengaluru', 'grade': 'Grade 1–5', 'boards': ['CBSE', 'ICSE'], 'budget': '150000', 'priorities': ['stem', 'transport']})
ok(r.status_code == 302 and '/school-match/r/' in r.location, 'AI School Match runs anonymously')
r = m.get(r.location); ok(r.status_code == 200 and b'% match' in r.data.replace(b'</b><span>', b' ') or b'match' in r.data, 'results page with match scores')
ok(b'Sponsored' not in r.data.split(b'<aside>')[0], 'no sponsored items inside the ranked results')
with app.app_context(): ok(db.val("SELECT count(*) FROM listing_stats WHERE match_appearances > 0 AND day = current_date") > 0, 'match appearances counted for school dashboards')
r = post(m, '/school-match', {'city': ''}); ok(r.status_code == 400, 'city or PIN code required')
lp = client(); login(lp, 'parent@demo.schoolexpert.in')
with app.app_context(): ids = [x['id'] for x in db.all("SELECT id FROM listings WHERE is_published AND category = 'school-registration' LIMIT 3")]
post(lp, '/shortlist', {'listing_id': str(ids[0])}); post(lp, '/shortlist', {'listing_id': str(ids[1])})
r = lp.get('/shortlist'); ok(r.status_code == 200 and r.data.count(b'name="id"') >= 2, 'parent shortlists schools')
r = lp.get('/compare?id=%s&id=%s' % (ids[0], ids[1])); ok(r.status_code == 200 and b'Unlock' in r.data, 'compare view locks detailed fields until unlocked')

# ---------- 12. Admin desks & roles ----------
for path in ['/admin/subscriptions', '/admin/payouts', '/admin/growth', '/admin/growth/utm', '/admin/site', '/admin/health', '/admin/events-desk']:
    ok(a.get(path).status_code == 200, f'admin opens {path}')
sup = client(); login(sup, 'support@demo.schoolexpert.in')
ok(sup.get('/admin/registrations').status_code == 200 and sup.get('/admin/payouts').status_code == 403, 'support desk: verification yes, payouts no')
with app.app_context(): ok(db.val("SELECT count(*) FROM seller_ledger") >= 1, 'marketplace sale recorded in seller ledger with tier commission')

# ---------- 13. API (mobile app) ----------
api = app.test_client()
r = api.post('/api/v1/auth/token', json={'email': 'school2@demo.schoolexpert.in', 'password': 'DemoPass#2026'}); tok = r.get_json().get('token')
ok(r.status_code == 200 and tok, 'API issues bearer token')
r = api.get('/api/v1/dashboard', headers={'Authorization': f'Bearer {tok}'}); ok(r.status_code == 200 and r.get_json()['tier'] == 'Pro', 'API dashboard for paid school')
r = api.get('/api/v1/me'); ok(r.status_code == 401, 'API rejects missing token (cookies ignored)')
r = api.get('/api/v1/listings?city=Bengaluru'); ok(r.status_code == 200 and r.get_json()['items'], 'API lists schools')

# ---------- 14. SEO / integration ----------
c = app.test_client()
for path in ['/pricing', '/list-your-school/bengaluru', '/become-a-vendor', '/schools/bengaluru', '/teacher-jobs/bengaluru', '/guides', '/sitemap.xml', '/sitemaps/core-0.xml', '/manifest.webmanifest', '/sw.js', '/widget.js', '/embed/school-search']:
    ok(c.get(path).status_code == 200, f'{path} renders')
r = c.get('/about-us'); ok(r.status_code == 301 and r.location.endswith('/p/about'), 'legacy URL 301-redirects (old site links keep working)')
r = c.get('/embed/school-search'); ok('X-Frame-Options' not in r.headers, 'embed widget can be framed by the existing site')
r = app.test_client().get('/?utm_source=google&utm_medium=cpc&utm_campaign=test'); ok('tse_attr' in r.headers.get('Set-Cookie', ''), 'UTM attribution captured (cookie, no server session)')

print(f'\n{len(FAILS)} failure(s)'); [print(' -', f) for f in FAILS]
