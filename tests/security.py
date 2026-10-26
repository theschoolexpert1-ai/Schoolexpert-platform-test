"""Security test-suite — one section per layer. Run: python tests/security.py (needs the demo database)."""
import sys, os, re, io, json, time, base64, zipfile, random, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tse import create_app
from tse.db import db
from tse.lib import mfa as MFA, security as S, forms as F

app = create_app({'TESTING': True}); app.logger.setLevel('ERROR')
FAILS = []; RUN = str(random.randint(10000, 99999))
def ok(cond, msg): print(('PASS ' if cond else 'FAIL ') + msg); cond or FAILS.append(msg)
def client():
    c = app.test_client(); c.get('/')
    with c.session_transaction() as s: s['_csrf'] = 'tok'
    return c
def post(c, url, data=None, **kw):
    d = dict(data or {}); d['_csrf'] = 'tok'; return c.post(url, data=d, **kw)
def login(c, email, pw='DemoPass#2026'):
    return post(c, '/login', {'email': email, 'password': pw})
def uid(email):
    with app.app_context(): return db.val('SELECT id FROM users WHERE email = %s', email)

# ======================= 1. DATABASE LAYER =======================
print('\n--- Database layer ---')
with app.app_context():
    a_org = db.val("SELECT org_id FROM org_members m JOIN users u ON u.id = m.user_id WHERE u.email = 'school1@demo.schoolexpert.in'")
    b_org = db.val("SELECT org_id FROM org_members m JOIN users u ON u.id = m.user_id WHERE u.email = 'school2@demo.schoolexpert.in'")
    db.insert('leads', dict(org_id=b_org, source='enquiry', name='RLS probe', email='probe@example.org', message='x'), returning=None)
    from tse.db import db as D
    D.set_context_provider(lambda: ('off', '999999', str(a_org)))           # pretend to be a member of school A only
    seen_b = D.val('SELECT count(*) FROM leads WHERE org_id = %s', b_org)
    seen_regs = D.val('SELECT count(*) FROM registrations WHERE org_id = %s', b_org)
    upd = D.run("UPDATE leads SET status = 'closed' WHERE org_id = %s", b_org)
    D.set_context_provider(lambda: ('off', '', ''))                          # anonymous
    anon_orders = D.val('SELECT count(*) FROM orders')
    app_ctx_provider = app.view_functions  # noqa
    create_app({'TESTING': True})                                           # re-installs the real provider
    ok(seen_b == 0 and seen_regs == 0, 'RLS: a school cannot read another school\'s leads or registrations, even with raw SQL')
    ok(upd == 0, 'RLS: a school cannot update another school\'s leads')
    ok(anon_orders == 0, 'RLS: anonymous database context sees no orders')
    ok(db.val('SELECT count(*) FROM leads WHERE org_id = %s', b_org) >= 1, 'trusted server jobs (no request) still work')
    try:
        db.run("UPDATE audit_log SET action = 'tampered' WHERE id = (SELECT min(id) FROM audit_log)"); ok(False, 'audit log blocks UPDATE')
    except Exception as e:
        ok('append-only' in str(e), 'audit log is append-only (UPDATE blocked)')
    try:
        db.run('DELETE FROM audit_log WHERE id = (SELECT min(id) FROM audit_log)'); ok(False, 'audit log blocks DELETE')
    except Exception as e:
        ok('append-only' in str(e), 'audit log is append-only (DELETE blocked outside retention)')
    ok(db.val('SELECT count(*) FROM audit_log WHERE row_hash IS NOT NULL') > 0, 'audit entries are hash-chained')
    blob = S.encrypt_json({'pan': 'ABCDE1234F'})
    ok(blob.split(':')[0] in ('v1', 'v2') and 'ABCDE' not in blob, 'private form answers are AES-256-GCM encrypted')
    old = app.config.get('FIELD_ENCRYPTION_KEYS')
    app.config['FIELD_ENCRYPTION_KEYS'] = 'v2:' + base64.b64encode(os.urandom(32)).decode() + ',v1:' + base64.b64encode(S._keys()[0][1]).decode() if not old else old
    ok(S.decrypt_json(blob) == {'pan': 'ABCDE1234F'} and S.encrypt_json({'a': 1}).startswith('v2:'), 'key rotation: old data readable, new data uses the newest key')
    app.config['FIELD_ENCRYPTION_KEYS'] = old

