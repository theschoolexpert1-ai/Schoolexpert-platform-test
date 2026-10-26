"""Account dashboards: parent, teacher, organisation (school / partner / professional — multi-tenant)."""
import datetime, secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, session, current_app
from ..db import db
from ..lib import forms as F, listings as L, payments, notify, storage, crm, entitlements as E
from ..lib.auth import login_required, roles, org_required, tenant_guard, is_staff
from ..lib.security import hash_password, verify_password, password_problem, audit

from ..lib.security import attribution as S_attr, referral_code as S_ref
bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')

@bp.before_request
def _auth():
    if not g.user: return redirect(url_for('auth.login', next=request.full_path))
    if g.user['account_type'] in ('admin', 'staff') and request.endpoint == 'dashboard.home': return redirect(url_for('admin.index'))
    # Paid access: an organisation's dashboard tools unlock only with an active School/Vendor plan.
    if g.user['account_type'] == 'organisation' and g.org and request.endpoint not in UNPAID_OK and not E.current().get('dashboard'):
        flash('Activate a plan to unlock your dashboard.', 'info')
        return redirect(url_for('dashboard.home'))

UNPAID_OK = {'dashboard.home', 'dashboard.plans', 'dashboard.orders', 'dashboard.subscriptions', 'dashboard.support', 'dashboard.ticket',
             'dashboard.settings', 'dashboard.notifications', 'dashboard.events', 'dashboard.accept_invite', 'dashboard.referrals'}

def org_regs():
    return db.all("""SELECT r.*, c.label, c.grp, l.slug AS listing_slug, l.tier, l.is_published, l.id AS listing_id FROM registrations r
                     JOIN categories c ON c.slug = r.form_slug LEFT JOIN listings l ON l.registration_id = r.id
                     WHERE r.org_id = %s AND r.status <> 'withdrawn' ORDER BY r.id""", g.org['id']) if g.org else []

@bp.route('/')
def home():
    t = g.user['account_type']
    ctx = {}
    if t == 'organisation':
        if not g.org: return redirect(url_for('register.index'))
        regs = org_regs()
        ent = E.current()
        if not ent.get('dashboard'):
            fam = E.org_family(g.org)
            return render_template('dashboard/org_activate.html', regs=regs, fam=fam,
                                   plans=db.all("SELECT * FROM plans WHERE active AND family = %s AND stream <> 'founding_partner' ORDER BY level", fam),
                                   founding=db.all("SELECT * FROM plans WHERE active AND family = %s AND stream = 'founding_partner'", fam),
                                   expired=E.renewal_quote(g.org['id']))
        lids = [r['listing_id'] for r in regs if r['listing_id']]
        stats = db.all("""SELECT d::date AS day, COALESCE(sum(s.views),0) views, COALESCE(sum(s.leads),0) leads, COALESCE(sum(s.unlocks),0) unlocks,
                            COALESCE(sum(s.match_appearances),0) matches
                            FROM generate_series(current_date - 29, current_date, interval '1 day') d
                            LEFT JOIN listing_stats s ON s.day = d::date AND s.listing_id = ANY(%s) GROUP BY d ORDER BY d""", lids or [0])
        ctx.update(ent=ent, quote=E.upgrade_quote(g.org['id']), stats=stats, tier=E.tier_label(ent['level']),
                   jobs_used=db.val("SELECT count(*) FROM jobs WHERE org_id = %s AND status = 'published'", g.org['id']),
                   products_used=db.val("SELECT count(*) FROM products WHERE seller_org_id = %s AND status <> 'archived'", g.org['id']),
                   earnings=db.one("SELECT COALESCE(sum(net_paise) FILTER (WHERE status <> 'paid'),0) due, COALESCE(sum(net_paise) FILTER (WHERE status = 'paid'),0) paid FROM seller_ledger WHERE seller_org_id = %s", g.org['id']))
        multi = {r['form_slug']: (F.get(r['form_slug']).get('multi_record') or {}) for r in regs}
        ctx.update(regs=regs, multi=multi,
            subs=db.all("""SELECT s.*, p.name FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.org_id = %s ORDER BY s.id DESC""", g.org['id']),
            kpi=dict(leads=db.val("SELECT count(*) FROM leads WHERE org_id = %s AND status = 'new'", g.org['id']),
                     views=db.val('SELECT COALESCE(sum(view_count),0) FROM listings WHERE org_id = %s', g.org['id']),
                     jobs=db.val("SELECT count(*) FROM jobs WHERE org_id = %s AND status = 'published'", g.org['id']),
                     apps=db.val("SELECT count(*) FROM job_applications a JOIN jobs j ON j.id = a.job_id WHERE j.org_id = %s AND a.status = 'applied'", g.org['id']),
                     rating=db.one('SELECT max(rating_avg) r, sum(rating_count) n FROM listings WHERE org_id = %s', g.org['id'])),
            recent_leads=db.all('SELECT * FROM leads WHERE org_id = %s ORDER BY id DESC LIMIT 5', g.org['id']),
            pending_pay=[r for r in regs if r['status'] == 'payment_pending'])
        return render_template('dashboard/org_home.html', **ctx)
    if t == 'teacher':
        ctx.update(reg=db.one("SELECT * FROM registrations WHERE form_slug = 'teacher-registration' AND user_id = %s ORDER BY id DESC LIMIT 1", g.user['id']),
                   profile=db.one('SELECT * FROM teacher_profiles WHERE user_id = %s', g.user['id']),
                   apps=db.all("""SELECT a.*, j.title, j.slug, o.name AS org_name FROM job_applications a JOIN jobs j ON j.id = a.job_id JOIN organisations o ON o.id = j.org_id
                                  WHERE a.teacher_id = %s ORDER BY a.id DESC LIMIT 5""", g.user['id']),
                   jobs=db.all("""SELECT j.*, o.name AS org_name FROM jobs j JOIN organisations o ON o.id = j.org_id WHERE j.status = 'published' ORDER BY j.published_at DESC LIMIT 5"""))
        from .hub import dashboard_context
        ctx.update(dashboard_context(g.user['id']))
        return render_template('dashboard/teacher_home.html', **ctx)
    # parent
    ctx.update(packs=db.all('SELECT * FROM unlock_packs WHERE user_id = %s ORDER BY id DESC', g.user['id']),
               unlocks=db.all("""SELECT l.*, c.label AS category_label, u.created_at AS unlocked_at FROM unlocks u JOIN listings l ON l.id = u.listing_id
                                 JOIN categories c ON c.slug = l.category WHERE u.user_id = %s ORDER BY u.id DESC""", g.user['id']),
               pa=db.all('SELECT * FROM pa_requests WHERE user_id = %s ORDER BY id DESC LIMIT 5', g.user['id']),
               reqs=db.all('SELECT * FROM expert_requests WHERE user_id = %s ORDER BY id DESC LIMIT 5', g.user['id']),
               regs=db.all("SELECT r.*, c.label FROM registrations r JOIN categories c ON c.slug = r.form_slug WHERE r.user_id = %s AND r.org_id IS NULL ORDER BY r.id DESC", g.user['id']),
               events=db.all("""SELECT er.*, e.title, e.slug, e.starts_at FROM event_registrations er JOIN events e ON e.id = er.event_id WHERE er.user_id = %s AND e.starts_at > now() ORDER BY e.starts_at""", g.user['id']))
    return render_template('dashboard/parent_home.html', **ctx)

