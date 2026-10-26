"""Teachers Hub (formerly TeachersInn) — journeys and isolation checks through the real HTTP layer against PostgreSQL."""
import sys, os, re, random, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tse import create_app
from tse.db import db

app = create_app({'TESTING': True}); app.logger.setLevel('ERROR')
FAILS = []
ok = lambda cond, msg: print(('PASS ' if cond else 'FAIL ') + msg) or (cond or FAILS.append(msg))
RUN = str(random.randint(10000, 99999))

def client():
    c = app.test_client(); c.get('/')
    with c.session_transaction() as s: s['_csrf'] = 'tok'
    return c
def post(c, url, data=None, **kw):
    d = dict(data or {}); d['_csrf'] = 'tok'
    return c.post(url, data=d, **kw)
def keep(c):
    with c.session_transaction() as s: s['_csrf'] = 'tok'
def login(c, email, pw='DemoPass#2026'):
    r = post(c, '/login', {'email': email, 'password': pw}); keep(c); return r
def signup(c, t, email, name):
    r = post(c, '/signup', {'type': t, 'name': name, 'email': email, 'phone': '9845012345', 'password': 'Sup3r-Secret-Pw', 'adult': 'on', 'consent_account': 'on'})
    keep(c); return r
def q(sql, *a):
    with app.app_context():
        with db.elevated(): return db.one(sql, *a)
def val(sql, *a):
    with app.app_context():
        with db.elevated(): return db.val(sql, *a)

# ---------- 1. demo teacher sees the Hub everywhere ----------
t = client(); login(t, 'teacher@demo.schoolexpert.in')
r = t.get('/dashboard/'); h = r.get_data(as_text=True)
ok(r.status_code == 200 and 'CPD this year' in h and 'Continue learning' in h and 'Lesson planner' in h, 'teacher dashboard is the Teachers Hub home')
for path in ['/teachers/learn', '/teachers/certificates', '/teachers/workshops', '/teachers/network', '/teachers/network/connections', '/teachers/messages',
             '/teachers/communities', '/teachers/mentors', '/teachers/tutorials', '/teachers/tutorials?saved=1', '/teachers/planner', '/teachers/planner/new',
             '/teachers/wellbeing', '/teachers/hub/profile', '/teachers', '/jobs']:
    r = t.get(path); ok(r.status_code == 200, f'teacher GET {path} -> {r.status_code}')
ok(t.get('/teachers/hub').status_code == 302, '/teachers/hub redirects to the dashboard')

# ---------- 2. courses, lessons, certificate, public verification ----------
course = q("SELECT c.* FROM courses c WHERE c.published AND NOT EXISTS (SELECT 1 FROM course_enrolments e JOIN users u ON u.id = e.user_id WHERE e.course_id = c.id AND u.email = 'teacher@demo.schoolexpert.in') ORDER BY sort DESC LIMIT 1")
r = t.get(f"/teachers/learn/{course['slug']}?lesson=2"); ok('Enrol' in r.get_data(as_text=True) and '🔒' in r.get_data(as_text=True), 'lesson 2 locked before enrolling')
lessons = [x for x in [q('SELECT id FROM course_lessons WHERE course_id = %s AND position = %s', course['id'], p) for p in range(1, 20)] if x]
r = post(t, f"/teachers/learn/lesson/{lessons[0]['id']}/done"); ok(val('SELECT count(*) FROM lesson_progress p JOIN users u ON u.id = p.user_id WHERE u.email = %s AND p.lesson_id = %s', 'teacher@demo.schoolexpert.in', lessons[0]['id']) == 0, 'cannot complete a lesson without enrolling')
post(t, f"/teachers/learn/{course['slug']}/enrol")
for l in lessons: r = post(t, f"/teachers/learn/lesson/{l['id']}/done")
code = val("SELECT certificate_code FROM course_enrolments e JOIN users u ON u.id = e.user_id WHERE u.email = 'teacher@demo.schoolexpert.in' AND e.course_id = %s", course['id'])
ok(code and code.startswith('TSE-C-'), 'certificate issued after the last lesson')
ok(r.status_code == 302 and code in r.headers.get('Location', ''), 'redirected to the new certificate')
anon = client()
from markupsafe import escape
r = anon.get(f'/teachers/certificates/{code}'); ok(r.status_code == 200 and str(escape(course['title'])) in r.get_data(as_text=True), 'certificate page is publicly verifiable')
r = anon.get(f'/teachers/certificates/verify?code={code.lower()}'); ok('Valid certificate' in r.get_data(as_text=True), 'verify form accepts the code (case-insensitive)')
r = anon.get('/teachers/certificates/verify?code=TSE-C-0000000000'); ok('No certificate found' in r.get_data(as_text=True), 'unknown code is rejected')
ok('@' not in anon.get(f'/teachers/certificates/{code}').get_data(as_text=True).split('<main')[-1].split('</main>')[0], 'certificate shows no email address')
r = t.get('/teachers/certificates'); ok(code in r.get_data(as_text=True), 'certificate listed in My certificates')
ok(val("SELECT count(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.email = 'teacher@demo.schoolexpert.in' AND n.title LIKE 'Certificate ready%%'") >= 1, 'certificate notification sent')

