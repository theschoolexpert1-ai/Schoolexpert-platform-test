"""Teachers Hub — upskilling, certificates, workshops, network & messages, communities, mentorship, tutorials, planner.

Formerly the standalone TeachersInn app; now part of The School Expert™ with the same account, database and security.
Every page is for teacher accounts (staff can view to support and moderate). No student / child data is collected.
"""
import datetime, functools, json
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, Response
from ..db import db
from ..lib import hub as H, notify
from ..lib.auth import is_staff
from ..lib.security import limited, audit

bp = Blueprint('hub', __name__, url_prefix='/teachers')

def hub_required(fn):
    @functools.wraps(fn)
    def w(*a, **kw):
        if not g.user:
            flash('Please log in with your teacher account.', 'info')
            return redirect(url_for('auth.login', next=request.full_path))
        if not H.is_hub_user():
            return render_template('hub/gate.html'), 403
        if g.user['account_type'] == 'teacher': g.hub_member = H.member(g.user['id'])
        return fn(*a, **kw)
    return w

@bp.app_context_processor
def _hub_counts():
    u = getattr(g, 'user', None)
    if not (u and u['account_type'] == 'teacher' and request.endpoint and request.endpoint.split('.')[0] in ('hub', 'dashboard', 'teachers', 'auth', 'privacy')):
        return {}
    return {'hub_unread': H.unread_messages(u['id']), 'hub_requests': H.pending_requests(u['id']), 'hub_member': getattr(g, 'hub_member', None)}

def _int(v, default=0, lo=0, hi=10**6):
    try: return max(lo, min(hi, int(v)))
    except (TypeError, ValueError): return default

@bp.route('/hub')
@hub_required
def home():
    return redirect(url_for('dashboard.home'))

def dashboard_context(uid):
    """Widgets for the teacher dashboard (dashboard.home renders them alongside profile, CV and applications)."""
    m = H.member(uid)
    learning = db.all("""SELECT c.id, c.slug, c.title, c.category, (SELECT count(*) FROM course_lessons l WHERE l.course_id = c.id) total,
                         (SELECT count(*) FROM lesson_progress p JOIN course_lessons l ON l.id = p.lesson_id WHERE l.course_id = c.id AND p.user_id = %s) done
                         FROM course_enrolments e JOIN courses c ON c.id = e.course_id WHERE e.user_id = %s AND e.completed_at IS NULL
                         ORDER BY e.enrolled_at DESC LIMIT 4""", uid, uid)
    weeks = {r['wk']: r['n'] for r in db.all("""SELECT to_char(date_trunc('week', done_at), 'YYYY-MM-DD') wk, count(*) n FROM lesson_progress
                                                WHERE user_id = %s AND done_at >= now() - interval '56 days' GROUP BY 1""", uid)}
    monday = datetime.date.today() - datetime.timedelta(days=datetime.date.today().weekday())
    activity = [{'label': (monday - datetime.timedelta(weeks=i)).strftime('%d %b'), 'n': weeks.get((monday - datetime.timedelta(weeks=i)).isoformat(), 0)} for i in range(7, -1, -1)]
    peak = max([a['n'] for a in activity] + [1])
    return dict(
        hub_member=m, cpd=H.cpd(uid), learning=learning, activity=activity, peak=peak,
        hub_stats=dict(
            enrolled=db.val('SELECT count(*) FROM course_enrolments WHERE user_id = %s', uid),
            completed=db.val('SELECT count(*) FROM course_enrolments WHERE user_id = %s AND completed_at IS NOT NULL', uid),
            connections=db.val("SELECT count(*) FROM connections WHERE status = 'accepted' AND (requester_id = %s OR addressee_id = %s)", uid, uid),
            plans=db.val('SELECT count(*) FROM lesson_plans WHERE user_id = %s', uid)),
        upcoming=db.all("""SELECT e.*, EXISTS (SELECT 1 FROM event_registrations r WHERE r.event_id = e.id AND r.user_id = %s AND r.status IN ('confirmed','requested')) registered
                           FROM events e WHERE e.status = 'published' AND e.starts_at > now() AND e.kind IN ('workshop','webinar') AND 'teachers' = ANY(e.audience)
                           ORDER BY e.starts_at LIMIT 3""", uid),
        next_plans=db.all('SELECT id, title, subject, grade, plan_date FROM lesson_plans WHERE user_id = %s AND plan_date >= current_date ORDER BY plan_date LIMIT 3', uid),
        discussions=db.all("""SELECT p.id, p.title, p.community, p.comment_count, p.created_at, c.name AS community_name, u.name AS author FROM posts p
                              JOIN communities c ON c.slug = p.community LEFT JOIN users u ON u.id = p.user_id
                              WHERE p.status = 'published' AND p.community = ANY(%s) AND u.status = 'active' ORDER BY p.created_at DESC LIMIT 4""", H.HUB_SLUGS))