# ---------------- common ----------------
@bp.route('/notifications')
def notifications():
    rows = db.all('SELECT * FROM notifications WHERE user_id = %s ORDER BY id DESC LIMIT 100', g.user['id'])
    db.run('UPDATE notifications SET read_at = now() WHERE user_id = %s AND read_at IS NULL', g.user['id'])
    return render_template('dashboard/notifications.html', rows=rows)

@bp.route('/orders')
def orders():
    rows = db.all("""SELECT * FROM orders WHERE (user_id = %s OR (org_id IS NOT NULL AND org_id = %s)) ORDER BY id DESC LIMIT 200""",
                  g.user['id'], g.org['id'] if g.org else 0)
    ships = {s['order_id']: s for s in db.all('SELECT * FROM shipments WHERE order_id = ANY(%s)', [o['id'] for o in rows])} if rows else {}
    return render_template('dashboard/orders.html', rows=rows, ships=ships)

@bp.route('/subscriptions')
def subscriptions():
    rows = db.all("""SELECT s.*, p.name, p.interval FROM subscriptions s JOIN plans p ON p.code = s.plan_code
                     WHERE s.user_id = %s OR (s.org_id IS NOT NULL AND s.org_id = %s) ORDER BY s.id DESC""", g.user['id'], g.org['id'] if g.org else 0)
    nl = db.all('SELECT * FROM newsletter_subscriptions WHERE user_id = %s OR email = %s', g.user['id'], g.user['email'])
    return render_template('dashboard/subscriptions.html', rows=rows, nl=nl)

@bp.route('/requests')
def requests():
    rows = db.all('SELECT * FROM expert_requests WHERE user_id = %s ORDER BY id DESC', g.user['id'])
    from .ask import TOPICS
    return render_template('dashboard/requests.html', rows=rows, topics=TOPICS)

@bp.route('/personal-assistance')
def pa():
    rows = db.all('SELECT * FROM pa_requests WHERE user_id = %s ORDER BY id DESC', g.user['id'])
    return render_template('dashboard/pa.html', rows=rows)

@bp.route('/events')
def events():
    rows = db.all("""SELECT er.*, e.title, e.slug, e.starts_at, e.mode, e.venue, e.city FROM event_registrations er JOIN events e ON e.id = er.event_id
                     WHERE er.user_id = %s OR (er.org_id IS NOT NULL AND er.org_id = %s) ORDER BY e.starts_at DESC""", g.user['id'], g.org['id'] if g.org else 0)
    return render_template('dashboard/events.html', rows=rows)