# ---------- 3. access control: Hub is for teachers ----------
p = client(); login(p, 'parent@demo.schoolexpert.in')
r = p.get('/teachers/learn'); ok(r.status_code == 403 and 'for teachers' in r.get_data(as_text=True), 'parents get the teachers-only gate')
ok(anon.get('/teachers/network').status_code == 302, 'anonymous visitors are sent to log in')
r = p.get('/community/teachers-maths'); ok(r.status_code == 403, 'parents cannot read teacher subject communities')

# ---------- 4. two new teachers: directory opt-in, connect, message, isolation ----------
a, b, c3 = client(), client(), client()
signup(a, 'teacher', f'hub-a-{RUN}@example.com', f'Asha Hub {RUN}'); signup(b, 'teacher', f'hub-b-{RUN}@example.com', f'Bala Hub {RUN}'); signup(c3, 'teacher', f'hub-c-{RUN}@example.com', f'Chitra Hub {RUN}')
ida = val('SELECT id FROM users WHERE email = %s', f'hub-a-{RUN}@example.com'); idb = val('SELECT id FROM users WHERE email = %s', f'hub-b-{RUN}@example.com')
idc = val('SELECT id FROM users WHERE email = %s', f'hub-c-{RUN}@example.com')
a.get('/teachers/network'); b.get('/teachers/network'); c3.get('/teachers/network')
ok(val('SELECT directory_visible FROM hub_members WHERE user_id = %s', ida) is False, 'new members are hidden from the directory by default')
r = a.get(f'/teachers/network?q=Bala+Hub+{RUN}'); ok(f'<b>Bala Hub {RUN}</b>' not in r.get_data(as_text=True), 'hidden teachers do not appear in search')
post(a, f'/teachers/network/connect/{idb}'); ok(val('SELECT count(*) FROM connections WHERE requester_id = %s', ida) == 0, 'cannot connect to a hidden teacher')
post(b, '/teachers/hub/profile', {'designation': 'PGT Physics', 'school': 'Test School', 'subjects': 'Physics', 'grades': '11–12', 'board': 'CBSE',
                                   'experience_years': '7', 'bio': 'Inquiry labs.', 'cpd_goal': '40', 'directory_visible': 'on'})
