"""Teachers Hub — the professional home for teachers inside The School Expert™ (formerly the standalone TeachersInn app).

One account, one database, one security model: a teacher account gets the Hub (upskilling + CPD certificates, workshops,
educator network and private messages, subject communities, mentorship, tutorials, lesson planner, careers, support).
No student / child data is collected anywhere in the Hub.
"""
import json, os, re, secrets, datetime
from flask import g
from ..db import db
from .security import encrypt_json, decrypt_json

CERT_PREFIX = 'TSE-C-'

# Subject & role communities (rows in `communities`, so moderation, reporting and the admin tools all apply).
HUB_COMMUNITIES = [
    ('teachers', 'Teachers Community', 'The whole-staffroom conversation: lesson ideas, classroom strategies and professional growth.', '✎'),
    ('teachers-foundational', 'Primary & Foundational', 'Play-based learning, FLN, early-years classrooms.', '◐'),
    ('teachers-maths', 'Mathematics Teachers', 'Problem-solving, manipulatives, competency-based maths.', '∑'),
    ('teachers-science', 'Science & STEM', 'Experiments, labs, tinkering and inquiry.', '⚗'),
    ('teachers-languages', 'Languages & Literature', 'Reading, writing, multilingual classrooms.', '❝'),
    ('teachers-social-science', 'Social Science', 'History, geography, civics and economics.', '⌖'),
    ('teachers-leaders', 'Coordinators & HoDs', 'Academic coordinators, heads of department and aspiring school leaders on leading teams.', '◆'),
    ('teachers-edtech', 'EdTech & AI', 'Digital tools, AI in teaching, online learning.', '⌘'),
    ('special-education', 'Special Education & Inclusion', 'Special educators and inclusive-education practitioners — supporting every learner.', '❖'),
]
HUB_SLUGS = [c[0] for c in HUB_COMMUNITIES]

TUTORIAL_ICONS = {'Lesson Planning': '🗒️', 'Assessment': '✅', 'EdTech': '💻', 'Classroom Practice': '🏫', 'Inclusion': '🤝',
                  'Parent Communication': '💬', 'School Operations': '🧭', 'Wellbeing & Workload': '🌿'}

def slugify(s, n=70): return re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')[:n]

def is_hub_user():
    u = getattr(g, 'user', None)
    return bool(u and u['account_type'] in ('teacher', 'admin', 'staff'))

# ---------- members ----------
def _years(v):
    m = re.search(r'(\d+)', v or '')
    return int(m.group(1)) if m else 0

def member(uid, create=True):
    """The Hub profile for a teacher; created on first use and pre-filled from the teacher registration (never published
    until the teacher opts in to the directory)."""
    m = db.one('SELECT * FROM hub_members WHERE user_id = %s', uid)
    if m or not create: return m
    with db.elevated():
        reg = db.one("SELECT answers FROM registrations WHERE form_slug = 'teacher-registration' AND user_id = %s ORDER BY id DESC LIMIT 1", uid)
    a = (reg or {}).get('answers') or {}
    j = lambda v: ', '.join(v) if isinstance(v, list) else (v or '')
    db.run("""INSERT INTO hub_members (user_id, designation, school, subjects, grades, board, experience_years, bio)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO NOTHING""",
           uid, (a.get('current_designation') or '')[:120], (a.get('current_school_organisation') or '')[:160], j(a.get('subjects_you_teach'))[:200],
           j(a.get('grades_levels_taught'))[:120], j(a.get('boards_curricula_experience'))[:120], min(_years(a.get('total_teaching_experience')), 60),
           (a.get('about_me') or '')[:600])
    return db.one('SELECT * FROM hub_members WHERE user_id = %s', uid)

PUBLIC_COLS = 'u.id, u.name, u.city, u.state, m.designation, m.school, m.subjects, m.grades, m.board, m.experience_years, m.bio, m.open_to_mentor, m.mentor_status'

def public_member(uid):
    """What another teacher may see: only members who opted in to the directory (or are an approved mentor)."""
    return db.one(f"""SELECT {PUBLIC_COLS} FROM hub_members m JOIN users u ON u.id = m.user_id
                      WHERE m.user_id = %s AND u.status = 'active' AND u.account_type = 'teacher'
                      AND (m.directory_visible OR m.mentor_status = 'approved')""", uid)