@bp.route('/applications')
@roles('teacher')
def applications():
    rows = db.all("""SELECT a.*, j.title, j.slug, j.city, o.name AS org_name FROM job_applications a JOIN jobs j ON j.id = a.job_id
                     JOIN organisations o ON o.id = j.org_id WHERE a.teacher_id = %s ORDER BY a.id DESC""", g.user['id'])
    return render_template('dashboard/applications.html', rows=rows)

@bp.route('/applications/<int:aid>/withdraw', methods=['POST'])
@roles('teacher')
def withdraw_application(aid):
    db.run("UPDATE job_applications SET status = 'withdrawn', updated_at = now() WHERE id = %s AND teacher_id = %s", aid, g.user['id'])
    flash('Application withdrawn.', 'info'); return redirect(url_for('dashboard.applications'))

@bp.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        f = request.form
        if f.get('action') == 'password':
            if not verify_password(g.user['password_hash'], f.get('current', '')):
                flash('Current password is incorrect.', 'error')
            elif password_problem(f.get('new', ''), g.user['email'], g.user['name']):
                flash(password_problem(f.get('new', ''), g.user['email'], g.user['name']), 'error')
            else:
                db.run('UPDATE users SET password_hash = %s, password_changed_at = now() WHERE id = %s', hash_password(f['new']), g.user['id'])
                import hashlib
                db.run('DELETE FROM sessions WHERE user_id = %s AND sid <> %s', g.user['id'], hashlib.sha256(session.sid.encode()).hexdigest())   # sign out other devices
                audit('auth.password_changed', 'user', g.user['id']); flash('Password changed. Other devices have been signed out.', 'success')
        else:
            db.run('UPDATE users SET name = %s, phone = %s, city = %s, state = %s, pincode = %s WHERE id = %s', f.get('name', g.user['name'])[:120],
                   f.get('phone', '')[:20] or None, f.get('city', '')[:80] or None, f.get('state') if f.get('state') in F.INDIAN_STATES else None, f.get('pincode', '')[:6] or None, g.user['id'])
            flash('Profile updated.', 'success')
        return redirect(url_for('dashboard.settings'))
    addresses = db.all('SELECT * FROM addresses WHERE user_id = %s', g.user['id'])
    return render_template('dashboard/settings.html', states=F.INDIAN_STATES, addresses=addresses)

@bp.route('/support', methods=['GET', 'POST'])
def support():
    if request.method == 'POST':
        subj = request.form.get('subject', '').strip()[:160]; body = request.form.get('body', '').strip()[:5000]
        if not subj or not body: flash('Please add a subject and message.', 'error'); return redirect(url_for('dashboard.support'))
        tid = db.insert('support_tickets', dict(org_id=g.org['id'] if g.org else None, user_id=g.user['id'], subject=subj, priority=request.form.get('priority', 'normal')))
        db.insert('ticket_messages', dict(ticket_id=tid, user_id=g.user['id'], body=body), returning=None)
        notify.notify_staff('New support ticket', subj, f'/admin/tickets/{tid}')
        flash('Support request created. We usually reply within one working day.', 'success')
        return redirect(url_for('dashboard.ticket', tid=tid))
    rows = db.all('SELECT * FROM support_tickets WHERE user_id = %s OR (org_id IS NOT NULL AND org_id = %s) ORDER BY id DESC', g.user['id'], g.org['id'] if g.org else 0)
    return render_template('dashboard/support.html', rows=rows, prefill=request.args.get('subject', ''))

@bp.route('/support/<int:tid>', methods=['GET', 'POST'])
def ticket(tid):
    t = db.one('SELECT * FROM support_tickets WHERE id = %s', tid) or abort(404)
    if t['user_id'] != g.user['id'] and not (g.org and t['org_id'] == g.org['id']) and not is_staff(): abort(404)
    if request.method == 'POST' and request.form.get('body'):
        db.insert('ticket_messages', dict(ticket_id=tid, user_id=g.user['id'], body=request.form['body'][:5000]), returning=None)
        db.run("UPDATE support_tickets SET status = 'open', updated_at = now() WHERE id = %s", tid)
        return redirect(url_for('dashboard.ticket', tid=tid))
    msgs = db.all('SELECT m.*, u.name FROM ticket_messages m LEFT JOIN users u ON u.id = m.user_id WHERE ticket_id = %s ORDER BY m.id', tid)
    return render_template('dashboard/ticket.html', t=t, msgs=msgs)

# ---------------- organisation (tenant) ----------------
@bp.route('/profile')
@org_required()
def profile():
    return render_template('dashboard/org_profile.html', regs=org_regs())