ok(val('SELECT directory_visible FROM hub_members WHERE user_id = %s', idb) is True, 'teacher opts in to the directory')
ok(val("SELECT count(*) FROM consents WHERE user_id = %s AND purpose = 'hub_directory' AND granted", idb) == 1, 'directory opt-in recorded as consent')
r = a.get('/teachers/network?q=Physics'); h = r.get_data(as_text=True)
ok(f'Bala Hub {RUN}' in h and f'hub-b-{RUN}@example.com' not in h and '9845012345' not in h, 'directory shows the opted-in teacher without email or phone')
ok(a.get(f'/teachers/messages/{idb}').status_code == 404, 'strangers cannot open a message thread')
post(a, f'/teachers/messages/{idb}', {'body': 'hello'}); ok(val('SELECT count(*) FROM direct_messages WHERE sender_id = %s', ida) == 0, 'strangers cannot message')
post(a, f'/teachers/network/connect/{idb}')
cid = val('SELECT id FROM connections WHERE requester_id = %s AND addressee_id = %s', ida, idb)
ok(cid and val('SELECT status FROM connections WHERE id = %s', cid) == 'pending', 'connection request created')
ok(post(c3, f'/teachers/network/respond/{cid}', {'action': 'accept'}).status_code == 404, 'a third teacher cannot accept someone else\'s request')
r = b.get('/teachers/network/connections'); ok(f'Asha Hub {RUN}' in r.get_data(as_text=True), 'request appears for the addressee')
post(b, f'/teachers/network/respond/{cid}', {'action': 'accept'}); ok(val('SELECT status FROM connections WHERE id = %s', cid) == 'accepted', 'request accepted')
post(a, f'/teachers/messages/{idb}', {'body': 'Hi Bala — any tips for a ripple-tank demo?'})
raw = val('SELECT body_enc FROM direct_messages WHERE sender_id = %s ORDER BY id DESC LIMIT 1', ida)
ok(raw and 'ripple' not in raw, 'message body is encrypted at rest')
r = b.get(f'/teachers/messages/{ida}'); ok('ripple-tank' in r.get_data(as_text=True), 'recipient reads the decrypted message')
ok(val('SELECT read_at IS NOT NULL FROM direct_messages WHERE sender_id = %s ORDER BY id DESC LIMIT 1', ida), 'message marked read')
ok(c3.get(f'/teachers/messages/{ida}').status_code == 404, 'a third teacher cannot open either side of the conversation')
with app.test_request_context():
    from flask import g
    g.user = {'id': idc, 'account_type': 'teacher'}
    n = db.val('SELECT count(*) FROM direct_messages WHERE sender_id = %s', ida)
ok(n == 0, 'row-level security hides other teachers\' messages even from raw SQL in a request')
post(a, f'/teachers/network/remove/{cid}')
post(a, f'/teachers/messages/{idb}', {'body': 'after removal'})
ok(val("SELECT count(*) FROM direct_messages WHERE sender_id = %s AND recipient_id = %s", ida, idb) == 1, 'cannot message after removing the connection')

# ---------- 5. planner privacy ----------
r = post(a, '/teachers/planner/new', {'title': 'Photosynthesis intro', 'subject': 'Science', 'grade': 'Grade 7', 'plan_date': '2026-11-02', 'duration_min': '45',
                                      'objectives': 'Explain inputs and outputs', 'activities': 'Leaf starch test demo'})
pid = val('SELECT id FROM lesson_plans WHERE user_id = %s ORDER BY id DESC LIMIT 1', ida)
ok(pid and r.status_code == 302, 'lesson plan saved')
ok(a.get(f'/teachers/planner/{pid}/print').status_code == 200, 'owner can print the plan')
ok(b.get(f'/teachers/planner/{pid}').status_code == 404 and b.get(f'/teachers/planner/{pid}/print').status_code == 404, 'another teacher cannot open the plan')
post(b, f'/teachers/planner/{pid}', {'delete': '1'}); ok(val('SELECT count(*) FROM lesson_plans WHERE id = %s', pid) == 1, 'another teacher cannot delete the plan')
post(a, f'/teachers/planner/{pid}', {'title': 'Photosynthesis — intro', 'duration_min': '9999'})
ok(val('SELECT duration_min FROM lesson_plans WHERE id = %s', pid) == 480, 'plan edits are validated (duration capped)')