# ================================================================ UPSKILLING
@bp.route('/learn')
@hub_required
def courses():
    cat = request.args.get('category', '')
    uid = g.user['id']
    rows = db.all("""SELECT c.*, (SELECT count(*) FROM course_lessons l WHERE l.course_id = c.id) lessons,
                     (SELECT COALESCE(sum(minutes), 0) FROM course_lessons l WHERE l.course_id = c.id) minutes,
                     e.enrolled_at, e.completed_at,
                     (SELECT count(*) FROM lesson_progress p JOIN course_lessons l ON l.id = p.lesson_id WHERE l.course_id = c.id AND p.user_id = %s) done
                     FROM courses c LEFT JOIN course_enrolments e ON e.course_id = c.id AND e.user_id = %s
                     WHERE c.published AND (%s = '' OR c.category = %s) ORDER BY c.sort, c.id""", uid, uid, cat, cat)
    cats = [r['category'] for r in db.all('SELECT DISTINCT category FROM courses WHERE published ORDER BY 1')]
    return render_template('hub/courses.html', rows=rows, cats=cats, cat=cat, cpd=H.cpd(uid))

@bp.route('/learn/<slug>')
@hub_required
def course(slug):
    c = db.one('SELECT * FROM courses WHERE slug = %s AND published', slug) or abort(404)
    uid = g.user['id']
    enr = db.one('SELECT * FROM course_enrolments WHERE user_id = %s AND course_id = %s', uid, c['id'])
    lessons = db.all("""SELECT l.*, EXISTS (SELECT 1 FROM lesson_progress p WHERE p.lesson_id = l.id AND p.user_id = %s) done
                        FROM course_lessons l WHERE l.course_id = %s ORDER BY l.position""", uid, c['id'])
    if not lessons: abort(404)
    pos = _int(request.args.get('lesson'), 0)
    if not pos:   # resume at the first unfinished lesson
        pos = next((l['position'] for l in lessons if not l['done']), lessons[0]['position'])
    cur = next((l for l in lessons if l['position'] == pos), lessons[0])
    locked = not enr and cur['position'] != lessons[0]['position']     # first lesson is a free preview
    return render_template('hub/course.html', c=c, enr=enr, lessons=lessons, cur=cur, locked=locked,
                           done=sum(1 for l in lessons if l['done']))

@bp.route('/learn/<slug>/enrol', methods=['POST'])
@hub_required
@limited(30, 3600, 'hub_enrol')
def enrol(slug):
    c = db.one('SELECT * FROM courses WHERE slug = %s AND published', slug) or abort(404)
    db.run('INSERT INTO course_enrolments (user_id, course_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', g.user['id'], c['id'])
    flash(f"You're enrolled in “{c['title']}”. Complete every lesson to earn your {c['cpd_hours']}-hour CPD certificate.", 'success')
    return redirect(url_for('hub.course', slug=slug))

