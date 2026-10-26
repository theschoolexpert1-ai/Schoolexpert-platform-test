import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, Response, send_file
from ..db import db
from ..lib import forms as F, cv as CV, consent, crm, notify, storage, payments
from ..lib.auth import login_required, roles, is_staff
from ..lib.security import decrypt_json, limited, audit

bp = Blueprint('teachers', __name__)

def teacher_answers(uid):
    with db.elevated():   # callers render only entitled tiers / named fields
        reg = db.one("SELECT * FROM registrations WHERE form_slug = 'teacher-registration' AND user_id = %s ORDER BY id DESC LIMIT 1", uid)
    if not reg: return None, {}
    a = dict(reg['answers']); a.update(decrypt_json(reg['private_enc']))
    return reg, a

@bp.route('/teachers')
def hub():
    jobs = db.all("""SELECT j.*, o.name AS org_name FROM jobs j JOIN organisations o ON o.id = j.org_id WHERE j.status = 'published'
                     ORDER BY (j.featured_until >= current_date) DESC NULLS LAST, j.published_at DESC LIMIT 6""")
    posts = db.all("""SELECT p.*, u.name AS user_name FROM posts p LEFT JOIN users u ON u.id = p.user_id
                      WHERE p.community = 'teachers' AND p.status = 'published' ORDER BY p.created_at DESC LIMIT 5""")
    events = db.all("SELECT * FROM events WHERE status = 'published' AND starts_at > now() AND ('teachers' = ANY(audience) OR kind IN ('workshop','webinar')) ORDER BY starts_at LIMIT 3")
    profile = db.one('SELECT * FROM teacher_profiles WHERE user_id = %s', g.user['id']) if g.user and g.user['account_type'] == 'teacher' else None
    reg = db.one("SELECT id, status, progress FROM registrations WHERE form_slug = 'teacher-registration' AND user_id = %s ORDER BY id DESC LIMIT 1", g.user['id']) if g.user else None
    premium = db.one("SELECT * FROM plans WHERE code = 'teacher_premium'")
    return render_template('teachers/hub.html', jobs=jobs, posts=posts, events=events, profile=profile, reg=reg, premium=premium)

@bp.route('/jobs')
def jobs():
    a = request.args
    where = ["j.status = 'published'"]; args = []
    if a.get('q'): where.append('(j.title ILIKE %s OR j.description ILIKE %s OR o.name ILIKE %s)'); args += [f"%{a['q']}%"] * 3
    if a.get('city'): where.append('lower(j.city) = lower(%s)'); args.append(a['city'])
    if a.get('subject'): where.append('%s = ANY(j.subjects)'); args.append(a['subject'])
    if a.get('type'): where.append('j.employment_type = %s'); args.append(a['type'])
    rows = db.all(f"""SELECT j.*, o.name AS org_name, l.slug AS listing_slug, l.logo_url FROM jobs j JOIN organisations o ON o.id = j.org_id
                      LEFT JOIN listings l ON l.id = j.listing_id WHERE {' AND '.join(where)}
                      ORDER BY (j.featured_until >= current_date) DESC NULLS LAST, j.published_at DESC LIMIT 100""", *args)
    cities = [r['city'] for r in db.all("SELECT DISTINCT city FROM jobs WHERE status = 'published' AND city <> '' ORDER BY 1")]
    subjects = [r['s'] for r in db.all("SELECT DISTINCT unnest(subjects) s FROM jobs WHERE status = 'published' ORDER BY 1")]
    return render_template('teachers/jobs.html', rows=rows, a=a, cities=cities, subjects=subjects)

@bp.route('/jobs/<slug>')
def job(slug):
    j = db.one("""SELECT j.*, o.name AS org_name, l.slug AS listing_slug, l.logo_url, l.city AS school_city FROM jobs j JOIN organisations o ON o.id = j.org_id
                  LEFT JOIN listings l ON l.id = j.listing_id WHERE j.slug = %s""", slug) or abort(404)
    if j['status'] != 'published' and not (g.org and g.org['id'] == j['org_id']) and not is_staff(): abort(404)
    applied = g.user and db.one('SELECT * FROM job_applications WHERE job_id = %s AND teacher_id = %s', j['id'], g.user['id'])
    profile = db.one('SELECT * FROM teacher_profiles WHERE user_id = %s', g.user['id']) if g.user and g.user['account_type'] == 'teacher' else None
    return render_template('teachers/job.html', j=j, applied=applied, profile=profile, notice=consent.notice('job_application'))