# ---------- 6. mentorship with staff approval ----------
post(b, '/teachers/hub/profile', {'designation': 'PGT Physics', 'experience_years': '7', 'cpd_goal': '40', 'directory_visible': 'on', 'open_to_mentor': 'on'})
ok(val('SELECT mentor_status FROM hub_members WHERE user_id = %s', idb) == 'pending', 'mentor application pending review')
r = a.get('/teachers/mentors'); ok(f'Bala Hub {RUN}' not in r.get_data(as_text=True), 'unapproved mentors are not listed')
adm = client(); login(adm, 'admin@demo.schoolexpert.in')
r = adm.get('/admin/teachers-hub'); ok(r.status_code == 200 and f'Bala Hub {RUN}' in r.get_data(as_text=True), 'Teachers Hub Desk shows the application')
post(adm, f'/admin/teachers-hub/mentor/{idb}', {'decision': 'approve'})
ok(val('SELECT mentor_status FROM hub_members WHERE user_id = %s', idb) == 'approved', 'staff approves the mentor')
post(c3, f'/teachers/mentors/{idb}/request', {'topic': 'Lab safety', 'message': 'How do you run safe labs with 45 students and one assistant?'})
mid = val('SELECT id FROM mentorships WHERE mentee_id = %s AND mentor_id = %s', idc, idb)
ok(mid, 'mentorship requested')
ok(post(c3, f'/teachers/mentorships/{mid}/accept').status_code == 403, 'mentee cannot accept their own request')
post(b, f'/teachers/mentorships/{mid}/accept'); ok(val('SELECT status FROM mentorships WHERE id = %s', mid) == 'active', 'mentor accepts')
post(c3, f'/teachers/messages/{idb}', {'body': 'Thank you for accepting!'})
ok(val('SELECT count(*) FROM direct_messages WHERE sender_id = %s AND recipient_id = %s', idc, idb) == 1, 'active mentor pairs can message')

# ---------- 7. tutorials, workshops, calendar, communities ----------
tut = q('SELECT slug FROM tutorials ORDER BY id LIMIT 1')['slug']
ok(a.get(f'/teachers/tutorials/{tut}').status_code == 200, 'tutorial opens'); post(a, f'/teachers/tutorials/{tut}/save')
ok(val('SELECT saved FROM tutorial_saves s JOIN tutorials t ON t.id = s.tutorial_id WHERE s.user_id = %s AND t.slug = %s', ida, tut) is True, 'tutorial saved')
ev = q("SELECT * FROM events WHERE cpd_hours > 0 AND status = 'published' AND starts_at > now() ORDER BY starts_at LIMIT 1")
r = anon.get(f"/events/{ev['slug']}.ics"); body = r.get_data(as_text=True)
ok(r.status_code == 200 and 'BEGIN:VEVENT' in body and 'text/calendar' in r.headers['Content-Type'], 'add-to-calendar file')
ok('CPD hours' in anon.get(f"/events/{ev['slug']}").get_data(as_text=True), 'event page shows CPD hours')
post(a, f"/events/{ev['slug']}/register")
ok('Registered' in a.get('/dashboard/').get_data(as_text=True) or val('SELECT count(*) FROM event_registrations WHERE user_id = %s', ida) == 1, 'teacher registers for a workshop')
r = post(a, '/community/teachers-maths/post', {'title': 'Fractions with paper strips', 'body': 'Here is how I teach equivalent fractions with strips.', 'guidelines': 'on'})
ok(val("SELECT count(*) FROM posts WHERE community = 'teachers-maths' AND user_id = %s", ida) == 1, 'teacher posts in a subject community')

# ---------- 8. DPDP: export and erasure include Hub data ----------
r = a.get('/privacy-centre/export'); d = json.loads(r.get_data(as_text=True))
hubx = d.get('teachers_hub', {})
ok(hubx.get('lesson_plans') and any('ripple-tank' in m['body'] for m in hubx.get('messages', [])), 'export includes Hub plans and decrypted messages')
with app.app_context():
    from tse.lib import retention
    with db.elevated(): retention.anonymise_user(ida)
ok(val('SELECT count(*) FROM lesson_plans WHERE user_id = %s', ida) == 0 and val('SELECT count(*) FROM direct_messages WHERE sender_id = %s OR recipient_id = %s', ida, ida) == 0
   and val('SELECT count(*) FROM hub_members WHERE user_id = %s', ida) == 0, 'erasure removes Hub data')

# ---------- 9. admin CMS manages Hub content ----------
for tbl in ('courses', 'course_lessons', 'tutorials'):
    ok(adm.get(f'/admin/cms/{tbl}').status_code == 200, f'admin can manage {tbl}')
ok(p.get('/admin/teachers-hub').status_code in (302, 403, 404), 'non-staff cannot open the Teachers Hub Desk')

print(f'\n{"ALL PASS" if not FAILS else str(len(FAILS)) + " FAILED"}')
sys.exit(1 if FAILS else 0)