@bp.route('/media/<int:lid>', methods=['GET', 'POST'])
@org_required('editor')
def media(lid):
    l = tenant_guard('listings', lid)
    if request.method == 'POST':
        if request.form.get('delete'):
            db.run('DELETE FROM listing_media WHERE id = %s AND listing_id = %s', request.form.get('delete', type=int), lid)
        else:
            n = 0
            used = db.val('SELECT count(*) FROM listing_media WHERE listing_id = %s', lid)
            for fs in request.files.getlist('files'):
                if fs and fs.filename:
                    if not E.limit_ok('photos_limit', used + n):
                        flash(f"Your plan allows {E.current()['photos_limit']} photos/videos. Upgrade for more.", 'warning'); break
                    try:
                        saved = storage.save(fs, folder='listing-media', kinds=('image', 'video'))
                        kind = 'video' if saved['url'].rsplit('.', 1)[-1] in ('mp4', 'mov', 'webm') else 'photo'
                        db.insert('listing_media', dict(listing_id=lid, kind=kind, url=saved['url'], caption=request.form.get('caption', '')[:200]), returning=None); n += 1
                    except storage.UploadError as e: flash(str(e), 'error')
            if request.form.get('video_url', '').startswith('https://'):
                db.insert('listing_media', dict(listing_id=lid, kind='video', url=request.form['video_url'][:500], caption=request.form.get('caption', '')[:200]), returning=None); n += 1
            if n: flash(f'{n} item(s) added. Remember: do not upload photos where children can be identified without parental consent.', 'success')
        return redirect(url_for('dashboard.media', lid=lid))
    items = db.all('SELECT * FROM listing_media WHERE listing_id = %s ORDER BY sort, id', lid)
    return render_template('dashboard/media.html', l=l, items=items)

@bp.route('/leads')
@org_required()
@E.requires('leads', 'Verified leads from parents and schools are part of the Plus and Pro plans.')
def leads():
    status = request.args.get('status')
    rows = db.all(f"""SELECT ld.*, l.name AS listing_name FROM leads ld LEFT JOIN listings l ON l.id = ld.listing_id WHERE ld.org_id = %s
                      {'AND ld.status = %s' if status else ''} ORDER BY ld.id DESC LIMIT 300""", g.org['id'], *([status] if status else []))
    return render_template('dashboard/leads.html', rows=rows, status=status)

@bp.route('/leads/<int:lid>', methods=['POST'])
@org_required('editor')
def lead_update(lid):
    tenant_guard('leads', lid)
    st = request.form.get('status')
    if st in ('new', 'contacted', 'follow_up', 'converted', 'closed', 'lost'):
        db.run('UPDATE leads SET status = %s, notes = %s WHERE id = %s', st, request.form.get('notes', '')[:2000], lid)
        crm.emit('lead.updated', {'lead_id': lid, 'status': st, 'org_id': g.org['id']})
    return redirect(url_for('dashboard.leads'))

@bp.route('/reviews', methods=['GET', 'POST'])
@org_required()
def reviews():
    if request.method == 'POST':
        rid = request.form.get('review_id', type=int)
        r = db.one('SELECT r.* FROM reviews r JOIN listings l ON l.id = r.listing_id WHERE r.id = %s AND l.org_id = %s', rid, g.org['id']) or abort(404)
        if not E.current().get('review_reply'):
            flash('Replying to reviews is part of the Plus and Pro plans.', 'info'); return redirect(url_for('dashboard.plans'))
        db.run('UPDATE reviews SET response = %s WHERE id = %s', request.form.get('response', '')[:2000], rid)
        flash('Response published.', 'success'); return redirect(url_for('dashboard.reviews'))
    rows = db.all("""SELECT r.*, l.name AS listing_name FROM reviews r JOIN listings l ON l.id = r.listing_id WHERE l.org_id = %s AND r.status = 'published' ORDER BY r.id DESC""", g.org['id'])
    return render_template('dashboard/reviews.html', rows=rows)

@bp.route('/plans', methods=['GET', 'POST'])
@org_required('admin')
def plans():
    """Activate, upgrade one step (Basic->Plus->Pro, paying the difference less unused credit), renew, or buy add-ons."""
    fam = E.org_family(g.org)
    current = E.active_subscription(g.org['id'])
    quote = E.upgrade_quote(g.org['id'])
    renewal = E.renewal_quote(g.org['id'])
    regs = org_regs()
    rid = regs[0]['id'] if regs else None
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'activate' and not current:
            p = db.one("SELECT * FROM plans WHERE code = %s AND active AND family = %s", request.form.get('plan'), fam) or abort(400)
            price, meta = p['price_paise'], {'plan': p['code'], 'registration_id': rid, 'action': 'new'}
        elif action == 'upgrade' and quote and current:
            p = quote['plan']; price = quote['price']
            meta = {'plan': p['code'], 'registration_id': rid, 'action': 'upgrade', 'from': current['plan_code'], 'credit_paise': quote['credit']}
        elif action == 'renew' and renewal:
            p = db.one('SELECT * FROM plans WHERE code = %s', renewal['sub']['plan_code']); price = renewal['price']
            meta = {'plan': p['code'], 'registration_id': rid, 'action': 'renew', 'waived': renewal['waived']}
        elif action == 'addon':
            p = db.one("SELECT * FROM plans WHERE code = %s AND active AND family = 'addon'", request.form.get('plan')) or abort(400)
            if p['code'] == 'school_recruiter' and (fam != 'school' or not current or current['level'] < 2): abort(400)
            price, meta = p['price_paise'], {'plan': p['code'], 'action': 'addon'}
        else:
            abort(400)
        desc = f"{'Upgrade to ' if action == 'upgrade' else 'Renewal: ' if action == 'renew' else ''}{p['name']}"
        o = payments.create_order('addon' if action == 'addon' else 'plan', desc, price, user_id=g.user['id'], org_id=g.org['id'], gst_rate=float(p['gst_rate']),
                                  meta=meta, referral_code=S_ref(), items=[{'title': desc, 'qty': 1, 'unit_paise': price}])
        return redirect(url_for('pay.checkout', public_id=o['public_id']))
    ladder = db.all("SELECT * FROM plans WHERE active AND family = %s AND stream <> 'founding_partner' ORDER BY level", fam)
    addons = db.all("SELECT * FROM plans WHERE active AND family = 'addon' AND code IN ('school_recruiter','sponsored_placement') ORDER BY sort")
    if fam != 'school': addons = [a for a in addons if a['code'] != 'school_recruiter']
    subs = db.all("SELECT s.*, p.name FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.org_id = %s ORDER BY s.id DESC", g.org['id'])
    return render_template('dashboard/plans.html', ladder=ladder, current=current, quote=quote, renewal=renewal, addons=addons, subs=subs, org=g.org,
                           ent=E.current(), labels=E.FEATURE_LABELS, fam=fam)

