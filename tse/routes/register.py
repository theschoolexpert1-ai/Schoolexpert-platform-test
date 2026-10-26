"""Registration centre: every form from registration.schoolexpert.in (and new ones) rendered from its definition.
Save as you go -> review -> consents -> submit -> choose plan / pay (or pay later) -> dashboard."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, current_app, session
from ..db import db
from ..lib import forms as F, listings as L, consent, crm, notify, payments
from ..lib.auth import login_required
from ..lib.security import encrypt_json, decrypt_json, audit

from ..lib.security import attribution as S_attr, referral_code as S_ref
bp = Blueprint('register', __name__, url_prefix='/register')

GROUP_TITLES = {'schools': 'Schools', 'learning': 'Tutors, Courses, Classes & Training', 'experts': 'Experts & Specialists',
                'vendors': 'Education Partners & Vendors', 'teachers': 'Teachers', 'ambassadors': 'Ambassador Programmes', 'events': 'Events'}
ACCOUNT_FOR = {'teachers': 'teacher', 'ambassadors': 'parent'}

def plan_audience(grp, entity=None):
    """Plan family for a registration category: schools -> School plans; every other listed organisation -> Vendor plans."""
    if grp == 'schools': return 'school'
    if grp in ('vendors', 'learning', 'experts'): return 'vendor'
    return None

@bp.route('/')
def index():
    cats = db.all("""SELECT c.*, f.title, f.provisional FROM categories c JOIN form_definitions f ON f.slug = c.slug
                     WHERE f.active AND c.grp <> 'events' ORDER BY c.sort, c.label""")
    groups = {}
    for c in cats: groups.setdefault(c['grp'], []).append(c)
    return render_template('register/index.html', groups=groups, titles=GROUP_TITLES, total=len(cats))

@bp.route('/<slug>')
def landing(slug):
    defn = F.get(slug) or abort(404)
    if defn['_meta']['grp'] == 'events':
        return redirect(url_for('events.index', kind='roundtable'))
    aud = plan_audience(defn['_meta']['grp'], defn['_meta']['entity'])
    plans = db.all("SELECT * FROM plans WHERE active AND family = %s AND stream <> 'founding_partner' ORDER BY level", aud) if aud else []
    mine = []
    if g.user:
        mine = db.all("""SELECT r.* FROM registrations r LEFT JOIN org_members m ON m.org_id = r.org_id
                         WHERE r.form_slug = %s AND (r.user_id = %s OR m.user_id = %s) ORDER BY r.id DESC""", slug, g.user['id'], g.user['id'])
    return render_template('register/landing.html', defn=defn, slug=slug, plans=plans, mine=mine,
                           need_type=defn.get('account') or ACCOUNT_FOR.get(defn['_meta']['grp'], 'organisation'))

@bp.route('/<slug>/start', methods=['POST'])
@login_required
def start(slug):
    defn = F.get(slug) or abort(404)
    grp, entity = defn['_meta']['grp'], defn['_meta']['entity']
    need = defn.get('account') or ACCOUNT_FOR.get(grp, 'organisation')
    if g.user['account_type'] != need and g.user['account_type'] != 'admin':
        names = {'organisation': 'a School / Organisation', 'teacher': 'a Teacher', 'parent': 'a Parent'}
        flash(f'This registration needs {names[need]} account. Please log out and sign up with that account type.', 'error')
        return redirect(url_for('register.landing', slug=slug))
    if slug == 'teacher-registration':
        existing = db.one("SELECT id FROM registrations WHERE form_slug = %s AND user_id = %s AND status <> 'withdrawn'", slug, g.user['id'])
        if existing: return redirect(url_for('register.step', rid=existing['id'], si=0))
    org_id = None
    if need == 'organisation':
        org_id = request.form.get('org_id', type=int)
        if org_id and not any(o['id'] == org_id for o in g.orgs): abort(403)
        if not org_id:
            org_id = db.insert('organisations', dict(name='New registration', slug=L.unique_slug('organisations', f'org-{g.user["id"]}'),
                               category=grp, kind=entity, created_by=g.user['id'], attribution=S_attr()))
            db.insert('org_members', dict(org_id=org_id, user_id=g.user['id'], role='owner'), returning=None)
            from flask import session; session['org_id'] = org_id
    rid = db.insert('registrations', dict(form_slug=slug, form_version=defn['_meta']['version'], user_id=g.user['id'], org_id=org_id))
    audit('registration.started', 'registration', rid, {'form': slug}, org_id=org_id)
    return redirect(url_for('register.step', rid=rid, si=0))

@bp.route('/r/<int:rid>/add-record', methods=['POST'])
@login_required
def add_record(rid):
    """Forms with several records per account (e.g. Course Providers: one provider, many courses). The shared sections
    (provider details) are copied; each new record gets its own registration, listing and ID."""
    src = load_reg(rid)
    defn = F.get(src['form_slug'])
    mr = defn.get('multi_record') or abort(404)
    shared = {f['key'] for s in defn['sections'] if s['title'] in mr['shared_sections'] for f in s['fields']}
    a = all_answers(src)
    keep = {k: v for k, v in a.items() if k in shared}
    pub, priv = F.split_private(defn, keep)
    files = {k: v for k, v in src['files'].items() if k in shared}
    parent = src['parent_registration_id'] or src['id']
    new = db.insert('registrations', dict(form_slug=src['form_slug'], form_version=defn['_meta']['version'], user_id=g.user['id'], org_id=src['org_id'],
                    answers=pub, private_enc=encrypt_json(priv), files=files, parent_registration_id=parent,
                    progress=F.progress(defn, keep, files)))
    audit('registration.record_added', 'registration', new, {'from': rid}, org_id=src['org_id'])
    first = next(i for i, s in enumerate(defn['sections']) if s['title'] not in mr['shared_sections'])
    flash(f"New {mr['record_label']} started — your provider details were copied. It gets its own ID and listing once verified.", 'success')
    return redirect(url_for('register.step', rid=new, si=first))

def load_reg(rid, write=True):
    reg = db.one('SELECT * FROM registrations WHERE id = %s', rid) or abort(404)
    role = db.val('SELECT role FROM org_members WHERE org_id = %s AND user_id = %s', reg['org_id'], g.user['id']) if reg['org_id'] else None
    ok = reg['user_id'] == g.user['id'] or role or g.user['account_type'] == 'admin'
    if not ok: abort(404)
    if write and request.method == 'POST' and role == 'viewer' and reg['user_id'] != g.user['id'] and g.user['account_type'] != 'admin':
        abort(403)    # organisation viewers may read the registration but not change it
    return reg

def all_answers(reg):
    a = dict(reg['answers']); a.update(decrypt_json(reg['private_enc']))
    return a

def save_answers(reg, defn, new_answers, new_files, locked_keys=()):
    answers = all_answers(reg)
    for k, v in new_answers.items():
        if k in locked_keys: continue
        answers[k] = v
    files = dict(reg['files'])
    for k, v in new_files.items():
        if k in locked_keys: continue
        files[k] = v
    pub, priv = F.split_private(defn, answers)
    prog = F.progress(defn, answers, files)
    db.run('UPDATE registrations SET answers = %s, private_enc = %s, files = %s, progress = %s, updated_at = now() WHERE id = %s',
           db.Json(pub), encrypt_json(priv), db.Json(files), prog, reg['id'])
    return answers, files

def locked_keys_for(reg, defn):
    if reg['status'] not in ('verified', 'under_review', 'suspended') or g.user['account_type'] == 'admin': return set()
    return {f['key'] for _, _, f in F.fields(defn) if not F.editable_after_verification(f)}

@bp.route('/r/<int:rid>/<int:si>', methods=['GET', 'POST'])
@login_required
def step(rid, si):
    reg = load_reg(rid); defn = F.get(reg['form_slug'])
    secs = defn['sections']
    if si < 0 or si >= len(secs): abort(404)
    answers = all_answers(reg); files = reg['files']; errors = {}
    locked = locked_keys_for(reg, defn)
    if request.method == 'POST':
        new, nf, errors = F.parse_section(defn, si, request.form, request.files, files)
        answers, files = save_answers(reg, defn, new, nf, locked)
        if si == 0 and reg['org_id']:
            nm = F.answer_by_role(defn, answers, 'name')
            if nm: db.run('UPDATE organisations SET name = %s WHERE id = %s', nm[:200], reg['org_id'])
        if reg['status'] in ('verified',):
            L.sync(rid)
        if errors:
            flash('Saved — please correct the highlighted fields.', 'warning')
        else:
            action = request.form.get('action')
            if action == 'exit':
                flash('Your progress is saved. You can continue any time from your dashboard.', 'success')
                return redirect(url_for('dashboard.home'))
            nxt = si + 1
            while nxt < len(secs) and not F.section_visible(secs[nxt], answers): nxt += 1
            if action == 'prev': return redirect(url_for('register.step', rid=rid, si=max(0, si - 1)))
            if nxt >= len(secs) or action == 'review': return redirect(url_for('register.review', rid=rid))
            return redirect(url_for('register.step', rid=rid, si=nxt))
    reg = db.one('SELECT * FROM registrations WHERE id = %s', rid)
    done = [not F.missing_required(defn, answers, files, i) and any(not F.is_empty(answers.get(f['key']) or files.get(f['key'])) for f in s['fields']) for i, s in enumerate(secs)]
    return render_template('register/step.html', reg=reg, defn=defn, si=si, sec=secs[si], answers=answers, files=files, errors=errors,
                           done=done, states=F.INDIAN_STATES, locked=locked)

@bp.route('/r/<int:rid>/review', methods=['GET', 'POST'])
@login_required
def review(rid):
    reg = load_reg(rid); defn = F.get(reg['form_slug'])
    answers = all_answers(reg); files = reg['files']
    missing = F.missing_required(defn, answers, files)
    grp = defn['_meta']['grp']
    listed = db.val('SELECT listed FROM categories WHERE slug = %s', reg['form_slug'])
    is_minor = defn['_meta']['entity'] == 'minor'
    if request.method == 'POST':
        if missing:
            flash('Please complete the required fields before submitting.', 'error')
            return redirect(url_for('register.review', rid=rid))
        if not request.form.get('consent_registration') or (listed and not request.form.get('consent_listing')):
            flash('Please accept the consent notices to submit.', 'error'); return redirect(url_for('register.review', rid=rid))
        if is_minor and not reg['checks'].get('guardian_verified'):
            flash('Please verify the parent/guardian mobile number with the OTP first.', 'error'); return redirect(url_for('register.review', rid=rid))
        consent.record('registration', True, user_id=g.user['id'], context=f'registration:{rid}')
        if listed: consent.record('profile_listing', True, user_id=g.user['id'], context=f'registration:{rid}')
        aud = plan_audience(grp, defn['_meta']['entity'])
        from ..lib import entitlements as E
        has_paid = bool(reg['org_id'] and E.active_subscription(reg['org_id']))
        status = 'payment_pending' if (aud and not has_paid) else 'under_review'
        db.run('UPDATE registrations SET status = %s, submitted_at = now(), updated_at = now() WHERE id = %s', status, rid)
        if reg['form_slug'] == 'teacher-registration':
            _teacher_profile(reg['user_id'], rid, answers)
        name = F.answer_by_role(defn, answers, 'name')
        crm.emit('registration.submitted', {'registration_id': rid, 'form': reg['form_slug'], 'name': name, 'org_name': name,
                 'email': F.answer_by_role(defn, answers, 'email') or g.user['email'], 'phone': F.answer_by_role(defn, answers, 'phone'),
                 'city': F.answer_by_role(defn, answers, 'city'), 'status': status})
        notify.notify_staff('Registration submitted', f"{defn['_meta']['label']}: {name}", f'/admin/registrations/{rid}')
        audit('registration.submitted', 'registration', rid, {'form': reg['form_slug']}, org_id=reg['org_id'])
        if status == 'payment_pending':
            flash('Registration complete! Choose a plan to activate your listing — or save and pay later from your dashboard.', 'success')
            return redirect(url_for('register.plan', rid=rid))
        flash('Thank you — your registration has been submitted for review. We will notify you once it is verified.', 'success')
        return redirect(url_for('dashboard.home'))
    sections = []
    for s in defn['sections']:
        items = []
        for f in s['fields']:
            if f['type'] in ('heading',): continue
            v = files.get(f['key']) if f['type'] in ('file', 'files') else answers.get(f['key'])
            items.append((f, F.display_value(f, v) if f['type'] not in ('file', 'files') else v))
        sections.append((s, items))
    return render_template('register/review.html', reg=reg, defn=defn, sections=sections, missing=missing, listed=listed, is_minor=is_minor,
                           n_reg=consent.notice('registration'), n_list=consent.notice('profile_listing'), n_guard=consent.notice('guardian_student_ambassador'),
                           answers=answers)

def _teacher_profile(uid, rid, a):
    slug = db.val('SELECT slug FROM teacher_profiles WHERE user_id = %s', uid) or L.unique_slug('teacher_profiles', f"{a.get('full_name', 'teacher')}-{uid}")
    vis = a.get('profile_visibility') or ''
    visibility = 'public' if vis.startswith('Visible on the public') else 'hidden' if vis.startswith('Hidden') else 'schools'
    db.run("""INSERT INTO teacher_profiles (user_id, registration_id, slug, headline, visibility, open_to_work) VALUES (%s,%s,%s,%s,%s,%s)
              ON CONFLICT (user_id) DO UPDATE SET registration_id = EXCLUDED.registration_id, headline = EXCLUDED.headline,
              visibility = EXCLUDED.visibility, open_to_work = EXCLUDED.open_to_work, updated_at = now()""",
           uid, rid, slug, a.get('professional_headline'), visibility, a.get('open_to_new_opportunities') != 'No')

@bp.route('/r/<int:rid>/guardian-otp', methods=['POST'])
@login_required
def guardian_otp(rid):
    """Verifiable parental consent (DPDP Rules, rule 10): OTP to the parent/guardian mobile captured in the form."""
    from ..lib import security as S
    reg = load_reg(rid); a = all_answers(reg)
    phone = (a.get('parent_guardian_mobile_number') or '').strip()
    if request.form.get('code'):
        if S.check_otp('guardian_consent', phone, request.form['code']):
            checks = dict(reg['checks']); checks['guardian_verified'] = True; checks['guardian_phone'] = phone[-4:]
            db.run('UPDATE registrations SET checks = %s WHERE id = %s', db.Json(checks), rid)
            consent.record('guardian_student_ambassador', True, user_id=g.user['id'], method='otp_guardian', context=f'registration:{rid}',
                           guardian={'name': a.get('parent_guardian_full_name'), 'relationship': a.get('relationship_to_student'), 'phone_last4': phone[-4:]})
            flash('Parent / guardian consent verified.', 'success')
        else:
            flash('That code is incorrect or expired.', 'error')
        return redirect(url_for('register.review', rid=rid))
    if len(phone) < 10:
        flash('Enter the parent/guardian mobile number in the form first.', 'error'); return redirect(url_for('register.review', rid=rid))
    code = S.make_token('guardian_consent', phone, g.user['id'], minutes=15, numeric=True)
    notify.sms(phone, f'The School Expert: OTP {code} to give consent for the Student Ambassador application. Valid 15 minutes.', otp=code)
    flash('OTP sent to the parent/guardian mobile.' + (f' (Development mode code: {code})' if current_app.config['DEV_SHOW_OTP'] else ''), 'info')
    return redirect(url_for('register.review', rid=rid))

@bp.route('/r/<int:rid>/plan', methods=['GET', 'POST'])
@login_required
def plan(rid):
    reg = load_reg(rid); defn = F.get(reg['form_slug'])
    fam = plan_audience(defn['_meta']['grp'])
    if not fam: return redirect(url_for('dashboard.home'))
    plans = db.all("SELECT * FROM plans WHERE active AND family = %s AND stream <> 'founding_partner' ORDER BY level", fam)
    founding = db.all("SELECT * FROM plans WHERE active AND family = %s AND stream = 'founding_partner'", fam)
    from ..lib import entitlements as E
    current = E.active_subscription(reg['org_id']) if reg['org_id'] else None
    if request.method == 'POST':
        p = db.one('SELECT * FROM plans WHERE code = %s AND active', request.form.get('plan')) or abort(400)
        if p['family'] != fam: abort(400)
        if current and current['level'] >= p['level']:
            flash('You already have this plan or a higher one.', 'info'); return redirect(url_for('dashboard.home'))
        if current:   # upgrades go through the dashboard (one step at a time, with credit)
            return redirect(url_for('dashboard.plans'))
        order = payments.create_order('plan', f"{p['name']} — {defn['_meta']['label']}", p['price_paise'], user_id=g.user['id'], org_id=reg['org_id'],
                                      gst_rate=float(p['gst_rate']), meta={'plan': p['code'], 'registration_id': rid, 'action': 'new'},
                                      referral_code=S_ref(),
                                      items=[{'title': p['name'], 'qty': 1, 'unit_paise': p['price_paise']}])
        return redirect(url_for('pay.checkout', public_id=order['public_id']))
    return render_template('register/plan.html', reg=reg, defn=defn, plans=plans, founding=founding, fam=fam, current=current)

@payments.fulfiller('plan')
def _fulfil_plan(order):
    """New plan, one-step upgrade (Basic->Plus->Pro) or renewal. Recomputes visibility for all the organisation's listings."""
    import datetime
    from ..lib import entitlements as E
    p = db.one('SELECT * FROM plans WHERE code = %s', order['meta']['plan'])
    action = order['meta'].get('action', 'new')
    rid = order['meta'].get('registration_id')
    reg = db.one('SELECT * FROM registrations WHERE id = %s', rid) if rid else None
    today = datetime.date.today()
    ends = None
    if p['interval'] == 'annual': ends = today + datetime.timedelta(days=365)
    elif p['interval'] == 'monthly': ends = today + datetime.timedelta(days=31)
    grants = p['grants']
    if grants.get('waiver_years'): ends = today + datetime.timedelta(days=365 * grants['waiver_years'])
    prev = None
    if order['org_id'] and p['family'] in ('school', 'vendor'):
        prev = E.active_subscription(order['org_id'])
        if prev and action == 'renew' and prev['plan_code'] == p['code']:
            base = max(prev['ends_at'] or today, today)
            db.run('UPDATE subscriptions SET ends_at = %s WHERE id = %s', base + datetime.timedelta(days=365), prev['id'])
            prev = 'renewed'
        elif prev:
            db.run("UPDATE subscriptions SET status = 'upgraded' WHERE id = %s", prev['id'])
    if prev != 'renewed':
        db.insert('subscriptions', dict(org_id=order['org_id'], user_id=None if order['org_id'] else order['user_id'], plan_code=p['code'],
                  ends_at=ends, order_id=order['id'], amount_paise=order['subtotal_paise'],
                  upgraded_from=prev['id'] if isinstance(prev, dict) else None), returning=None)
    if grants.get('founding_partner') and order['org_id']:
        db.run('UPDATE organisations SET founding_partner = true, founding_partner_since = current_date, renewal_waived_until = %s WHERE id = %s', ends, order['org_id'])
    if grants.get('teacher_premium'):
        db.run('UPDATE teacher_profiles SET membership_until = %s WHERE user_id = %s', ends, order['user_id'])
    if grants.get('ad_credit_days') and order['org_id'] and action != 'renew':
        db.insert('ad_placements', dict(placement='directory', org_id=order['org_id'], title='Included sponsored banner — set up in your dashboard',
                  link_url='/', starts_on=today, ends_on=today + datetime.timedelta(days=grants['ad_credit_days']), active=False, status='draft'), returning=None)
    if reg and reg['status'] == 'payment_pending':
        db.run("UPDATE registrations SET status = 'under_review' WHERE id = %s", rid)
    if order['org_id']: L.refresh_org(order['org_id'])
    verb = {'upgrade': 'upgraded to', 'renew': 'renewed:'}.get(action, 'activated:')
    notify.notify(order['user_id'], f"Plan {verb} {p['name']}", 'Thank you for your payment. Your dashboard and visibility have been updated.', '/dashboard', mail=True)