# ---------- CPD ----------
def cpd(uid):
    with db.elevated():   # own records only (uid is always the signed-in user)
        courses = db.val("""SELECT COALESCE(sum(c.cpd_hours), 0) FROM course_enrolments e JOIN courses c ON c.id = e.course_id
                            WHERE e.user_id = %s AND e.completed_at >= date_trunc('year', now())""", uid)
        events = db.val("""SELECT COALESCE(sum(e.cpd_hours), 0) FROM event_registrations r JOIN events e ON e.id = r.event_id
                           WHERE r.user_id = %s AND (r.status = 'attended' OR (r.status = 'confirmed' AND COALESCE(e.ends_at, e.starts_at) < now()))
                           AND e.starts_at >= date_trunc('year', now())""", uid)
    return {'courses': int(courses), 'workshops': int(events), 'total': int(courses) + int(events)}

def new_certificate_code():
    return CERT_PREFIX + secrets.token_hex(5).upper()

# ---------- network ----------
def connection(a, b):
    return db.one('SELECT * FROM connections WHERE LEAST(requester_id, addressee_id) = LEAST(%s::bigint, %s::bigint) AND GREATEST(requester_id, addressee_id) = GREATEST(%s::bigint, %s::bigint)', a, b, a, b)

def can_message(a, b):
    c = connection(a, b)
    if c and c['status'] == 'accepted': return True
    return bool(db.val("""SELECT 1 FROM mentorships WHERE status = 'active' AND ((mentee_id = %s AND mentor_id = %s) OR (mentee_id = %s AND mentor_id = %s))""", a, b, b, a))

def seal(body): return encrypt_json({'b': body})
def unseal(blob):
    try: return decrypt_json(blob).get('b', '')
    except Exception: return '[message could not be decrypted]'

def unread_messages(uid):
    return db.val('SELECT count(*) FROM direct_messages WHERE recipient_id = %s AND read_at IS NULL', uid) or 0

def pending_requests(uid):
    return db.val("SELECT count(*) FROM connections WHERE addressee_id = %s AND status = 'pending'", uid) or 0

# ---------- seed ----------
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _content():
    return json.load(open(os.path.join(HERE, 'db', 'content', 'teachers_hub.json'), encoding='utf-8'))

def seed_content():
    """Courses, lessons, tutorials and Hub communities. Idempotent; never overwrites edits made in the admin."""
    d = _content()
    for i, c in enumerate(d['COURSES']):
        slug = slugify(c['title'])
        cid = db.val("""INSERT INTO courses (slug, title, category, level, summary, instructor, cpd_hours, sort) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (slug) DO NOTHING RETURNING id""", slug, c['title'], c['category'], c['level'], c['summary'], c['instructor'], c['cpd'], (i + 1) * 10)
        if cid:
            for pos, (title, minutes, body) in enumerate(c['lessons'], 1):
                db.run('INSERT INTO course_lessons (course_id, position, title, minutes, body) VALUES (%s,%s,%s,%s,%s)', cid, pos, title, minutes, body)
    for t in d['TUTORIALS']:
        title, cat, summary, minutes, steps = t
        db.run("""INSERT INTO tutorials (slug, title, category, summary, minutes, steps) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (slug) DO NOTHING""",
               slugify(title), title, cat, summary, minutes, db.Json([{'title': a, 'body': b} for a, b in steps]))
    for i, (slug, name, desc, _icon) in enumerate(HUB_COMMUNITIES):
        if slug in ('teachers', 'special-education'): continue          # already part of the core community list
        db.run("""INSERT INTO communities (slug, name, description, view_roles, post_roles, premoderate, allow_comments, sort)
                  VALUES (%s,%s,%s,%s,%s,false,true,%s) ON CONFLICT (slug) DO NOTHING""",
               slug, name, desc, ['teacher', 'admin', 'staff'], ['teacher'], 11 + i)