@bp.route('/learn/lesson/<int:lid>/done', methods=['POST'])
@hub_required
@limited(120, 3600, 'hub_lesson')
def lesson_done(lid):
    uid = g.user['id']
    l = db.one('SELECT l.*, c.slug, c.title AS course_title, c.cpd_hours FROM course_lessons l JOIN courses c ON c.id = l.course_id WHERE l.id = %s AND c.published', lid) or abort(404)
    enr = db.one('SELECT * FROM course_enrolments WHERE user_id = %s AND course_id = %s', uid, l['course_id'])
    if not enr:
        flash('Enrol in the course first.', 'error'); return redirect(url_for('hub.course', slug=l['slug']))
    with db.transaction():
        db.run('INSERT INTO lesson_progress (user_id, lesson_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', uid, lid)
        left = db.val("""SELECT count(*) FROM course_lessons l WHERE l.course_id = %s
                         AND NOT EXISTS (SELECT 1 FROM lesson_progress p WHERE p.lesson_id = l.id AND p.user_id = %s)""", l['course_id'], uid)
        if left == 0 and not enr['completed_at']:
            code = H.new_certificate_code()
            db.run('UPDATE course_enrolments SET completed_at = now(), certificate_code = %s WHERE user_id = %s AND course_id = %s AND completed_at IS NULL', code, uid, l['course_id'])
            notify.notify(uid, 'Certificate ready 🎓', f"You completed “{l['course_title']}” — {l['cpd_hours']} CPD hours added.", url_for('hub.certificate', code=code))
            audit('hub.course_completed', 'course', l['course_id'], {'code': code})
            flash(f"Congratulations! You completed “{l['course_title']}”. Your certificate is ready.", 'success')
            return redirect(url_for('hub.certificate', code=code))
    nxt = db.val('SELECT position FROM course_lessons WHERE course_id = %s AND position > %s ORDER BY position LIMIT 1', l['course_id'], l['position'])
    return redirect(url_for('hub.course', slug=l['slug'], lesson=nxt or l['position']))

@bp.route('/certificates')
@hub_required
def certificates():
    rows = db.all("""SELECT c.title, c.slug, c.cpd_hours, c.instructor, e.completed_at, e.certificate_code FROM course_enrolments e JOIN courses c ON c.id = e.course_id
                     WHERE e.user_id = %s AND e.completed_at IS NOT NULL ORDER BY e.completed_at DESC""", g.user['id'])
    events = db.all("""SELECT e.title, e.slug, e.cpd_hours, e.starts_at, r.status FROM event_registrations r JOIN events e ON e.id = r.event_id
                       WHERE r.user_id = %s AND e.cpd_hours > 0 AND (r.status = 'attended' OR (r.status = 'confirmed' AND COALESCE(e.ends_at, e.starts_at) < now()))
                       ORDER BY e.starts_at DESC""", g.user['id'])
    return render_template('hub/certificates.html', rows=rows, events=events, cpd=H.cpd(g.user['id']))

@bp.route('/certificates/<code>')
def certificate(code):
    """Printable certificate. Public by design: anyone holding the code can verify it (it shows name, course, hours, date only)."""
    if len(code) > 24: abort(404)
    with db.elevated():
        r = db.one("""SELECT u.name, c.title, c.cpd_hours, c.instructor, e.completed_at, e.certificate_code, e.user_id FROM course_enrolments e
                      JOIN users u ON u.id = e.user_id JOIN courses c ON c.id = e.course_id WHERE e.certificate_code = %s AND u.status = 'active'""", code.upper())
    if not r: abort(404)
    return render_template('hub/certificate.html', r=r, own=bool(g.user and g.user['id'] == r['user_id']))

@bp.route('/certificates/verify')
@limited(30, 600, 'cert_verify')
def verify():
    code = (request.args.get('code') or '').strip().upper()[:24]
    r = None
    if code:
        with db.elevated():
            r = db.one("""SELECT u.name, c.title, c.cpd_hours, e.completed_at FROM course_enrolments e JOIN users u ON u.id = e.user_id
                          JOIN courses c ON c.id = e.course_id WHERE e.certificate_code = %s AND u.status = 'active'""", code)
    return render_template('hub/verify.html', code=code, r=r)

# ================================================================ WORKSHOPS (events for teachers)
@bp.route('/workshops')
@hub_required
def workshops():
    uid = g.user['id']
    rows = db.all("""SELECT e.*, (SELECT COALESCE(sum(attendees), 0) FROM event_registrations r WHERE r.event_id = e.id AND r.status IN ('confirmed','requested')) taken,
                     (SELECT r.status FROM event_registrations r WHERE r.event_id = e.id AND r.user_id = %s AND r.status <> 'cancelled' ORDER BY r.id DESC LIMIT 1) my_status
                     FROM events e WHERE e.status = 'published' AND e.starts_at > now() AND e.kind IN ('workshop','webinar','meetup')
                     AND ('teachers' = ANY(e.audience) OR e.cpd_hours > 0) ORDER BY e.starts_at LIMIT 60""", uid)
    return render_template('hub/workshops.html', rows=rows)