@payments.fulfiller('addon')
def _fulfil_addon(order):
    p = db.one('SELECT * FROM plans WHERE code = %s', order['meta']['plan'])
    days = p['grants'].get('ad_days') or (365 if p['interval'] == 'annual' else 30)
    db.insert('subscriptions', dict(org_id=order['org_id'], plan_code=p['code'], ends_at=datetime.date.today() + datetime.timedelta(days=days),
              order_id=order['id'], amount_paise=order['subtotal_paise']), returning=None)
    if p['grants'].get('ad_days'):
        db.insert('ad_placements', dict(placement='directory', org_id=order['org_id'], title='Sponsored banner — set up in your dashboard', link_url='/',
                  starts_on=datetime.date.today(), ends_on=datetime.date.today() + datetime.timedelta(days=days), active=False, status='draft', order_id=order['id']), returning=None)
    notify.notify(order['user_id'], f"{p['name']} activated", 'Thank you for your purchase.', '/dashboard/plans', mail=True)

# ---- sponsored banners (self-serve; approved by the Growth desk) ----
@bp.route('/promote', methods=['GET', 'POST'])
@org_required('editor')
def promote():
    if request.method == 'POST':
        ad = db.one("SELECT * FROM ad_placements WHERE id = %s AND org_id = %s", request.form.get('id', type=int), g.org['id']) or abort(404)
        data = dict(title=request.form.get('title', '')[:120], link_url=request.form.get('link_url', '')[:500] or '/', status='pending', active=False,
                    placement=request.form.get('placement') if request.form.get('placement') in ('home', 'directory', 'school_match', 'jobs', 'resources') else 'directory',
                    city=request.form.get('city', '')[:60] or None)
        if request.files.get('image') and request.files['image'].filename:
            try: data['image_url'] = storage.save(request.files['image'], folder='ads', kinds=('image',))['url']
            except storage.UploadError as e: flash(str(e), 'error'); return redirect(url_for('dashboard.promote'))
        db.update('ad_placements', ad['id'], data)
        notify.notify_staff('Sponsored banner awaiting approval', data['title'], '/admin/growth')
        flash('Submitted — your banner goes live after a quick review.', 'success'); return redirect(url_for('dashboard.promote'))
    ads = db.all('SELECT * FROM ad_placements WHERE org_id = %s ORDER BY id DESC', g.org['id'])
    return render_template('dashboard/promote.html', ads=ads, plan=db.one("SELECT * FROM plans WHERE code = 'sponsored_placement'"))

# ---- jobs ----
@bp.route('/jobs')
@org_required()
def jobs():
    rows = db.all("""SELECT j.*, (SELECT count(*) FROM job_applications a WHERE a.job_id = j.id) apps FROM jobs j WHERE j.org_id = %s ORDER BY j.id DESC""", g.org['id'])
    return render_template('dashboard/jobs.html', rows=rows)