@bp.route('/jobs/<slug>/apply', methods=['POST'])
@roles('teacher')
@limited(20, 3600, 'apply')
def apply(slug):
    j = db.one("SELECT * FROM jobs WHERE slug = %s AND status = 'published'", slug) or abort(404)
    profile = db.one('SELECT * FROM teacher_profiles WHERE user_id = %s', g.user['id'])
    if not profile:
        flash('Complete your teacher profile first — it only takes a few minutes.', 'info')
        return redirect(url_for('register.landing', slug='teacher-registration'))
    if not request.form.get('consent'):
        flash('Please agree to share your profile and CV with the school.', 'error'); return redirect(url_for('teachers.job', slug=slug))
    cv_url = None
    up = request.files.get('cv')
    if up and up.filename:
        try: cv_url = storage.save(up, private=True, folder='cvs', kinds=('doc',))['url']
        except storage.UploadError as e:
            flash(str(e), 'error'); return redirect(url_for('teachers.job', slug=slug))
    elif request.form.get('use') == 'uploaded' and profile['uploaded_cv_url']: cv_url = profile['uploaded_cv_url']
    snapshot = profile['cv_json'] if request.form.get('use', 'generated') == 'generated' else None
    if not cv_url and not snapshot:
        flash('Generate your AI CV or upload a CV to apply.', 'error'); return redirect(url_for('teachers.cv'))
    cid = consent.record('job_application', True, user_id=g.user['id'], context=f'job:{j["id"]}')
    try:
        aid = db.insert('job_applications', dict(job_id=j['id'], teacher_id=g.user['id'], cv_url=cv_url, cv_snapshot=snapshot,
                        cover_letter=request.form.get('cover_letter', '')[:4000], share_consent_id=cid))
    except db.IntegrityError:
        flash('You have already applied to this job.', 'info'); return redirect(url_for('teachers.job', slug=slug))
    notify.notify_org(j['org_id'], 'New job application', f"{g.user['name']} applied for {j['title']}.", f'/dashboard/jobs/{j["id"]}')
    crm.emit('job_application.created', {'application_id': aid, 'job': j['title'], 'org_id': j['org_id'], 'name': g.user['name'], 'email': g.user['email']})
    flash('Application sent! Track it from your dashboard.', 'success')
    return redirect(url_for('dashboard.applications'))

# ---------- CV builder ----------
@bp.route('/teachers/cv', methods=['GET', 'POST'])
@roles('teacher')
def cv():
    reg, a = teacher_answers(g.user['id'])
    profile = db.one('SELECT * FROM teacher_profiles WHERE user_id = %s', g.user['id'])
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'generate':
            if not reg:
                flash('Fill your teacher profile first.', 'info'); return redirect(url_for('register.landing', slug='teacher-registration'))
            if not request.form.get('consent_ai'):
                flash('Please allow the AI CV builder to use your professional details.', 'error'); return redirect(url_for('teachers.cv'))
            premium = profile and profile['membership_until'] and profile['membership_until'] >= datetime.date.today()
            n = db.val("SELECT count(*) FROM audit_log WHERE actor_id = %s AND action = 'cv.generated' AND created_at > now() - interval '30 days'", g.user['id'])
            if not premium and n >= 3:
                flash('Free accounts can generate 3 CV versions a month. Upgrade to Teacher Premium for unlimited tailored CVs.', 'warning')
                return redirect(url_for('teachers.cv'))
            consent.record('ai_cv', True, user_id=g.user['id'], context='cv_builder')
            data = CV.ai_cv(a.get('full_name') or g.user['name'], a, request.form.get('target_role'))
            if not profile:
                from .register import _teacher_profile; _teacher_profile(g.user['id'], reg['id'], a)
            db.run('UPDATE teacher_profiles SET cv_json = %s, cv_generated_at = now() WHERE user_id = %s', db.Json(data), g.user['id'])
            audit('cv.generated', 'user', g.user['id'], {'by': data.get('generated_by')})
            flash('Your CV is ready. Review it below, edit your profile to change anything, and download the PDF.', 'success')
        elif action == 'upload':
            up = request.files.get('cv')
            try:
                saved = storage.save(up, private=True, folder='cvs', kinds=('doc',))
                if not saved: raise storage.UploadError('Choose a file.')
                db.run('UPDATE teacher_profiles SET uploaded_cv_url = %s WHERE user_id = %s', saved['url'], g.user['id'])
                flash('CV uploaded.', 'success')
            except storage.UploadError as e:
                flash(str(e), 'error')
        elif action == 'save_summary' and profile and profile['cv_json']:
            data = dict(profile['cv_json']); data['summary'] = request.form.get('summary', '')[:1500]; data['headline'] = request.form.get('headline', '')[:200]
            db.run('UPDATE teacher_profiles SET cv_json = %s WHERE user_id = %s', db.Json(data), g.user['id'])
            flash('CV updated.', 'success')
        return redirect(url_for('teachers.cv'))
    return render_template('teachers/cv.html', reg=reg, profile=profile, notice=consent.notice('ai_cv'))