# ================================================================ NETWORK
@bp.route('/network')
@hub_required
def network():
    uid = g.user['id']
    q = (request.args.get('q') or '').strip()[:60].replace('%', '').replace('_', ' ')
    like = f'%{q}%'
    rows = db.all(f"""SELECT {H.PUBLIC_COLS},
                      (SELECT c.status FROM connections c WHERE LEAST(c.requester_id, c.addressee_id) = LEAST(u.id, %s::bigint) AND GREATEST(c.requester_id, c.addressee_id) = GREATEST(u.id, %s::bigint)) conn_status,
                      (SELECT CASE WHEN c.requester_id = %s THEN 'out' ELSE 'in' END FROM connections c WHERE LEAST(c.requester_id, c.addressee_id) = LEAST(u.id, %s::bigint) AND GREATEST(c.requester_id, c.addressee_id) = GREATEST(u.id, %s::bigint)) direction
                      FROM hub_members m JOIN users u ON u.id = m.user_id
                      WHERE u.status = 'active' AND u.account_type = 'teacher' AND m.directory_visible AND u.id <> %s
                      AND (%s = '' OR u.name ILIKE %s OR m.subjects ILIKE %s OR u.city ILIKE %s OR u.state ILIKE %s OR m.school ILIKE %s OR m.designation ILIKE %s)
                      ORDER BY (m.mentor_status = 'approved') DESC, m.experience_years DESC LIMIT 60""",
                  uid, uid, uid, uid, uid, uid, q, like, like, like, like, like, like)
    return render_template('hub/network.html', rows=rows, q=q, me=g.hub_member if hasattr(g, 'hub_member') else None)

@bp.route('/network/connections')
@hub_required
def connections():
    uid = g.user['id']
    cols = 'c.id AS cid, c.status, c.created_at, u.id, u.name, u.city, m.designation, m.school, m.subjects'
    other = 'CASE WHEN c.requester_id = %s THEN c.addressee_id ELSE c.requester_id END'
    return render_template('hub/connections.html',
        accepted=db.all(f"""SELECT {cols} FROM connections c JOIN users u ON u.id = {other} LEFT JOIN hub_members m ON m.user_id = u.id
                            WHERE c.status = 'accepted' AND (c.requester_id = %s OR c.addressee_id = %s) AND u.status = 'active' ORDER BY u.name""", uid, uid, uid),
        incoming=db.all(f"""SELECT {cols} FROM connections c JOIN users u ON u.id = c.requester_id LEFT JOIN hub_members m ON m.user_id = u.id
                            WHERE c.status = 'pending' AND c.addressee_id = %s ORDER BY c.created_at DESC""", uid),
        outgoing=db.all(f"""SELECT {cols} FROM connections c JOIN users u ON u.id = c.addressee_id LEFT JOIN hub_members m ON m.user_id = u.id
                            WHERE c.status = 'pending' AND c.requester_id = %s ORDER BY c.created_at DESC""", uid))

@bp.route('/network/connect/<int:other>', methods=['POST'])
@hub_required
@limited(40, 3600, 'hub_connect')
def connect(other):
    uid = g.user['id']
    if other == uid: abort(400)
    if not H.public_member(other): abort(404)
    c = H.connection(uid, other)
    if c:
        if c['status'] == 'pending' and c['addressee_id'] == uid:
            db.run("UPDATE connections SET status = 'accepted', responded_at = now() WHERE id = %s", c['id'])
            notify.notify(other, 'Connection accepted', f"{g.user['name']} accepted your connection request.", url_for('hub.thread', other=uid))
            flash('Connected. You can now message each other.', 'success')
        else:
            flash('Request already sent.' if c['status'] != 'accepted' else 'You are already connected.', 'info')
    else:
        db.run('INSERT INTO connections (requester_id, addressee_id) VALUES (%s,%s)', uid, other)
        notify.notify(other, 'New connection request', f"{g.user['name']} wants to connect with you on the Teachers Hub.", url_for('hub.connections'))
        flash('Connection request sent.', 'success')
    return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for('hub.network'))