JOB_FIELDS = ('title', 'role', 'board', 'employment_type', 'experience', 'qualifications', 'city', 'state', 'description')
@bp.route('/jobs/new', methods=['GET', 'POST'])
@bp.route('/jobs/<int:jid>/edit', methods=['GET', 'POST'])
@org_required('editor')
def job_edit(jid=None):
    j = tenant_guard('jobs', jid) if jid else None
    listings = db.all('SELECT id, name, city, state FROM listings WHERE org_id = %s', g.org['id'])
    if request.method == 'POST':
        f = request.form
        if not f.get('title') or not f.get('description'):
            flash('Title and description are required.', 'error'); return render_template('dashboard/job_edit.html', j=f, listings=listings, states=F.INDIAN_STATES)
        data = {k: (f.get(k) or '').strip()[:6000] or None for k in JOB_FIELDS}
        data.update(subjects=[s.strip() for s in f.get('subjects', '').split(',') if s.strip()][:20],
                    grades=[s.strip() for s in f.get('grades', '').split(',') if s.strip()][:12],
                    salary_min=f.get('salary_min', type=int), salary_max=f.get('salary_max', type=int), show_salary=bool(f.get('show_salary')),
                    listing_id=f.get('listing_id', type=int) if any(l['id'] == f.get('listing_id', type=int) for l in listings) else (listings[0]['id'] if listings else None),
                    closes_on=f.get('closes_on') or None)
        publish = f.get('action') == 'publish'
        if publish and not (j and j['status'] == 'published'):
            live = db.val("SELECT count(*) FROM jobs WHERE org_id = %s AND status = 'published'", g.org['id'])
            if not E.limit_ok('jobs_limit', live):
                flash(f"Your plan allows {E.current()['jobs_limit']} active job post(s). Saved as draft — close a job or upgrade to publish more.", 'warning')
                publish = False; f = dict(f); f['action'] = 'draft'
        if j:
            if publish and j['status'] != 'published': data.update(status='published', published_at=datetime.datetime.now(datetime.timezone.utc))
            elif f.get('action') == 'close': data['status'] = 'closed'
            db.update('jobs', jid, dict(data, updated_at=datetime.datetime.now(datetime.timezone.utc)))
        else:
            data.update(org_id=g.org['id'], created_by=g.user['id'], slug=L.unique_slug('jobs', f"{data['title']} {g.org['name']}"),
                        status='published' if publish else 'draft', published_at=datetime.datetime.now(datetime.timezone.utc) if publish else None)
            jid = db.insert('jobs', data)
        audit('job.saved', 'job', jid, {'publish': publish}, org_id=g.org['id'])
        flash('Job published — teachers can now apply.' if publish else 'Job saved.', 'success')
        return redirect(url_for('dashboard.jobs'))
    return render_template('dashboard/job_edit.html', j=j or {}, listings=listings, states=F.INDIAN_STATES)

@bp.route('/jobs/<int:jid>')
@org_required()
def job_apps(jid):
    j = tenant_guard('jobs', jid)
    rows = db.all("""SELECT a.*, u.name, u.email, u.phone, tp.slug AS profile_slug, tp.headline FROM job_applications a JOIN users u ON u.id = a.teacher_id
                     LEFT JOIN teacher_profiles tp ON tp.user_id = a.teacher_id WHERE a.job_id = %s ORDER BY a.id DESC""", jid)
    db.run("UPDATE job_applications SET status = 'viewed' WHERE job_id = %s AND status = 'applied'", jid)
    return render_template('dashboard/job_apps.html', j=j, rows=rows)

@bp.route('/applications/<int:aid>/status', methods=['POST'])
@org_required('editor')
def application_status(aid):
    a = db.one('SELECT a.*, j.org_id, j.title FROM job_applications a JOIN jobs j ON j.id = a.job_id WHERE a.id = %s', aid) or abort(404)
    if a['org_id'] != g.org['id']: abort(404)
    st = request.form.get('status')
    if st in ('shortlisted', 'interview', 'offered', 'hired', 'rejected'):
        db.run('UPDATE job_applications SET status = %s, updated_at = now() WHERE id = %s', st, aid)
        notify.notify(a['teacher_id'], f"Application update: {a['title']}", f"Your application status is now: {st}.", '/dashboard/applications', mail=True)
    return redirect(url_for('dashboard.job_apps', jid=a['job_id']))

@bp.route('/applications/<int:aid>/cv')
@org_required()
def application_cv(aid):
    a = db.one('SELECT a.*, j.org_id FROM job_applications a JOIN jobs j ON j.id = a.job_id WHERE a.id = %s', aid) or abort(404)
    if a['org_id'] != g.org['id']: abort(404)
    if a['cv_url']: return redirect(url_for('privacy.private_file', ref=a['cv_url']))
    if a['cv_snapshot']:
        from ..lib import cv as CV
        from flask import Response
        u = db.one('SELECT name, email, phone, city FROM users WHERE id = %s', a['teacher_id'])
        audit('application.cv_viewed', 'job_application', aid, org_id=g.org['id'])
        return Response(CV.render_pdf(a['cv_snapshot'], [u['city'], u['email'], u['phone']]), mimetype='application/pdf')
    abort(404)