@bp.route('/teachers/cv.pdf')
@roles('teacher')
def cv_pdf():
    profile = db.one('SELECT * FROM teacher_profiles WHERE user_id = %s', g.user['id'])
    if not profile or not profile['cv_json']: abort(404)
    reg, a = teacher_answers(g.user['id'])
    pdf = CV.render_pdf(profile['cv_json'], [a.get('current_city'), a.get('state'), g.user['email'], a.get('mobile_number'), a.get('linkedin_profile')])
    return Response(pdf, mimetype='application/pdf', headers={'Content-Disposition': f'inline; filename="CV-{(a.get("full_name") or "teacher").replace(" ", "-")}.pdf"'})

@bp.route('/teachers/<slug>')
def profile(slug):
    p = db.one('SELECT tp.*, u.name, u.avatar_url FROM teacher_profiles tp JOIN users u ON u.id = tp.user_id WHERE tp.slug = %s', slug) or abort(404)
    from ..lib import entitlements as E
    viewer_is_recruiter = g.user and g.user['account_type'] == 'organisation' and (E.current().get('teacher_search') or E.current().get('directory_access'))
    own = g.user and g.user['id'] == p['user_id']
    if not (own or is_staff() or p['visibility'] == 'public' or (p['visibility'] == 'schools' and viewer_is_recruiter)): abort(404)
    reg, a = teacher_answers(p['user_id'])
    defn = F.get('teacher-registration')
    tiers = ('public', 'detailed') if (own or viewer_is_recruiter or is_staff()) else ('public',)
    secs = F.profile_sections(defn, reg['answers'] if reg else {}, reg['files'] if reg else {}, tiers)
    return render_template('teachers/profile.html', p=p, secs=secs, a={k: a.get(k) for k in ('professional_headline', 'current_city', 'state', 'total_teaching_experience')})

@bp.route('/teachers/directory')
@roles('organisation')
def directory():
    from ..lib import entitlements as E
    ok = E.current().get('teacher_search') or is_staff()
    rows = []
    if ok:
        q = request.args.get('q', '')
        with db.elevated():   # projection: only public teaching subjects are exposed from the registration
          rows = db.all("""SELECT tp.*, u.name, jsonb_build_object('subjects_you_teach', r.answers->'subjects_you_teach') AS answers FROM teacher_profiles tp JOIN users u ON u.id = tp.user_id
                         LEFT JOIN registrations r ON r.id = tp.registration_id WHERE tp.visibility IN ('public','schools') AND tp.open_to_work
                         AND (%s = '' OR u.name ILIKE %s OR tp.headline ILIKE %s OR r.answers::text ILIKE %s) ORDER BY tp.updated_at DESC LIMIT 60""",
                      q, f'%{q}%', f'%{q}%', f'%{q}%')
        for r in rows: r['answers'] = r['answers'] or {}
    return render_template('teachers/directory.html', ok=ok, rows=rows, plan=db.one("SELECT * FROM plans WHERE code = 'school_recruiter'"))

@bp.route('/teachers/premium', methods=['POST'])
@roles('teacher')
def premium():
    p = db.one("SELECT * FROM plans WHERE code = 'teacher_premium' AND active") or abort(404)
    o = payments.create_order('plan', p['name'], p['price_paise'], user_id=g.user['id'], meta={'plan': p['code']},
                              items=[{'title': p['name'], 'qty': 1, 'unit_paise': p['price_paise']}])
    return redirect(url_for('pay.checkout', public_id=o['public_id']))