@bp.route('/network/respond/<int:cid>', methods=['POST'])
@hub_required
def respond(cid):
    c = db.one("SELECT * FROM connections WHERE id = %s AND addressee_id = %s AND status = 'pending'", cid, g.user['id']) or abort(404)
    accept = request.form.get('action') == 'accept'
    db.run('UPDATE connections SET status = %s, responded_at = now() WHERE id = %s', 'accepted' if accept else 'declined', cid)
    if accept:
        notify.notify(c['requester_id'], 'Connection accepted', f"{g.user['name']} accepted your connection request.", url_for('hub.thread', other=g.user['id']))
    flash('Connected.' if accept else 'Request declined.', 'success' if accept else 'info')
    return redirect(url_for('hub.connections'))

@bp.route('/network/remove/<int:cid>', methods=['POST'])
@hub_required
def remove_connection(cid):
    n = db.run('DELETE FROM connections WHERE id = %s AND (requester_id = %s OR addressee_id = %s)', cid, g.user['id'], g.user['id'])
    if n: audit('hub.connection_removed', 'connection', cid)
    flash('Connection removed. You will no longer be able to message each other.', 'info')
    return redirect(url_for('hub.connections'))

# ---------------- messages (encrypted at rest; only between connections or active mentor pairs)
@bp.route('/messages')
@hub_required
def messages():
    uid = g.user['id']
    rows = db.all("""SELECT other.id, other.name, m.designation, d.body_enc, d.created_at, d.sender_id,
                     (SELECT count(*) FROM direct_messages x WHERE x.sender_id = other.id AND x.recipient_id = %s AND x.read_at IS NULL) unread
                     FROM (SELECT CASE WHEN sender_id = %s THEN recipient_id ELSE sender_id END other_id, max(id) mid FROM direct_messages
                           WHERE sender_id = %s OR recipient_id = %s GROUP BY 1) t
                     JOIN direct_messages d ON d.id = t.mid JOIN users other ON other.id = t.other_id LEFT JOIN hub_members m ON m.user_id = other.id
                     ORDER BY d.id DESC LIMIT 100""", uid, uid, uid, uid)
    for r in rows: r['preview'] = H.unseal(r.pop('body_enc'))[:90]
    return render_template('hub/messages.html', rows=rows)

@bp.route('/messages/<int:other>', methods=['GET', 'POST'])
@hub_required
def thread(other):
    uid = g.user['id']
    person = db.one("""SELECT u.id, u.name, u.city, m.designation, m.school FROM users u LEFT JOIN hub_members m ON m.user_id = u.id
                       WHERE u.id = %s AND u.status = 'active' AND u.account_type = 'teacher'""", other)
    if not person or other == uid: abort(404)
    allowed = H.can_message(uid, other)
    has_history = db.val('SELECT 1 FROM direct_messages WHERE (sender_id = %s AND recipient_id = %s) OR (sender_id = %s AND recipient_id = %s) LIMIT 1', uid, other, other, uid)
    if not allowed and not has_history: abort(404)       # strangers cannot even open a thread
    if request.method == 'POST':
        if not allowed: abort(403)
        if not security_ok_to_send(uid):
            flash('You are sending messages too quickly. Please wait a little.', 'error'); return redirect(url_for('hub.thread', other=other))
        body = (request.form.get('body') or '').strip()[:2000]
        if body:
            db.run('INSERT INTO direct_messages (sender_id, recipient_id, body_enc) VALUES (%s,%s,%s)', uid, other, H.seal(body))
            if not db.val("SELECT 1 FROM notifications WHERE user_id = %s AND title = 'New message' AND read_at IS NULL AND created_at > now() - interval '1 hour'", other):
                notify.notify(other, 'New message', f"{g.user['name']} sent you a message.", url_for('hub.thread', other=uid))
        return redirect(url_for('hub.thread', other=other) + '#end')
    db.run('UPDATE direct_messages SET read_at = now() WHERE sender_id = %s AND recipient_id = %s AND read_at IS NULL', other, uid)
    msgs = db.all("""SELECT id, sender_id, body_enc, created_at FROM direct_messages WHERE (sender_id = %s AND recipient_id = %s) OR (sender_id = %s AND recipient_id = %s)
                     ORDER BY id DESC LIMIT 200""", uid, other, other, uid)[::-1]
    for m in msgs: m['body'] = H.unseal(m.pop('body_enc'))
    return render_template('hub/thread.html', person=person, msgs=msgs, allowed=allowed)