@bp.route('/jobs/<int:jid>/boost', methods=['POST'])
@org_required('admin')
def job_boost(jid):
    j = tenant_guard('jobs', jid)
    free = E.current().get('featured_jobs') or 0
    used = db.val("SELECT count(*) FROM audit_log WHERE org_id = %s AND action = 'job.free_boost' AND created_at > date_trunc('month', now())", g.org['id'])
    if used < free:
        db.run('UPDATE jobs SET featured_until = current_date + 30 WHERE id = %s', jid)
        audit('job.free_boost', 'job', jid, org_id=g.org['id'])
        flash(f'Job featured for 30 days ({free - used - 1} free boosts left this month).', 'success'); return redirect(url_for('dashboard.jobs'))
    p = db.one("SELECT * FROM plans WHERE code = 'job_boost' AND active") or abort(404)
    o = payments.create_order('job_boost', f"{p['name']}: {j['title']}", p['price_paise'], user_id=g.user['id'], org_id=g.org['id'], meta={'job_id': jid},
                              items=[{'title': p['name'], 'qty': 1, 'unit_paise': p['price_paise']}])
    return redirect(url_for('pay.checkout', public_id=o['public_id']))

@payments.fulfiller('job_boost')
def _boost(order):
    db.run("UPDATE jobs SET featured_until = current_date + 30 WHERE id = %s", order['meta']['job_id'])

# ---- team (multi-user tenant) ----
@bp.route('/team', methods=['GET', 'POST'])
@org_required('admin')
def team():
    if request.method == 'POST':
        if request.form.get('remove'):
            uid = request.form.get('remove', type=int)
            if uid != g.user['id']: db.run("DELETE FROM org_members WHERE org_id = %s AND user_id = %s AND role <> 'owner'", g.org['id'], uid)
        else:
            email = request.form.get('email', '').strip().lower(); role = request.form.get('role') if request.form.get('role') in ('admin', 'editor', 'viewer') else 'editor'
            tok = secrets.token_urlsafe(24)
            db.insert('org_invites', dict(org_id=g.org['id'], email=email, role=role, token=tok, invited_by=g.user['id']), returning=None)
            link = f"{current_app.config['SITE_URL']}{url_for('dashboard.accept_invite', token=tok)}"
            notify.email(email, f"You're invited to manage {g.org['name']} on The School Expert™", f"{g.user['name']} invited you as {role}. Accept: {link}")
            if current_app.config['DEV_SHOW_OTP']: flash(f'Development mode: invite link {link}', 'info')
            flash('Invitation sent.', 'success')
        return redirect(url_for('dashboard.team'))
    members = db.all('SELECT u.id, u.name, u.email, m.role FROM org_members m JOIN users u ON u.id = m.user_id WHERE m.org_id = %s', g.org['id'])
    invites = db.all('SELECT * FROM org_invites WHERE org_id = %s AND accepted_at IS NULL', g.org['id'])
    return render_template('dashboard/team.html', members=members, invites=invites)

@bp.route('/invite/<token>')
def accept_invite(token):
    inv = db.one('SELECT * FROM org_invites WHERE token = %s AND accepted_at IS NULL', token) or abort(404)
    if g.user['email'].lower() != inv['email'].lower() or g.user['account_type'] != 'organisation':
        flash('Please log in with the invited email address (an organisation account).', 'error'); return redirect(url_for('public.home'))
    db.run('INSERT INTO org_members (org_id, user_id, role) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING', inv['org_id'], g.user['id'], inv['role'])
    db.run('UPDATE org_invites SET accepted_at = now() WHERE id = %s', inv['id'])
    session['org_id'] = inv['org_id']
    flash('You have joined the organisation.', 'success'); return redirect(url_for('dashboard.home'))

# ---- campuses ----
@bp.route('/campuses/new', methods=['POST'])
@org_required('admin')
def new_campus():
    regs = org_regs()
    main = next((r for r in regs if r['grp'] == 'schools'), None) or abort(400)
    if not E.limit_ok('campuses_limit', len([r for r in regs if r['grp'] == 'schools'])):
        flash('Multiple campuses are part of School - Pro.', 'info'); return redirect(url_for('dashboard.plans'))
    rid = db.insert('registrations', dict(form_slug=main['form_slug'], user_id=g.user['id'], org_id=g.org['id']))
    flash('New campus registration started under your organisation. Its listing will be linked to your main school page.', 'info')
    return redirect(url_for('register.step', rid=rid, si=0))

# ---- marketplace seller ----
@bp.route('/products')
@org_required()
def products():
    seller = E.current().get('level', 0) >= 1 and E.current().get('products_limit', 0) != 0
    rows = db.all('SELECT * FROM products WHERE seller_org_id = %s ORDER BY id DESC', g.org['id'])
    return render_template('dashboard/products.html', rows=rows, seller=seller)