# ======================= 2. IDENTITY & SESSIONS =======================
print('\n--- Identity & sessions ---')
c = client(); email = f'sec{RUN}@example.org'
r = post(c, '/signup', {'type': 'parent', 'name': 'Sec Tester', 'email': email, 'phone': '9845000000', 'password': 'password1234', 'consent_account': 'on', 'adult': 'on'})
ok(r.status_code == 400 and b'too' in r.data.lower(), 'common passwords rejected')
r = post(c, '/signup', {'type': 'parent', 'name': 'Sec Tester', 'email': email, 'phone': '9845000000', 'password': 'tester-sec-9!', 'consent_account': 'on', 'adult': 'on'})
ok(r.status_code == 400, 'passwords containing your name rejected')
r = post(c, '/signup', {'type': 'parent', 'name': 'Sec Tester', 'email': email, 'phone': '9845000000', 'password': 'blue river kite 42', 'consent_account': 'on', 'adult': 'on', 'hp_website': 'http://spam'})
ok(r.status_code == 400, 'bot honeypot blocks automated sign-ups')
r = post(c, '/signup', {'type': 'parent', 'name': 'Sec Tester', 'email': email, 'phone': '9845000000', 'password': 'blue river kite 42', 'consent_account': 'on', 'adult': 'on'})
ok(r.status_code == 302, 'strong passphrase accepted')
c2 = client()
for i in range(5): login(c2, email, 'wrong-password-x')
r = login(c2, email, 'blue river kite 42')
ok(r.status_code == 429, 'account locks after 5 failed attempts (even with the right password)')
with app.app_context():
    ok(db.val("SELECT count(*) FROM audit_log WHERE action = 'security.account_locked' AND entity_id = %s", str(uid(email))) == 1, 'lockout recorded in the audit log')
    db.run('UPDATE users SET locked_until = NULL WHERE email = %s', email)
r = login(client(), f'nobody{RUN}@example.org', 'whatever-123-xyz'); ok(r.status_code == 401, 'unknown accounts get the same generic error (no user enumeration)')
# two-step verification
with app.app_context():
    secret = MFA.new_secret(); codes = MFA.enable(uid(email), secret)