def security_ok_to_send(uid):
    """60 private messages an hour per teacher (spam / harassment brake), shared across all servers."""
    from flask import current_app
    from ..lib.security import rate_limit
    if current_app.testing and not current_app.config.get('ENFORCE_RATE_LIMITS'): return True
    return rate_limit(f'dm:{uid}', 60, 3600)

# ================================================================ COMMUNITIES
@bp.route('/communities')
@hub_required
def communities():
    rows = db.all("""SELECT c.*, (SELECT count(*) FROM posts p WHERE p.community = c.slug AND p.status = 'published') posts,
                     (SELECT max(p.created_at) FROM posts p WHERE p.community = c.slug AND p.status = 'published') last_post
                     FROM communities c WHERE c.slug = ANY(%s)""", H.HUB_SLUGS)
    order = {s: i for i, s in enumerate(H.HUB_SLUGS)}; icons = {c[0]: c[3] for c in H.HUB_COMMUNITIES}
    rows.sort(key=lambda r: order[r['slug']])
    for r in rows: r['icon'] = icons[r['slug']]
    return render_template('hub/communities.html', rows=rows)

# ================================================================ MENTORSHIP
@bp.route('/mentors')
@hub_required
def mentors():
    uid = g.user['id']
    rows = db.all(f"""SELECT {H.PUBLIC_COLS} FROM hub_members m JOIN users u ON u.id = m.user_id
                      WHERE m.mentor_status = 'approved' AND m.open_to_mentor AND u.status = 'active' AND u.id <> %s ORDER BY m.experience_years DESC""", uid)
    mine = db.all("""SELECT ms.*, a.name AS mentee_name, b.name AS mentor_name FROM mentorships ms JOIN users a ON a.id = ms.mentee_id JOIN users b ON b.id = ms.mentor_id
                     WHERE ms.mentee_id = %s OR ms.mentor_id = %s ORDER BY ms.updated_at DESC""", uid, uid)
    return render_template('hub/mentors.html', rows=rows, mine=mine, me=getattr(g, 'hub_member', None))

@bp.route('/mentors/<int:mentor>/request', methods=['POST'])
@hub_required
@limited(5, 86400, 'hub_mentor_req')
def request_mentor(mentor):
    uid = g.user['id']
    m = db.one("SELECT * FROM hub_members WHERE user_id = %s AND mentor_status = 'approved' AND open_to_mentor", mentor)
    if not m or mentor == uid: abort(404)
    topic = (request.form.get('topic') or '').strip()[:120]; msg = (request.form.get('message') or '').strip()[:1500]
    if len(topic) < 3 or len(msg) < 20:
        flash('Please add a topic and a few lines about what you would like help with.', 'error'); return redirect(url_for('hub.mentors'))
    if db.val("SELECT 1 FROM mentorships WHERE mentee_id = %s AND mentor_id = %s AND status IN ('requested','active')", uid, mentor):
        flash('You already have an open request with this mentor.', 'info'); return redirect(url_for('hub.mentors'))
    db.insert('mentorships', dict(mentee_id=uid, mentor_id=mentor, topic=topic, message=msg), returning=None)
    notify.notify(mentor, 'New mentorship request', f"{g.user['name']}: {topic}", url_for('hub.mentors'))
    flash('Request sent. You will be notified when the mentor responds.', 'success')
    return redirect(url_for('hub.mentors'))

@bp.route('/mentorships/<int:mid>/<action>', methods=['POST'])
@hub_required
def mentorship_action(mid, action):
    uid = g.user['id']
    ms = db.one('SELECT * FROM mentorships WHERE id = %s AND (mentor_id = %s OR mentee_id = %s)', mid, uid, uid) or abort(404)
    rules = {'accept': ('mentor_id', ('requested',), 'active'), 'decline': ('mentor_id', ('requested',), 'declined'),
             'complete': (None, ('active',), 'completed'), 'withdraw': ('mentee_id', ('requested',), 'declined')}
    if action not in rules: abort(404)
    who, frm, to = rules[action]
    if (who and ms[who] != uid) or ms['status'] not in frm: abort(403)
    db.run('UPDATE mentorships SET status = %s, updated_at = now() WHERE id = %s', to, mid)
    other = ms['mentee_id'] if uid == ms['mentor_id'] else ms['mentor_id']
    notify.notify(other, f'Mentorship {to}', f"“{ms['topic']}” is now {to}.", url_for('hub.mentors'))
    flash({'active': 'Mentorship started — you can now message each other.', 'declined': 'Request closed.', 'completed': 'Mentorship marked complete. Thank you!'}[to], 'success')
    return redirect(url_for('hub.mentors'))