@bp.route('/products/new', methods=['GET', 'POST'])
@bp.route('/products/<int:pid>/edit', methods=['GET', 'POST'])
@org_required('editor')
def product_edit(pid=None):
    from .marketplace import CATEGORIES
    p = None
    if pid:
        p = db.one('SELECT * FROM products WHERE id = %s AND seller_org_id = %s', pid, g.org['id']) or abort(404)
    if not p and not E.limit_ok('products_limit', db.val("SELECT count(*) FROM products WHERE seller_org_id = %s AND status <> 'archived'", g.org['id'])):
        flash(f"Your plan allows {E.current().get('products_limit') or 0} products. Upgrade to list more.", 'info'); return redirect(url_for('dashboard.plans'))
    if request.method == 'POST':
        f = request.form
        try:
            price = int(round(float(f.get('price', '0')) * 100)); mrp = int(round(float(f.get('mrp') or 0) * 100)) or None
        except ValueError:
            flash('Enter valid prices.', 'error'); return redirect(request.url)
        if not f.get('title') or price <= 0 or f.get('category') not in CATEGORIES:
            flash('Title, category and price are required.', 'error'); return redirect(request.url)
        imgs = list(p['images']) if p else []
        for fs in request.files.getlist('images'):
            if fs and fs.filename:
                try: imgs.append(storage.save(fs, folder='products', kinds=('image',))['url'])
                except storage.UploadError as e: flash(str(e), 'error')
        tiers = []
        for i in range(3):
            q = f.get(f'tier_qty_{i}', type=int); pr = f.get(f'tier_price_{i}', type=float)
            if q and pr: tiers.append({'min_qty': q, 'price_paise': int(pr * 100)})
        data = dict(title=f['title'][:200], category=f['category'], brand=f.get('brand', '')[:80], summary=f.get('summary', '')[:300], description=f.get('description', '')[:8000],
                    price_paise=price, mrp_paise=mrp, stock=f.get('stock', 0, type=int), grade=f.get('grade', '')[:40], images=imgs[:8], bulk_tiers=tiers)
        if p:
            data['status'] = 'pending' if p['status'] in ('rejected', 'draft') else p['status']
            db.update('products', pid, data)
        else:
            data.update(seller_org_id=g.org['id'], slug=L.unique_slug('products', f['title']), status='pending')
            pid = db.insert('products', data)
            notify.notify_staff('Product awaiting approval', f['title'], '/admin/products')
        flash('Product saved — new products appear after a quick quality check.', 'success'); return redirect(url_for('dashboard.products'))
    return render_template('dashboard/product_edit.html', p=p or {}, cats=CATEGORIES)

@bp.route('/sales')
@org_required()
def sales():
    rows = db.all("""SELECT o.invoice_no, o.created_at, o.address, o.status AS order_status, s.id AS shipment_id, s.status, s.courier, s.tracking_no, oi.title, oi.qty, oi.unit_paise
                     FROM order_items oi JOIN orders o ON o.id = oi.order_id LEFT JOIN shipments s ON s.order_id = o.id AND s.seller_org_id = oi.seller_org_id
                     WHERE oi.seller_org_id = %s AND o.status IN ('paid','fulfilled','shipped','delivered') ORDER BY o.id DESC""", g.org['id'])
    return render_template('dashboard/sales.html', rows=rows)

@bp.route('/sales/<int:sid>', methods=['POST'])
@org_required('editor')
def ship(sid):
    s = db.one('SELECT * FROM shipments WHERE id = %s AND seller_org_id = %s', sid, g.org['id']) or abort(404)
    db.run('UPDATE shipments SET courier = %s, tracking_no = %s, status = %s, updated_at = now() WHERE id = %s',
           request.form.get('courier', '')[:60], request.form.get('tracking_no', '')[:60], request.form.get('status', 'shipped')[:20], sid)
    o = db.one('SELECT * FROM orders WHERE id = %s', s['order_id'])
    notify.notify(o['user_id'], 'Your order has shipped', f"{request.form.get('courier')} {request.form.get('tracking_no')}", '/dashboard/orders', mail=True)
    return redirect(url_for('dashboard.sales'))

@bp.route('/referrals')
def referrals():
    """Affiliate / referral stream: every account gets a link; commission is credited when a referred order is paid."""
    rc = db.one('SELECT * FROM referral_codes WHERE user_id = %s AND active ORDER BY created_at LIMIT 1', g.user['id'])
    if not rc:
        base = ''.join(ch for ch in (g.org['name'] if g.org else g.user['name']).upper() if ch.isalnum())[:8] or 'TSE'
        code = f"{base}{secrets.randbelow(9000) + 1000}"
        kind = 'partner' if g.org else ('ambassador' if g.user['account_type'] in ('parent', 'teacher') else 'affiliate')
        pct = {'partner': 10, 'ambassador': 10, 'affiliate': 12}[kind]
        db.insert('referral_codes', dict(code=code, user_id=g.user['id'], org_id=g.org['id'] if g.org else None, kind=kind, commission_pct=pct), returning=None)
        rc = db.one('SELECT * FROM referral_codes WHERE code = %s', code)
    rows = db.all("""SELECT r.*, o.description, o.invoice_no, o.kind AS order_kind FROM referrals r LEFT JOIN orders o ON o.id = r.order_id
                     WHERE r.code = %s ORDER BY r.id DESC LIMIT 100""", rc['code'])
    totals = db.one("""SELECT count(*) n, COALESCE(sum(commission_paise) FILTER (WHERE status IN ('pending','approved')),0) due,
                       COALESCE(sum(commission_paise) FILTER (WHERE status = 'paid'),0) paid FROM referrals WHERE code = %s""", rc['code'])
    return render_template('dashboard/referrals.html', rc=rc, rows=rows, totals=totals)