def seed_demo(teacher_uid, user_fn, start):
    """Demo educators (mentors and peers), Hub workshops, discussions and one connection for the demo teacher."""
    d = _content()
    ids = []
    for name, desig, school, subjects, grades, board, city, state, years, role, bio in d['DEMO_EDUCATORS']:
        email = slugify(name).replace('-', '.') + '@demo.schoolexpert.in'
        uid = user_fn(email, f'{name} (Demo)', 'teacher', city=city, state=state)
        db.run("""INSERT INTO hub_members (user_id, designation, school, subjects, grades, board, experience_years, bio, directory_visible, open_to_mentor, mentor_status)
                  VALUES (%s,%s,%s,%s,%s,%s,%s,%s,true,%s,%s) ON CONFLICT (user_id) DO NOTHING""",
               uid, desig, f'{school} (Demo)', subjects, grades, board, years, bio, role == 'mentor', 'approved' if role == 'mentor' else 'none')
        ids.append(uid)
    member(teacher_uid)
    db.run('UPDATE hub_members SET directory_visible = true WHERE user_id = %s', teacher_uid)
    for title, desc, facil, cat, mode, loc, days, dur, cap, cpd_h in d['WORKSHOPS']:
        slug = slugify(title + '-demo')
        st = start + datetime.timedelta(days=days, hours=5)
        db.run("""INSERT INTO events (slug, title, kind, summary, body, audience, mode, venue, city, starts_at, ends_at, capacity, cpd_hours, facilitator, category)
                  VALUES (%s,%s,'workshop',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (slug) DO NOTHING""",
               slug, f'{title} (Demo)', desc, desc + f'\n\n**Facilitator:** {facil}', ['teachers'],
               {'Online': 'online', 'In-person': 'offline', 'Hybrid': 'hybrid'}[mode], loc, loc.split(' ')[0] if mode != 'Online' else None,
               st, st + datetime.timedelta(minutes=dur), cap, cpd_h, facil, cat)
    if not db.val("SELECT 1 FROM posts WHERE community = 'teachers-maths'"):
        for comm, who, title, body, reply in [
            ('teachers-maths', 1, 'Low-cost manipulatives for fractions?', 'I teach Grade 6 in a government school with a tight budget. What do you use to teach equivalent fractions hands-on? I have tried paper folding — looking for more ideas.',
             (0, 'Roti/chapati drawings work wonderfully for younger kids! Also strips of old calendars cut into equal parts make great fraction walls.')),
            ('teachers-edtech', 2, 'Share your best AI prompt for differentiated worksheets', 'Mine: "Create three versions of a worksheet on [topic] for Grade [x]: support, core, and challenge. Same concept, different scaffolding." What works for you?', None),
            ('teachers-foundational', 0, 'Morning circle ideas for Grade 1', 'Looking to refresh our morning circle. Currently we do a greeting song and weather chart. What else has worked for you?', None)]:
            pid = db.insert('posts', dict(community=comm, user_id=ids[who], title=title, body=body))
            if reply:
                db.insert('comments', dict(post_id=pid, user_id=ids[reply[0]], body=reply[1]), returning=None)
                db.run('UPDATE posts SET comment_count = 1 WHERE id = %s', pid)
    if not connection(teacher_uid, ids[0]):
        db.run("INSERT INTO connections (requester_id, addressee_id, status, responded_at) VALUES (%s,%s,'accepted',now())", teacher_uid, ids[0])
        db.run('INSERT INTO direct_messages (sender_id, recipient_id, body_enc) VALUES (%s,%s,%s)', ids[0], teacher_uid,
               seal('Welcome to the Teachers Hub! Happy to share my phonics games whenever you need them.'))
        db.run("INSERT INTO connections (requester_id, addressee_id) VALUES (%s,%s)", ids[4], teacher_uid)
    # some learning history so the dashboard shows real progress
    if not db.val('SELECT 1 FROM course_enrolments WHERE user_id = %s', teacher_uid):
        c1, c2 = [r['id'] for r in db.all('SELECT id FROM courses ORDER BY sort LIMIT 2')]
        db.run("INSERT INTO course_enrolments (user_id, course_id, enrolled_at, completed_at, certificate_code) VALUES (%s,%s,now() - interval '20 days',now() - interval '6 days',%s)",
               teacher_uid, c1, new_certificate_code())
        db.run("INSERT INTO lesson_progress (user_id, lesson_id, done_at) SELECT %s, id, now() - (position || ' days')::interval FROM course_lessons WHERE course_id = %s", teacher_uid, c1)
        db.run("INSERT INTO course_enrolments (user_id, course_id, enrolled_at) VALUES (%s,%s,now() - interval '3 days')", teacher_uid, c2)
        db.run("INSERT INTO lesson_progress (user_id, lesson_id) SELECT %s, id FROM course_lessons WHERE course_id = %s AND position <= 2", teacher_uid, c2)
        db.insert('lesson_plans', dict(user_id=teacher_uid, title='Equivalent fractions with paper strips', subject='Mathematics', grade='Grade 6',
                  plan_date=datetime.date.today() + datetime.timedelta(days=1), duration_min=40,
                  objectives='Students can show that 1/2 = 2/4 = 4/8 using paper strips.', materials='Coloured paper strips, scissors, chart paper',
                  activities='1. Do Now: shade 1/2 of a strip (5 min)\n2. Fold into quarters and eighths in pairs (15 min)\n3. Build a class fraction wall (15 min)',
                  assessment='Exit ticket: write two fractions equal to 3/4.'), returning=None)
    return ids