# ================================================================ TUTORIALS
@bp.route('/tutorials')
@hub_required
def tutorials():
    q = (request.args.get('q') or '').strip()[:60]; cat = request.args.get('category', '')
    saved_only = request.args.get('saved') == '1'
    rows = db.all("""SELECT t.id, t.slug, t.title, t.category, t.summary, t.minutes, COALESCE(s.saved, false) saved
                     FROM tutorials t LEFT JOIN tutorial_saves s ON s.tutorial_id = t.id AND s.user_id = %s
                     WHERE t.published AND (%s = '' OR t.category = %s) AND (%s = '' OR t.title ILIKE %s OR t.summary ILIKE %s)
                     AND (NOT %s OR s.saved) ORDER BY t.category, t.title""",
                  g.user['id'], cat, cat, q, f'%{q}%', f'%{q}%', saved_only)
    cats = [r['category'] for r in db.all('SELECT DISTINCT category FROM tutorials WHERE published ORDER BY 1')]
    return render_template('hub/tutorials.html', rows=rows, cats=cats, cat=cat, q=q, saved_only=saved_only, icons=H.TUTORIAL_ICONS)

@bp.route('/tutorials/<slug>')
@hub_required
def tutorial(slug):
    t = db.one('SELECT * FROM tutorials WHERE slug = %s AND published', slug) or abort(404)
    db.run("""INSERT INTO tutorial_saves (user_id, tutorial_id) VALUES (%s,%s) ON CONFLICT (user_id, tutorial_id) DO UPDATE SET viewed_at = now()""", g.user['id'], t['id'])
    saved = db.val('SELECT saved FROM tutorial_saves WHERE user_id = %s AND tutorial_id = %s', g.user['id'], t['id'])
    more = db.all('SELECT slug, title, minutes FROM tutorials WHERE published AND category = %s AND id <> %s ORDER BY title LIMIT 4', t['category'], t['id'])
    return render_template('hub/tutorial.html', t=t, saved=saved, more=more, icons=H.TUTORIAL_ICONS)

@bp.route('/tutorials/<slug>/save', methods=['POST'])
@hub_required
def tutorial_save(slug):
    t = db.one('SELECT id FROM tutorials WHERE slug = %s AND published', slug) or abort(404)
    db.run("""INSERT INTO tutorial_saves (user_id, tutorial_id, saved) VALUES (%s,%s,true)
              ON CONFLICT (user_id, tutorial_id) DO UPDATE SET saved = NOT tutorial_saves.saved""", g.user['id'], t['id'])
    return redirect(url_for('hub.tutorial', slug=slug))

# ================================================================ LESSON PLANNER (private to the teacher)
PLAN_FIELDS = ('title', 'subject', 'grade', 'plan_date', 'duration_min', 'objectives', 'materials', 'activities', 'assessment', 'reflection')
PLAN_MAX = {'title': 160, 'subject': 80, 'grade': 40, 'objectives': 3000, 'materials': 2000, 'activities': 6000, 'assessment': 3000, 'reflection': 3000}

@bp.route('/planner')
@hub_required
def planner():
    rows = db.all("""SELECT * FROM lesson_plans WHERE user_id = %s ORDER BY (plan_date IS NULL), (plan_date < current_date), plan_date, id DESC""", g.user['id'])
    return render_template('hub/planner.html', rows=rows, today=datetime.date.today())

def _plan_from_form(f):
    d = {k: (f.get(k) or '').strip()[:PLAN_MAX.get(k, 200)] for k in PLAN_FIELDS if k not in ('plan_date', 'duration_min')}
    try: d['plan_date'] = datetime.date.fromisoformat(f.get('plan_date')) if f.get('plan_date') else None
    except ValueError: d['plan_date'] = None
    d['duration_min'] = _int(f.get('duration_min'), 40, 5, 480)
    return d