c3 = client(); r = login(c3, email, 'blue river kite 42')
ok(r.status_code == 302 and '/login/verify' in r.location, 'with 2-step on, password alone does not sign in')
r = c3.get('/dashboard/'); ok(r.status_code == 302 and '/login' in r.location, 'not signed in until the code is verified')
r = post(c3, '/login/verify', {'code': '000000'}); ok(r.status_code == 200 and b'did not work' in r.data, 'wrong 2-step code rejected')
code = MFA._code(secret, int(time.time() // 30))
r = post(c3, '/login/verify', {'code': code}); ok(r.status_code == 302 and c3.get('/dashboard/').status_code == 200, 'correct TOTP code signs in')
c4 = client(); login(c4, email, 'blue river kite 42'); r = post(c4, '/login/verify', {'code': code})
ok(b'did not work' in r.data, 'a TOTP code cannot be replayed')
r = post(c4, '/login/verify', {'code': codes[0]}); ok(r.status_code == 302, 'one-time recovery code works')
c5 = client(); login(c5, email, 'blue river kite 42'); r = post(c5, '/login/verify', {'code': codes[0]})
ok(b'did not work' in r.data, 'recovery codes are single-use')
# staff must use 2-step
app.config['MFA_REQUIRED_FOR_STAFF'] = True
s = client(); login(s, 'support@demo.schoolexpert.in'); r = s.get('/admin/')
ok(r.status_code == 302 and '/account/security' in r.location, 'staff without 2-step are sent to set it up before the back office')
r = post(s, '/admin/registrations/1', {'action': 'verify'}); ok(r.status_code == 302 and '/account/security' in r.location, 'staff without 2-step cannot change anything either')
app.config['MFA_REQUIRED_FOR_STAFF'] = False
# step-up authentication
app.config['ENFORCE_FRESH_AUTH'] = True
a = client(); login(a, 'admin@demo.schoolexpert.in')
with a.session_transaction() as sess: sess['auth_at'] = int(time.time()) - 3600
r = a.get('/admin/registrations/1'); ok(r.status_code == 302 and '/reauth' in r.location, 'viewing private documents needs a fresh password check')
r = post(a, '/reauth', {'password': 'DemoPass#2026', 'next': '/admin/registrations/1'}); ok(r.status_code == 302 and a.get('/admin/registrations/1').status_code == 200, 'after re-entering the password, access is granted')
app.config['ENFORCE_FRESH_AUTH'] = False
# idle timeout
st = client(); login(st, 'support@demo.schoolexpert.in')
with st.session_transaction() as sess: sess['seen'] = int(time.time()) - 31 * 60
r = st.get('/admin/'); ok(r.status_code == 302 and '/login' in r.location, 'staff sessions end after 30 minutes idle')
# sign out other devices
d1 = client(); d2 = client(); login(d1, 'parent@demo.schoolexpert.in'); login(d2, 'parent@demo.schoolexpert.in')
post(d1, '/account/security', {'action': 'signout_others'})
ok(d2.get('/dashboard/').status_code == 302 and d1.get('/dashboard/').status_code == 200, '"sign out other devices" revokes other sessions')
# session fixation
f = client()
with f.session_transaction() as sess: before = sess.sid
login(f, 'parent@demo.schoolexpert.in')
with f.session_transaction() as sess: after = sess.sid
ok(before != after, 'session id rotates at sign-in (no fixation)')

# ======================= 3. APPLICATION / AUTHORISATION =======================
print('\n--- Application & authorisation ---')
with app.app_context():
    vid = db.insert('users', dict(email=f'viewer{RUN}@example.org', name='Viewer Member', password_hash=S.hash_password('DemoPass#2026'), account_type='organisation', is_adult=True))
    db.insert('org_members', dict(org_id=a_org, user_id=vid, role='viewer'), returning=None)
    reg_a = db.val('SELECT id FROM registrations WHERE org_id = %s ORDER BY id LIMIT 1', a_org)
    job_b = db.val("SELECT id FROM jobs WHERE org_id = %s LIMIT 1", b_org)
v = client(); login(v, f'viewer{RUN}@example.org')
ok(v.get('/dashboard/leads').status_code == 200, 'organisation viewer can look at leads')
r = post(v, '/dashboard/jobs/new', {'title': 'x', 'description': 'y', 'action': 'draft'}); ok(r.status_code == 403, 'organisation viewer cannot create or change anything')
r = post(v, f'/register/r/{reg_a}/0', {'action': 'next'}); ok(r.status_code == 403, 'organisation viewer cannot edit the registration')
sa = client(); login(sa, 'school1@demo.schoolexpert.in')
if job_b: ok(sa.get(f'/dashboard/jobs/{job_b}/edit').status_code == 404, 'IDOR: another school\'s job id returns not-found')
r = client().get('/private-file?ref=private:registrations/%25'); ok(r.status_code in (302, 404), 'private-file wildcards rejected')
p = client(); login(p, 'parent@demo.schoolexpert.in')
ok(p.get('/private-file?ref=private:registrations/2026/10/' + 'a' * 32 + '.pdf').status_code == 404, 'parents cannot open private documents')
ok(p.get('/admin/').status_code == 403, 'parents cannot reach the back office')
api = app.test_client(); login(api, 'school2@demo.schoolexpert.in')
ok(api.get('/api/v1/me').status_code == 401, 'API ignores browser cookies (CSRF-proof)')
r = client().post('/contact', data={'name': 'x', 'email': 'x@y.z', 'message': 'hi', 'consent': 'on'}); ok(r.status_code == 400, 'forged POST without CSRF token rejected')
app.config['ENFORCE_RATE_LIMITS'] = True
rl = client(); codes_seen = [login(rl, f'rl{RUN}@example.org', 'nope-nope-nope').status_code for _ in range(12)]
ok(429 in codes_seen, 'sign-in attempts are rate limited per IP (shared across servers)')
app.config['ENFORCE_RATE_LIMITS'] = False

# ======================= 4. UPLOADS & FILES =======================
print('\n--- Uploads & files ---')
from tse.lib import storage
from werkzeug.datastructures import FileStorage
with app.test_request_context():
    def up(name, data, private=False, kinds=('image', 'doc')):
        try: return storage.save(FileStorage(io.BytesIO(data), filename=name), private=private, kinds=kinds)
        except storage.UploadError as e: return str(e)
    ok('not accepted' in up('bad.pdf', b'%PDF-1.4 1 0 obj << /OpenAction << /S /JavaScript /JS (app.alert(1)) >> >>'), 'PDFs containing JavaScript are rejected')
    zb = io.BytesIO(); z = zipfile.ZipFile(zb, 'w'); z.writestr('[Content_Types].xml', 'x'); z.writestr('word/vbaProject.bin', 'macro'); z.close()
    ok('macros' in up('bad.docx', zb.getvalue()), 'Office files with macros are rejected')
    ok('does not match' in up('fake.png', b'MZ\x90\x00 this is an exe'), 'file content must match its extension (no disguised executables)')
    ok('not allowed' in up('run.exe', b'MZ'), 'executable file types are refused')
    saved = up('cert.pdf', b'%PDF-1.4 clean certificate', private=True)
    raw = open(storage.private_path(saved['url']), 'rb').read()
    ok(raw.startswith(b'TSEENC1') and b'clean certificate' not in raw, 'private documents are encrypted at rest')
    ok(storage.read_private(saved['url']) == b'%PDF-1.4 clean certificate', 'authorised reads decrypt transparently')
    from PIL import Image
    im = Image.new('RGB', (50, 50)); ex = Image.Exif(); ex[0x010F] = 'GPS-Camera'; ex[0x0110] = 'Model-X'; bio = io.BytesIO(); im.save(bio, 'JPEG', exif=ex.tobytes())
    sp = up('photo.jpg', bio.getvalue()); data = open(os.path.join(app.config['UPLOAD_DIR'], sp['url'][len('/media/'):]), 'rb').read()
    ok(b'Exif' not in data, 'photo location (EXIF/GPS) stripped from uploads')

# ======================= 5. BROWSER / HTTP LAYER =======================
print('\n--- Browser & HTTP ---')
r = client().get('/'); csp = r.headers.get('Content-Security-Policy', '')
m = re.search(r"script-src ([^;]+)", csp)
ok(m and "'unsafe-inline'" not in m.group(1) and "'nonce-" in m.group(1), "CSP: scripts need a per-request nonce (no 'unsafe-inline')")
r2 = client().get('/school-match')
ok(b'<script nonce="' in r2.data and all(re.search(rb'\son(click|change|submit|load)=', x.data) is None for x in (r, r2)), 'inline scripts carry the nonce; no inline event handlers')
for h in ('X-Content-Type-Options', 'Referrer-Policy', 'Permissions-Policy', 'Cross-Origin-Opener-Policy', 'X-Frame-Options'):
    ok(h in r.headers, f'header {h} set')
lp = client(); login(lp, 'parent@demo.schoolexpert.in'); r = lp.get('/dashboard/')
ok('no-store' in r.headers.get('Cache-Control', ''), 'personal pages are never cached')
ok(client().get('/.well-known/security.txt').status_code == 200, 'security.txt published for responsible disclosure')
ok(client().get('/healthz').data == b'ok', 'health check reveals nothing but up/down')

# ======================= 6. OPERATIONS =======================
print('\n--- Operations ---')
import logging
rec = logging.LogRecord('x', 20, __file__, 1, 'login for asha@example.org phone 9845012345 token=abc123secret', None, None)
S.RedactFilter().filter(rec); ok('asha@' not in rec.msg and '9845012345' not in rec.msg and 'abc123secret' not in rec.msg, 'personal data and secrets are redacted from logs')
for bad in ('http://example.org/hook', 'https://127.0.0.1/hook', 'https://169.254.169.254/latest/meta-data'):
    try: S.safe_outbound_url(bad); ok(False, f'SSRF guard blocks {bad}')
    except ValueError: ok(True, f'SSRF guard blocks {bad}')
import subprocess
env = dict(os.environ, TSE_ENV='production', SECRET_KEY='dev-insecure-change-me')
out = subprocess.run([sys.executable, '-c', 'import tse; tse.create_app()'], capture_output=True, text=True, env=env, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ok('Refusing to start' in out.stderr, 'production refuses to start with weak/missing secrets')
import subprocess
out = subprocess.run([sys.executable, '-m', 'flask', '--app', 'tse', 'verify-audit'], capture_output=True, text=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ok('chain intact' in out.stdout, 'audit-log hash chain verifies')

# ======================= 7. FORMS FROM YOUR DOCUMENTS =======================
print('\n--- Registration forms (document fidelity) ---')
with app.app_context():
    k12 = F.get('k12-curriculum-development-expert-registration')
    boards = next(f for _, s, f in F.fields(k12) if f['key'] == 'boards_curricula_with_professional_experience')
    ok(len(boards['options']) == 14 and boards.get('other'), 'Curriculum Experts: all 14 boards + "Other State/UT Board"')
    ok((k12.get('internal') or {}).get('checks', [])[:1] == ['CV verified'], 'Curriculum Experts: internal verification checklist from your form drives the admin screen')
    cp = F.get('course-provider')
    flds = {f['key']: f for _, s, f in F.fields(cp)}
    ok(len(flds) == 60 and len(flds['course_categories']['options']) == 27, 'Course Providers: rebuilt field-for-field from your specification table')
    ok(not F.visible(flds['certificate_type'], {'certificate_provided': 'No'}) and F.visible(flds['certificate_type'], {'certificate_provided': 'Optional'}), 'Course Providers: certificate fields follow your conditional logic')
    rt = F.get('principal-roundtable-virtual'); rc = next(f for _, s, f in F.fields(rt) if f['key'] == 'recording_consent')
    ok(rc['type'] == 'radio' and len(rc['options']) == 2, 'Roundtable: recording consent is a choice between your two statements')
    rec = F.get('recreation-hobbies-enrichment-provider'); tf = next(f for _, s, f in F.fields(rec) if f['key'] == 'trial_class_fee')
    ok(F.visible(tf, {'is_a_trial_demo_class_available': 'Yes – Paid'}) and not F.visible(tf, {'is_a_trial_demo_class_available': 'Yes – Free'}), 'Hobby providers: trial fee only when the trial is paid')
    sa_ = F.get('student-ambassador'); keys = [f['key'] for _, s, f in F.fields(sa_)]
    ok(sum(k.startswith('guardian_decl_') for k in keys) == 4 and 'date_of_birth' not in keys, 'Student Ambassador: 4 guardian declarations restored; no date of birth collected')
cpo = client(); login(cpo, 'partner0@demo.schoolexpert.in')
with app.app_context():
    org = db.val("SELECT org_id FROM org_members m JOIN users u ON u.id = m.user_id WHERE u.email = 'partner0@demo.schoolexpert.in'")
    src = db.insert('registrations', dict(form_slug='course-provider', form_version=1, user_id=uid('partner0@demo.schoolexpert.in'), org_id=org,
                    answers={'provider_name': 'Demo Provider', 'course_name': 'Robotics 101'}, status='submitted', progress=40))
r = post(cpo, f'/register/r/{src}/add-record')
with app.app_context(): new = db.one('SELECT * FROM registrations WHERE parent_registration_id = %s', src)
ok(new and new['answers'].get('provider_name') == 'Demo Provider' and 'course_name' not in new['answers'], 'Course Providers: "Add another course" copies provider details, starts a fresh course with its own ID')

print(f'\n{len(FAILS)} failure(s)'); [print(' -', f) for f in FAILS]
sys.exit(1 if FAILS else 0)