@bp.route('/planner/new', methods=['GET', 'POST'])
@bp.route('/planner/<int:pid>', methods=['GET', 'POST'])
@hub_required
def plan_edit(pid=None):
    p = db.one('SELECT * FROM lesson_plans WHERE id = %s AND user_id = %s', pid, g.user['id']) if pid else None
    if pid and not p: abort(404)
    if request.method == 'POST':
        if request.form.get('delete') and p:
            db.run('DELETE FROM lesson_plans WHERE id = %s AND user_id = %s', pid, g.user['id'])
            flash('Lesson plan deleted.', 'info'); return redirect(url_for('hub.planner'))
        d = _plan_from_form(request.form)
        if len(d['title']) < 3:
            flash('Give your lesson plan a title.', 'error'); return render_template('hub/plan_edit.html', p=dict(p or {}, **d))
        if p:
            sets = ', '.join(f'{k} = %s' for k in d)
            db.run(f'UPDATE lesson_plans SET {sets}, updated_at = now() WHERE id = %s AND user_id = %s', *d.values(), pid, g.user['id'])
        else:
            pid = db.insert('lesson_plans', dict(user_id=g.user['id'], **d))
        flash('Lesson plan saved.', 'success')
        return redirect(url_for('hub.plan_edit', pid=pid))
    return render_template('hub/plan_edit.html', p=p or {'duration_min': 40, 'plan_date': request.args.get('date')})

@bp.route('/planner/<int:pid>/print')
@hub_required
def plan_print(pid):
    p = db.one('SELECT * FROM lesson_plans WHERE id = %s AND user_id = %s', pid, g.user['id']) or abort(404)
    return render_template('hub/plan_print.html', p=p)

# ================================================================ WELLBEING & HUB PROFILE
@bp.route('/wellbeing')
@hub_required
def wellbeing():
    t = db.all("SELECT slug, title, minutes FROM tutorials WHERE published AND category = 'Wellbeing & Workload' ORDER BY title")
    c = db.one("SELECT slug, title FROM courses WHERE published AND category ILIKE '%%wellbeing%%' ORDER BY sort LIMIT 1")
    return render_template('hub/wellbeing.html', tutorials=t, course=c)

@bp.route('/hub/profile', methods=['GET', 'POST'])
@hub_required
def profile():
    if g.user['account_type'] != 'teacher': abort(403)
    m = g.hub_member
    if request.method == 'POST':
        f = request.form
        d = dict(designation=f.get('designation', '').strip()[:120], school=f.get('school', '').strip()[:160], subjects=f.get('subjects', '').strip()[:200],
                 grades=f.get('grades', '').strip()[:120], board=f.get('board', '').strip()[:120], bio=f.get('bio', '').strip()[:600],
                 experience_years=_int(f.get('experience_years'), 0, 0, 60), cpd_goal=_int(f.get('cpd_goal'), 50, 1, 500),
                 directory_visible=f.get('directory_visible') == 'on', open_to_mentor=f.get('open_to_mentor') == 'on')
        status = m['mentor_status']
        if d['open_to_mentor'] and status in ('none', 'rejected'):
            status = 'pending'
            notify.notify_staff('Mentor application', f"{g.user['name']} offered to mentor teachers.", url_for('admin.teachers_hub'))
        d['mentor_status'] = status
        sets = ', '.join(f'{k} = %s' for k in d)
        db.run(f'UPDATE hub_members SET {sets}, updated_at = now() WHERE user_id = %s', *d.values(), g.user['id'])
        if d['directory_visible'] != m['directory_visible']:
            from ..lib import consent
            consent.record('hub_directory', d['directory_visible'], user_id=g.user['id'], method='hub_profile')
        audit('hub.profile_updated', 'user', g.user['id'], {'directory_visible': d['directory_visible'], 'mentor': d['open_to_mentor']})
        flash('Hub profile saved.' + (' Your mentor application is with our team for a quick check.' if status == 'pending' and m['mentor_status'] != 'pending' else ''), 'success')
        return redirect(url_for('hub.profile'))
    return render_template('hub/profile.html', m=m)
