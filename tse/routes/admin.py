"""Back office for The School Expert™ team."""
import json, datetime, csv, io
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, Response, current_app
from ..db import db
from ..lib import forms as F, listings as L, payments, notify, storage, crm
from ..lib.auth import staff_required
from ..lib.security import decrypt_json, audit, client_ip
from ..lib.auth import fresh_auth
from .directory import recompute_rating

bp = Blueprint('admin', __name__, url_prefix='/admin')

@bp.before_request
@staff_required()
def _guard():
    """Back office: staff only, optional office/VPN IP allow-list, every request logged."""
    allow = current_app.config.get('ADMIN_IP_ALLOWLIST')
    if allow:
        import ipaddress
        ip = ipaddress.ip_address(client_ip())
        if not any(ip in ipaddress.ip_network(n, strict=False) for n in allow):
            audit('security.admin_ip_blocked', 'user', g.user['id'] if g.user else None, {'ip': str(ip)}); abort(403)
    if request.method != 'GET':
        audit('admin.request', 'endpoint', request.endpoint, {'method': request.method})

@bp.route('/')
def index():
    k = dict(
        pending=db.val("SELECT count(*) FROM registrations WHERE status IN ('submitted','under_review','payment_pending')"),
        verified=db.val("SELECT count(*) FROM registrations WHERE status = 'verified'"),
        users=db.val("SELECT count(*) FROM users WHERE status = 'active'"),
        revenue=db.val("SELECT COALESCE(sum(total_paise),0) FROM orders WHERE status IN ('paid','fulfilled','shipped','delivered')"),
        revenue30=db.val("SELECT COALESCE(sum(total_paise),0) FROM orders WHERE status IN ('paid','fulfilled','shipped','delivered') AND paid_at > now() - interval '30 days'"),
        leads=db.val("SELECT count(*) FROM leads WHERE created_at > now() - interval '30 days'"),
        expert=db.val("SELECT count(*) FROM expert_requests WHERE status IN ('new','in_review','paid')"),
        pa=db.val("SELECT count(*) FROM pa_requests WHERE status IN ('paid','in_progress')"),
        moderation=db.val("SELECT (SELECT count(*) FROM posts WHERE status = 'pending') + (SELECT count(*) FROM comments WHERE status = 'pending') + (SELECT count(*) FROM content_reports WHERE status = 'open') + (SELECT count(*) FROM reviews WHERE status = 'pending') + (SELECT count(*) FROM corner_submissions WHERE status = 'pending') + (SELECT count(*) FROM products WHERE status = 'pending')"),
        dsr=db.val("SELECT count(*) FROM data_requests WHERE status IN ('open','in_progress')"),
        dsr_overdue=db.val("SELECT count(*) FROM data_requests WHERE status IN ('open','in_progress') AND due_at < now() + interval '15 days'"),
        tickets=db.val("SELECT count(*) FROM support_tickets WHERE status IN ('open','pending')"),
        outbox_failed=db.val("SELECT count(*) FROM outbox WHERE status = 'failed'"),
    )
    streams = db.all("""SELECT kind, count(*) n, sum(total_paise) amt FROM orders WHERE status IN ('paid','fulfilled','shipped','delivered') GROUP BY kind ORDER BY amt DESC""")
    recent = db.all("SELECT r.*, c.label FROM registrations r JOIN categories c ON c.slug = r.form_slug WHERE r.status <> 'draft' ORDER BY r.updated_at DESC LIMIT 10")
    mix = db.all("""SELECT p.family, p.level, count(*) n FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.status = 'active'
                     AND (s.ends_at IS NULL OR s.ends_at >= current_date) AND p.family IN ('school','vendor') GROUP BY 1,2""")
    tiers = {f: {l: 0 for l in (1, 2, 3)} for f in ('school', 'vendor')}
    for m in mix: tiers[m['family']][m['level']] = m['n']
    k.update(arr=db.val("""SELECT COALESCE(sum(p.price_paise),0) FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.status = 'active'
                          AND (s.ends_at IS NULL OR s.ends_at >= current_date) AND p.interval = 'annual'"""),
             expiring=db.val("""SELECT count(*) FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.status = 'active' AND p.family IN ('school','vendor')
                               AND s.ends_at BETWEEN current_date AND current_date + 30"""),
             unpaid_orgs=db.val("""SELECT count(*) FROM organisations o WHERE NOT EXISTS (SELECT 1 FROM subscriptions s JOIN plans p ON p.code = s.plan_code
                                  WHERE s.org_id = o.id AND s.status = 'active' AND p.family IN ('school','vendor'))"""),
             matches=db.val("SELECT count(*) FROM school_match_sessions WHERE created_at > now() - interval '30 days'"),
             ads_pending=db.val("SELECT count(*) FROM ad_placements WHERE status = 'pending'"),
             payouts_due=db.val("SELECT COALESCE(sum(net_paise),0) FROM seller_ledger WHERE status IN ('pending','payable')"))
    return render_template('admin/index.html', k=k, streams=streams, recent=recent, tiers=tiers)

# ---------------- registrations & verification ----------------
@bp.route('/registrations')
def registrations():
    a = request.args; where = ['1=1']; args = []
    if a.get('status'): where.append('r.status = %s'); args.append(a['status'])
    else: where.append("r.status <> 'draft'")
    if a.get('form'): where.append('r.form_slug = %s'); args.append(a['form'])
    if a.get('q'): where.append('r.answers::text ILIKE %s'); args.append(f"%{a['q']}%")
    rows = db.all(f"""SELECT r.*, c.label, u.email, l.slug AS listing_slug FROM registrations r JOIN categories c ON c.slug = r.form_slug LEFT JOIN users u ON u.id = r.user_id
                      LEFT JOIN listings l ON l.registration_id = r.id WHERE {' AND '.join(where)} ORDER BY r.updated_at DESC LIMIT 300""", *args)
    forms = db.all('SELECT slug, label FROM categories ORDER BY sort, label')
    if a.get('export') == 'csv':
        out = io.StringIO(); w = csv.writer(out); w.writerow(['id', 'form', 'status', 'name', 'email', 'progress', 'submitted_at'])
        for r in rows:
            d = F.get(r['form_slug']); w.writerow([r['id'], r['form_slug'], r['status'], F.answer_by_role(d, r['answers'], 'name'), r['email'], r['progress'], r['submitted_at']])
        audit('admin.export', 'registrations', None, {'n': len(rows)})
        return Response(out.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=registrations.csv'})
    for r in rows: r['name'] = F.answer_by_role(F.get(r['form_slug']), r['answers'], 'name')
    return render_template('admin/registrations.html', rows=rows, forms=forms, a=a)

CHECKS = ['Identity / organisation verified', 'Registration / affiliation documents checked', 'Qualifications verified', 'Experience verified',
          'Contact details verified', 'Portfolio / samples reviewed', 'References checked', 'Interview / call conducted', 'Child-safeguarding policy seen', 'Photos reviewed (no identifiable children without consent)']

def form_checks(defn):
    """The verification checklist written in the form document (internal-use block) where it has one, else the standard list."""
    return (defn.get('internal') or {}).get('checks') or CHECKS

def form_statuses(defn):
    return (defn.get('internal') or {}).get('statuses') or ['Registered', 'Under Review', 'Verified', 'Empanelled', 'Inactive']

@bp.route('/registrations/<int:rid>', methods=['GET', 'POST'])
@fresh_auth(15)
def registration(rid):
    reg = db.one('SELECT r.*, c.label, c.grp, c.listed FROM registrations r JOIN categories c ON c.slug = r.form_slug WHERE r.id = %s', rid) or abort(404)
    defn = F.get(reg['form_slug'])
    if request.method == 'POST':
        act = request.form.get('action')
        checks = dict(reg['checks'])
        clist = form_checks(defn)
        for i, c in enumerate(clist): checks[c] = bool(request.form.get('chk_' + str(i)))
        spec = defn.get('internal') or {}
        internal = dict(reg.get('internal') or {})
        if spec.get('classification'): internal['classification'] = [c for c in request.form.getlist('classification') if c in spec['classification']]
        if spec.get('tags'): internal['tags'] = {t: request.form.get('tag_' + str(i), '')[:120] for i, t in enumerate(spec['tags'])}
        for key, label, kind in [tuple(x) for x in spec.get('fields', [])]:
            v = request.form.get('int_' + key, '')[:200]
            if isinstance(kind, list) and v and v not in kind: v = ''
            internal[key] = v
        db.run('UPDATE registrations SET internal = %s WHERE id = %s', db.Json(internal), rid)
        tags = [t.strip() for t in request.form.get('tags', '').split(',') if t.strip()]
        st = request.form.get('engagement_status') or None
        if st and st not in form_statuses(defn): st = None
        db.run('UPDATE registrations SET checks = %s, internal_tags = %s, engagement_status = %s, review_notes = %s WHERE id = %s',
               db.Json(checks), tags, st, request.form.get('notes', '')[:4000], rid)
        msg = None
        if act == 'verify':
            db.run("UPDATE registrations SET status = 'verified', verified_at = now(), verified_by = %s WHERE id = %s", g.user['id'], rid)
            lid = L.sync(rid)
            if lid and request.form.get('in_house'): db.run('UPDATE listings SET in_house_panel = true WHERE id = %s', lid)
            notify.notify(reg['user_id'], 'Your registration is verified', f"{reg['label']}: your profile is now live on The School Expert™.", '/dashboard', mail=True)
            crm.emit('registration.verified', {'registration_id': rid, 'form': reg['form_slug'], 'name': F.answer_by_role(defn, reg['answers'], 'name')})
            msg = 'Verified and published.'
        elif act == 'changes':
            db.run("UPDATE registrations SET status = 'changes_requested' WHERE id = %s", rid)
            notify.notify(reg['user_id'], 'Changes requested on your registration', request.form.get('notes', ''), f'/register/r/{rid}/0', mail=True)
            msg = 'Changes requested.'
        elif act == 'reject':
            db.run("UPDATE registrations SET status = 'rejected' WHERE id = %s", rid); db.run('UPDATE listings SET is_published = false WHERE registration_id = %s', rid)
            notify.notify(reg['user_id'], 'Registration not approved', request.form.get('notes', ''), '/dashboard', mail=True); msg = 'Rejected.'
        elif act == 'suspend':
            db.run("UPDATE registrations SET status = 'suspended' WHERE id = %s", rid); db.run('UPDATE listings SET is_published = false WHERE registration_id = %s', rid); msg = 'Suspended.'
        elif act == 'resync':
            L.sync(rid); msg = 'Listing refreshed.'
        audit(f'admin.registration.{act}', 'registration', rid, org_id=reg['org_id'])
        flash(msg or 'Saved.', 'success'); return redirect(url_for('admin.registration', rid=rid))
    priv = decrypt_json(reg['private_enc'])
    audit('admin.registration.viewed_private', 'registration', rid, org_id=reg['org_id'])
    answers = dict(reg['answers']); answers.update(priv)
    secs = []
    for s in defn['sections']:
        items = []
        for f in s['fields']:
            v = reg['files'].get(f['key']) if f['type'] in ('file', 'files') else answers.get(f['key'])
            if F.is_empty(v) or f['type'] == 'heading': continue
            items.append((f, v if f['type'] in ('file', 'files', 'repeat') else F.display_value(f, v)))
        secs.append((s, items))
    listing = db.one('SELECT * FROM listings WHERE registration_id = %s', rid)
    user = db.one('SELECT * FROM users WHERE id = %s', reg['user_id'])
    consents = db.all("SELECT * FROM consents WHERE context = %s ORDER BY id", f'registration:{rid}')
    orders = db.all('SELECT * FROM orders WHERE org_id = %s ORDER BY id DESC', reg['org_id']) if reg['org_id'] else []
    record_id = f"{(defn.get('multi_record') or {}).get('id_prefix', 'TSE')}-{reg['id']:06d}"
    return render_template('admin/registration.html', reg=reg, defn=defn, secs=secs, listing=listing, user=user, checks=form_checks(defn), consents=consents,
                           orders=orders, spec=defn.get('internal') or {}, statuses=form_statuses(defn), record_id=record_id,
                           siblings=db.all('SELECT id, status FROM registrations WHERE (parent_registration_id = %s OR id = %s) AND id <> %s ORDER BY id',
                                           reg['parent_registration_id'] or rid, reg['parent_registration_id'] or rid, rid))

@bp.route('/listings', methods=['GET', 'POST'])
def listings():
    if request.method == 'POST':
        lid = request.form.get('id', type=int); act = request.form.get('action')
        if act == 'toggle': db.run('UPDATE listings SET is_published = NOT is_published WHERE id = %s', lid)
        elif act == 'feature': db.run("UPDATE listings SET featured_until = current_date + 365 WHERE id = %s", lid)
        elif act == 'unfeature': db.run('UPDATE listings SET featured_until = NULL WHERE id = %s', lid)
        elif act == 'panel': db.run('UPDATE listings SET in_house_panel = NOT in_house_panel WHERE id = %s', lid)
        elif act == 'tier': db.run('UPDATE listings SET tier = %s, tier_until = current_date + 365 WHERE id = %s', request.form.get('tier'), lid)
        audit(f'admin.listing.{act}', 'listing', lid); return redirect(request.referrer or url_for('admin.listings'))
    q = request.args.get('q', '')
    rows = db.all("""SELECT l.*, c.label AS category_label FROM listings l JOIN categories c ON c.slug = l.category
                     WHERE (%s = '' OR l.name ILIKE %s OR l.city ILIKE %s) ORDER BY l.id DESC LIMIT 300""", q, f'%{q}%', f'%{q}%')
    return render_template('admin/listings.html', rows=rows, q=q)

# ---------------- users & organisations ----------------
@bp.route('/users', methods=['GET', 'POST'])
@fresh_auth(15)
def users():
    if request.method == 'POST' and g.user['account_type'] == 'admin':
        uid = request.form.get('id', type=int); act = request.form.get('action')
        if act == 'suspend': db.run("UPDATE users SET status = 'suspended' WHERE id = %s AND account_type <> 'admin'", uid); db.run('DELETE FROM sessions WHERE user_id = %s', uid)
        elif act == 'activate': db.run("UPDATE users SET status = 'active' WHERE id = %s", uid)
        elif act == 'staff': db.run("UPDATE users SET account_type = 'staff', staff_role = %s WHERE id = %s AND account_type <> 'admin'", request.form.get('staff_role', 'support'), uid)
        elif act == 'ban': db.run('INSERT INTO community_bans (user_id, reason) VALUES (%s, %s) ON CONFLICT (user_id) DO NOTHING', uid, request.form.get('reason', 'Guidelines'))
        audit(f'admin.user.{act}', 'user', uid); return redirect(request.referrer)
    q = request.args.get('q', ''); t = request.args.get('type', '')
    rows = db.all("""SELECT * FROM users WHERE (%s = '' OR email ILIKE %s OR name ILIKE %s) AND (%s = '' OR account_type = %s) ORDER BY id DESC LIMIT 300""",
                  q, f'%{q}%', f'%{q}%', t, t)
    return render_template('admin/users.html', rows=rows, q=q, t=t)

@bp.route('/organisations', methods=['GET', 'POST'])
def organisations():
    if request.method == 'POST':
        oid = request.form.get('id', type=int); act = request.form.get('action')
        if act == 'founding': db.run('UPDATE organisations SET founding_partner = true, founding_partner_since = COALESCE(founding_partner_since, current_date), renewal_waived_until = COALESCE(renewal_waived_until, current_date + 1095) WHERE id = %s', oid)
        elif act == 'exclusive': db.run('UPDATE organisations SET exclusive_category = %s WHERE id = %s', request.form.get('category') or None, oid)
        elif act == 'suspend': db.run("UPDATE organisations SET status = 'suspended' WHERE id = %s", oid); db.run('UPDATE listings SET is_published = false WHERE org_id = %s', oid)
        audit(f'admin.org.{act}', 'organisation', oid); return redirect(request.referrer)
    rows = db.all("""SELECT o.*, (SELECT count(*) FROM org_members m WHERE m.org_id = o.id) members, (SELECT string_agg(p.name, ', ') FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.org_id = o.id AND s.status = 'active') plans
                     FROM organisations o ORDER BY o.id DESC LIMIT 300""")
    return render_template('admin/organisations.html', rows=rows)

# ---------------- orders & revenue ----------------
@bp.route('/orders')
def orders():
    a = request.args
    rows = db.all("""SELECT o.*, u.email FROM orders o LEFT JOIN users u ON u.id = o.user_id WHERE (%s = '' OR o.kind = %s) AND (%s = '' OR o.status = %s) ORDER BY o.id DESC LIMIT 300""",
                  a.get('kind', ''), a.get('kind', ''), a.get('status', ''), a.get('status', ''))
    kinds = [r['kind'] for r in db.all('SELECT DISTINCT kind FROM orders ORDER BY 1')]
    return render_template('admin/orders.html', rows=rows, kinds=kinds, a=a)

@bp.route('/orders/<int:oid>', methods=['GET', 'POST'])
@fresh_auth(15)
def order(oid):
    o = db.one('SELECT * FROM orders WHERE id = %s', oid) or abort(404)
    if request.method == 'POST':
        act = request.form.get('action')
        if act == 'refund' and g.user['account_type'] == 'admin':
            try: payments.refund(o, reason=request.form.get('reason', '')); flash('Refunded.', 'success')
            except Exception as e: flash(f'Refund failed: {e}', 'error')
        elif act == 'mark_paid' and g.user['account_type'] == 'admin':
            payments.mark_paid(o, 'manual:' + request.form.get('reference', '')[:60]); flash('Marked paid & fulfilled.', 'success')
        elif act in ('shipped', 'delivered'):
            db.run('UPDATE orders SET status = %s WHERE id = %s', act, oid)
        audit(f'admin.order.{act}', 'order', oid); return redirect(url_for('admin.order', oid=oid))
    items = db.all('SELECT * FROM order_items WHERE order_id = %s', oid)
    ships = db.all('SELECT * FROM shipments WHERE order_id = %s', oid)
    return render_template('admin/order.html', o=o, items=items, ships=ships)

@bp.route('/revenue')
def revenue():
    by_stream = db.all("""SELECT COALESCE(p.stream, o.kind) stream, count(*) n, sum(o.total_paise) total, sum(o.gst_paise) gst FROM orders o
                          LEFT JOIN plans p ON p.code = o.meta->>'plan' WHERE o.status IN ('paid','fulfilled','shipped','delivered') GROUP BY 1 ORDER BY total DESC""")
    by_month = db.all("""SELECT to_char(date_trunc('month', paid_at), 'Mon YYYY') m, sum(total_paise) total, count(*) n FROM orders
                         WHERE status IN ('paid','fulfilled','shipped','delivered') GROUP BY date_trunc('month', paid_at) ORDER BY date_trunc('month', paid_at) DESC LIMIT 12""")
    referrals = db.all('SELECT r.*, rc.user_id FROM referrals r JOIN referral_codes rc ON rc.code = r.code ORDER BY r.id DESC LIMIT 100')
    return render_template('admin/revenue.html', by_stream=by_stream, by_month=by_month, referrals=referrals)

# ---------------- CRM-lite ----------------
@bp.route('/leads')
def leads():
    rows = db.all("""SELECT ld.*, l.name AS listing_name FROM leads ld LEFT JOIN listings l ON l.id = ld.listing_id ORDER BY ld.id DESC LIMIT 300""")
    return render_template('admin/leads.html', rows=rows)

@bp.route('/expert-requests')
def expert_requests():
    from .ask import TOPICS
    rows = db.all('SELECT e.*, u.name, u.email FROM expert_requests e LEFT JOIN users u ON u.id = e.user_id ORDER BY e.id DESC LIMIT 300')
    return render_template('admin/expert_requests.html', rows=rows, topics=TOPICS)

@bp.route('/expert-requests/<int:rid>', methods=['GET', 'POST'])
def expert_request(rid):
    from .ask import TOPICS
    r = db.one('SELECT e.*, u.name, u.email, u.phone FROM expert_requests e LEFT JOIN users u ON u.id = e.user_id WHERE e.id = %s', rid) or abort(404)
    if request.method == 'POST':
        f = request.form; act = f.get('action')
        if act == 'quote':
            amt = int(float(f.get('amount', 0)) * 100)
            db.run("UPDATE expert_requests SET status = 'quoted', quote_paise = %s, panel = %s, staff_notes = %s, updated_at = now() WHERE id = %s", amt, f.get('panel'), f.get('notes', ''), rid)
            notify.notify(r['user_id'], 'Your Ask The School Expert options are ready', f"{'In-house panel' if f.get('panel') == 'in_house' else 'Referral'} — {payments.inr(amt)} + GST. {f.get('message', '')}", '/dashboard/requests', mail=True)
        elif act == 'match':
            lid = f.get('listing_id', type=int)
            db.run("UPDATE expert_requests SET status = 'matched', matched_listing_id = %s, staff_notes = %s, updated_at = now() WHERE id = %s", lid, f.get('notes', ''), rid)
            l = db.one('SELECT * FROM listings WHERE id = %s', lid)
            if l:
                db.insert('leads', dict(listing_id=lid, org_id=l['org_id'], source='ask_expert', user_id=r['user_id'], name=r['name'], email=r['email'], phone=r['phone'],
                          message=r['message'][:2000], verified=True), returning=None)
                db.insert('unlocks', dict(user_id=r['user_id'], listing_id=lid), returning=None) if not db.val('SELECT 1 FROM unlocks WHERE user_id = %s AND listing_id = %s', r['user_id'], lid) else None
                notify.notify(r['user_id'], 'We have matched you with an expert', l['name'], f"/l/{l['slug']}", mail=True)
                if l['org_id']: notify.notify_org(l['org_id'], 'New referral from The School Expert', r['message'][:200], '/dashboard/leads')
        elif act in ('in_review', 'completed', 'closed'):
            db.run('UPDATE expert_requests SET status = %s, staff_notes = %s, updated_at = now() WHERE id = %s', act, f.get('notes', ''), rid)
        audit(f'admin.expert.{act}', 'expert_request', rid); return redirect(url_for('admin.expert_request', rid=rid))
    experts = db.all("""SELECT l.id, l.name, l.city, l.category, l.in_house_panel FROM listings l JOIN categories c ON c.slug = l.category
                        WHERE l.is_published AND (c.grp IN ('experts','learning')) ORDER BY l.in_house_panel DESC, l.name""")
    return render_template('admin/expert_request.html', r=r, experts=experts, topics=TOPICS)

@bp.route('/pa')
def pa_list():
    rows = db.all('SELECT p.*, u.name, u.phone FROM pa_requests p JOIN users u ON u.id = p.user_id ORDER BY p.id DESC LIMIT 300')
    return render_template('admin/pa_list.html', rows=rows)

@bp.route('/pa/<int:rid>', methods=['GET', 'POST'])
def pa(rid):
    from .ask import PA_STAGES
    r = db.one('SELECT p.*, u.name, u.email, u.phone FROM pa_requests p JOIN users u ON u.id = p.user_id WHERE p.id = %s', rid) or abort(404)
    if request.method == 'POST':
        f = request.form
        if f.get('assign'): db.run("UPDATE pa_requests SET assigned_to = %s, status = 'in_progress' WHERE id = %s", f.get('assign', type=int), rid)
        if f.get('stage'):
            att = None
            if request.files.get('attachment') and request.files['attachment'].filename:
                att = storage.save(request.files['attachment'], private=True, folder='pa')['url']
            db.insert('pa_updates', dict(request_id=rid, stage=f['stage'], note=f.get('note', '')[:2000], attachment_url=att, created_by=g.user['id']), returning=None)
            st = 'completed' if f['stage'] == 'completed' else 'in_progress'
            db.run('UPDATE pa_requests SET status = %s WHERE id = %s', st, rid)
            notify.notify(r['user_id'], 'Personal Assistance update', dict(PA_STAGES).get(f['stage'], f['stage']) + (': ' + f.get('note') if f.get('note') else ''), f'/personal-assistance/{rid}', mail=True)
        audit('admin.pa.update', 'pa_request', rid); return redirect(url_for('admin.pa', rid=rid))
    updates = db.all('SELECT * FROM pa_updates WHERE request_id = %s ORDER BY created_at', rid)
    agents = db.all("SELECT id, name FROM users WHERE account_type IN ('admin','staff') AND status = 'active'")
    return render_template('admin/pa.html', r=r, updates=updates, stages=PA_STAGES, agents=agents)

# ---------------- moderation ----------------
@bp.route('/moderation', methods=['GET', 'POST'])
def moderation():
    if request.method == 'POST':
        t = request.form.get('type'); tid = request.form.get('id', type=int); act = request.form.get('action')
        table = {'post': 'posts', 'comment': 'comments', 'review': 'reviews', 'book_review': 'book_reviews', 'corner': 'corner_submissions', 'product': 'products', 'question': 'podcast_questions'}.get(t)
        if not table: abort(400)
        status = {'approve': 'published', 'reject': 'rejected' if t in ('review', 'book_review', 'corner', 'product', 'question') else 'removed', 'hide': 'hidden'}.get(act)
        if status:
            db.run(f'UPDATE {table} SET status = %s WHERE id = %s', status, tid)
            if t == 'review':
                recompute_rating(db.val('SELECT listing_id FROM reviews WHERE id = %s', tid))
            if t == 'question' and request.form.get('answer'):
                db.run("UPDATE podcast_questions SET answer = %s, status = 'answered' WHERE id = %s", request.form['answer'][:3000], tid)
        if request.form.get('report_id'):
            db.run("UPDATE content_reports SET status = %s, resolved_by = %s WHERE id = %s", 'actioned' if act in ('hide', 'reject') else 'dismissed', g.user['id'], request.form.get('report_id', type=int))
        audit(f'admin.moderation.{act}', t, tid); return redirect(url_for('admin.moderation'))
    q = dict(
        posts=db.all("SELECT p.*, u.name FROM posts p LEFT JOIN users u ON u.id = p.user_id WHERE p.status = 'pending' ORDER BY p.id"),
        comments=db.all("SELECT c.*, u.name FROM comments c LEFT JOIN users u ON u.id = c.user_id WHERE c.status = 'pending' ORDER BY c.id"),
        reviews=db.all("SELECT r.*, l.name AS listing FROM reviews r JOIN listings l ON l.id = r.listing_id WHERE r.status = 'pending'"),
        book_reviews=db.all("SELECT r.*, b.title FROM book_reviews r JOIN books b ON b.id = r.book_id WHERE r.status = 'pending'"),
        corner=db.all("SELECT * FROM corner_submissions WHERE status = 'pending' ORDER BY id"),
        products=db.all("SELECT p.*, o.name AS seller FROM products p LEFT JOIN organisations o ON o.id = p.seller_org_id WHERE p.status = 'pending'"),
        questions=db.all("SELECT q.*, p.title FROM podcast_questions q JOIN podcasts p ON p.id = q.podcast_id WHERE q.status = 'pending'"),
        reports=db.all("SELECT * FROM content_reports WHERE status = 'open' ORDER BY id"))
    return render_template('admin/moderation.html', q=q)

# ---------------- events (pass approvals) ----------------
@bp.route('/events/<int:eid>', methods=['GET', 'POST'])
def event(eid):
    e = db.one('SELECT * FROM events WHERE id = %s', eid) or abort(404)
    if request.method == 'POST':
        rid = request.form.get('reg_id', type=int)
        if request.form.get('action') == 'confirm':
            from .events import _confirm; _confirm(rid)
        elif request.form.get('action') == 'cancel':
            db.run("UPDATE event_registrations SET status = 'cancelled' WHERE id = %s", rid)
        elif request.form.get('action') == 'sponsor':
            db.run("UPDATE sponsorships SET status = %s WHERE id = %s", request.form.get('status'), request.form.get('sid', type=int))
        return redirect(url_for('admin.event', eid=eid))
    regs = db.all('SELECT er.*, u.name, u.email FROM event_registrations er LEFT JOIN users u ON u.id = er.user_id WHERE er.event_id = %s ORDER BY er.id', eid)
    sponsors = db.all('SELECT * FROM sponsorships WHERE event_id = %s', eid)
    return render_template('admin/event.html', e=e, regs=regs, sponsors=sponsors)

# ---------------- generic CMS ----------------
CMS = {
 'events': ('Events', [('title', 'text'), ('slug', 'slug'), ('kind', ('conference', 'roundtable', 'workshop', 'webinar', 'meetup', 'homeschool_meetup', 'storytelling', 'bookclub', 'expo')),
            ('summary', 'textarea'), ('body', 'md'), ('audience', 'array'), ('mode', ('online', 'offline', 'hybrid')), ('venue', 'text'), ('city', 'text'),
            ('starts_at', 'datetime'), ('ends_at', 'datetime'), ('price_paise', 'money'), ('member_price_paise', 'money'), ('capacity', 'int'),
            ('form_slug', 'text'), ('cover_url', 'image'), ('status', ('draft', 'published', 'cancelled', 'completed')), ('passes_require_approval', 'bool'),
            ('cpd_hours', 'int'), ('facilitator', 'text'), ('category', 'text')], 'starts_at DESC'),
 'courses': ('Teachers Hub — courses', [('title', 'text'), ('slug', 'slug'), ('category', 'text'), ('level', ('Beginner', 'Intermediate', 'Advanced')), ('summary', 'textarea'),
             ('instructor', 'text'), ('cpd_hours', 'int'), ('sort', 'int'), ('published', 'bool')], 'sort, id'),
 'course_lessons': ('Teachers Hub — course lessons', [('course_id', 'int'), ('position', 'int'), ('title', 'text'), ('minutes', 'int'), ('body', 'md')], 'course_id, position'),
 'tutorials': ('Teachers Hub — tutorials', [('title', 'text'), ('slug', 'slug'), ('category', 'text'), ('summary', 'textarea'), ('minutes', 'int'),
               ('steps', 'json'), ('published', 'bool')], 'category, title'),
 'podcasts': ('Podcasts & Webinars', [('title', 'text'), ('slug', 'slug'), ('kind', ('podcast', 'webinar')), ('guest', 'text'), ('guest_title', 'text'), ('summary', 'textarea'),
              ('body', 'md'), ('media_url', 'text'), ('cover_url', 'image'), ('audience', 'array'), ('tags', 'array'), ('duration_min', 'int'), ('published_at', 'datetime'),
              ('status', ('draft', 'published'))], 'published_at DESC NULLS FIRST'),
 'gallery_albums': ('Gallery albums', [('title', 'text'), ('slug', 'slug'), ('description', 'textarea'), ('event_id', 'int'), ('cover_url', 'image'), ('taken_on', 'date'), ('published', 'bool')], 'id DESC'),
 'newsletters': ('Newsletters (Industry & NewsWorms)', [('kind', ('industry', 'newsworms')), ('title', 'text'), ('slug', 'slug'), ('issue_no', 'int'), ('summary', 'textarea'), ('body', 'md'),
                 ('pdf_url', 'file'), ('cover_url', 'image'), ('age_band', 'text'), ('access', ('free', 'subscriber')), ('published_at', 'datetime')], 'id DESC'),
 'resources': ('Resources, worksheets & apps', [('kind', ('worksheet', 'kids_newspaper', 'homeschool', 'learning_app', 'teacher_resource', 'guide')), ('title', 'text'), ('slug', 'slug'),
               ('summary', 'textarea'), ('grade', 'text'), ('subject', 'text'), ('file_url', 'file'), ('external_url', 'text'), ('platform', 'text'), ('price_paise', 'money'), ('is_free', 'bool'), ('published', 'bool')], 'id DESC'),
 'books': ('Book Club books', [('title', 'text'), ('slug', 'slug'), ('author', 'text'), ('age_band', 'text'), ('language', 'text'), ('cover_url', 'image'), ('summary', 'textarea'), ('marketplace_product_id', 'int')], 'id DESC'),
 'products': ('Marketplace products', [('title', 'text'), ('slug', 'slug'), ('category', 'text'), ('brand', 'text'), ('summary', 'textarea'), ('description', 'md'), ('price_paise', 'money'),
              ('mrp_paise', 'money'), ('gst_rate', 'text'), ('stock', 'int'), ('grade', 'text'), ('is_tse', 'bool'), ('is_digital', 'bool'), ('digital_url', 'file'),
              ('status', ('draft', 'pending', 'published', 'rejected', 'archived'))], 'id DESC'),
 'initiatives': ('Initiatives page', [('title', 'text'), ('slug', 'slug'), ('tagline', 'text'), ('summary', 'textarea'), ('body', 'md'), ('cta_label', 'text'), ('cta_url', 'text'), ('icon', 'text'), ('sort', 'int'), ('published', 'bool')], 'sort'),
 'faqs': ('FAQs', [('section', 'text'), ('question', 'text'), ('answer', 'md'), ('sort', 'int')], 'sort'),
 'pages': ('Pages & policies', [('slug', 'text'), ('title', 'text'), ('path', 'text'), ('meta_description', 'text'), ('body_format', ('markdown', 'html')), ('body', 'md'), ('show_in_footer', 'bool')], 'slug'),
 'plans': ('Plans & pricing', [('code', 'text'), ('audience', ('school', 'vendor', 'provider', 'professional', 'teacher', 'parent')), ('stream', 'text'), ('name', 'text'), ('description', 'textarea'),
           ('price_paise', 'money'), ('gst_rate', 'text'), ('interval', ('one_time', 'monthly', 'annual')), ('family', ('school', 'vendor', 'addon', 'parent', 'teacher')), ('level', 'int'), ('badge', 'text'), ('highlight', 'text'), ('grants', 'json'), ('features', 'json'), ('active', 'bool'), ('sort', 'int')], 'sort'),
 'pa_services': ('Personal Assistance services', [('code', 'text'), ('name', 'text'), ('description', 'textarea'), ('price_paise', 'money'), ('sort', 'int'), ('active', 'bool')], 'sort'),
 'pa_cities': ('Personal Assistance cities', [('city', 'text'), ('state', 'text'), ('base_paise', 'money'), ('per_km_paise', 'money'), ('active', 'bool')], 'city'),
 'communities': ('Communities', [('slug', 'text'), ('name', 'text'), ('description', 'textarea'), ('view_roles', 'array'), ('post_roles', 'array'), ('premoderate', 'bool'), ('allow_comments', 'bool'), ('sort', 'int')], 'sort'),
 'ad_placements': ('Sponsored placements', [('placement', ('home', 'directory', 'school_match', 'resources', 'jobs', 'newsletter', 'marketplace', 'community_teachers')), ('title', 'text'), ('image_url', 'image'), ('link_url', 'text'), ('city', 'text'), ('org_id', 'int'), ('starts_on', 'date'), ('ends_on', 'date'), ('status', ('pending', 'approved', 'rejected')), ('active', 'bool')], 'id DESC'),
 'articles': ('Guides (SEO articles)', [('title', 'text'), ('slug', 'slug'), ('audience', ('parents', 'schools', 'vendors', 'teachers')), ('summary', 'textarea'), ('keywords', 'text'), ('cover_url', 'image'), ('body', 'md'), ('author', 'text'), ('published_at', 'datetime')], 'id DESC'),
 'referral_codes': ('Referral / affiliate codes', [('code', 'text'), ('user_id', 'int'), ('org_id', 'int'), ('kind', ('ambassador', 'affiliate', 'partner')), ('commission_pct', 'text'), ('active', 'bool')], 'created_at DESC'),
 'breach_incidents': ('Personal-data breach register', [('detected_at', 'datetime'), ('summary', 'textarea'), ('data_categories', 'text'), ('affected_count', 'int'), ('likely_impact', 'textarea'),
                      ('mitigation', 'textarea'), ('board_intimated_at', 'datetime'), ('board_report_at', 'datetime'), ('principals_notified_at', 'datetime'), ('status', ('open', 'contained', 'closed'))], 'detected_at DESC'),
}
PK = {'pages': 'slug', 'plans': 'code', 'pa_services': 'code', 'pa_cities': 'city', 'communities': 'slug', 'referral_codes': 'code'}

@bp.route('/cms')
def cms_index():
    counts = {t: db.val(f'SELECT count(*) FROM {t}') for t in CMS}
    return render_template('admin/cms_index.html', cms=CMS, counts=counts)

@bp.route('/cms/<table>')
def cms_list(table):
    if table not in CMS: abort(404)
    title, fields, order = CMS[table]
    rows = db.all(f'SELECT * FROM {table} ORDER BY {order} LIMIT 500')
    return render_template('admin/cms_list.html', table=table, title=title, fields=fields, rows=rows, pk=PK.get(table, 'id'))

def _coerce(t, raw, existing=None, key=None):
    if isinstance(t, tuple): return raw if raw in t else (t[0] if raw is None else raw)
    if t == 'bool': return raw == 'on'
    if t == 'int': return int(raw) if raw not in (None, '') else None
    if t == 'money': return int(round(float(raw) * 100)) if raw not in (None, '') else None
    if t == 'array': return [x.strip() for x in (raw or '').split(',') if x.strip()]
    if t == 'json':
        try: return db.Json(json.loads(raw or 'null'))
        except ValueError: raise ValueError(f'{key}: invalid JSON')
    if t in ('datetime', 'date'): return raw or None
    if t == 'slug': return L.slugify(raw) if raw else None
    return raw if raw != '' else None

@bp.route('/cms/<table>/new', methods=['GET', 'POST'])
@bp.route('/cms/<table>/<key>', methods=['GET', 'POST'])
def cms_edit(table, key=None):
    if table not in CMS: abort(404)
    title, fields, _ = CMS[table]; pk = PK.get(table, 'id')
    row = db.one(f'SELECT * FROM {table} WHERE {pk}::text = %s', key) if key else None
    if key and not row: abort(404)
    if request.method == 'POST':
        if request.form.get('delete') and row:
            db.run(f'DELETE FROM {table} WHERE {pk}::text = %s', key); audit('admin.cms.delete', table, key)
            flash('Deleted.', 'success'); return redirect(url_for('admin.cms_list', table=table))
        data = {}
        try:
            for name, t in fields:
                if t in ('image', 'file'):
                    fs = request.files.get(name)
                    if fs and fs.filename:
                        data[name] = storage.save(fs, folder='cms', kinds=('image',) if t == 'image' else ('image', 'doc'))['url']
                    elif request.form.get(name + '__url'): data[name] = request.form.get(name + '__url')
                    continue
                v = _coerce(t, request.form.get(name), row, name)
                if t == 'slug' and not v: v = L.unique_slug(table, request.form.get('title') or request.form.get('name') or 'item') if not row else row[name]
                data[name] = v
        except (ValueError, storage.UploadError) as e:
            flash(str(e), 'error'); return render_template('admin/cms_edit.html', table=table, title=title, fields=fields, row=dict(request.form), key=key)
        if table == 'events' and data.get('starts_at'):
            data['starts_at'] = data['starts_at'] + ':00+05:30' if len(data['starts_at']) == 16 else data['starts_at']
            if data.get('ends_at') and len(data['ends_at']) == 16: data['ends_at'] += ':00+05:30'
        if table == 'products' and not row: data['seller_org_id'] = None
        cols = list(data.keys())
        vals = [v for v in data.values()]
        if row:
            db.run(f"UPDATE {table} SET {', '.join(c + ' = %s' for c in cols)} WHERE {pk}::text = %s", *vals, key)
            newkey = data.get(pk) or key
        else:
            db.run(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", *vals)
            newkey = data.get(pk) or db.val(f'SELECT max(id) FROM {table}')
        audit('admin.cms.save', table, newkey)
        flash('Saved.', 'success')
        if table == 'gallery_albums': return redirect(url_for('admin.album_photos', aid=newkey))
        return redirect(url_for('admin.cms_list', table=table))
    return render_template('admin/cms_edit.html', table=table, title=title, fields=fields, row=row or {}, key=key)

@bp.route('/gallery/<int:aid>', methods=['GET', 'POST'])
def album_photos(aid):
    a = db.one('SELECT * FROM gallery_albums WHERE id = %s', aid) or abort(404)
    if request.method == 'POST':
        if request.form.get('delete'): db.run('DELETE FROM gallery_photos WHERE id = %s AND album_id = %s', request.form.get('delete', type=int), aid)
        else:
            if not request.form.get('consent_confirmed'):
                flash('Confirm that people (especially children) in these photos are not identifiable, or that written consent is on file.', 'error')
                return redirect(url_for('admin.album_photos', aid=aid))
            for fs in request.files.getlist('photos'):
                if fs and fs.filename:
                    try: db.insert('gallery_photos', dict(album_id=aid, url=storage.save(fs, folder='gallery', kinds=('image',))['url'], caption=request.form.get('caption', '')[:200], consent_confirmed=True), returning=None)
                    except storage.UploadError as e: flash(str(e), 'error')
        return redirect(url_for('admin.album_photos', aid=aid))
    photos = db.all('SELECT * FROM gallery_photos WHERE album_id = %s ORDER BY sort, id', aid)
    return render_template('admin/album.html', a=a, photos=photos)

# ---------------- forms manager ----------------
@bp.route('/forms', methods=['GET', 'POST'])
def forms_admin():
    if request.method == 'POST' and g.user['account_type'] == 'admin':
        fs = request.files.get('definition')
        try:
            d = json.loads(fs.read().decode('utf-8'))
            assert d.get('slug') and d.get('sections') and d.get('category') and d.get('label')
            from ..db.seed import upsert_form; upsert_form(d, bump=True)
            audit('admin.form.imported', 'form', d['slug']); flash(f"Form {d['slug']} imported.", 'success')
        except Exception as e:
            flash(f'Could not import: {e}', 'error')
        return redirect(url_for('admin.forms_admin'))
    rows = db.all("""SELECT f.slug, f.title, f.version, f.provisional, f.updated_at, c.label, c.grp, c.parent_access, c.school_access,
                     (SELECT count(*) FROM registrations r WHERE r.form_slug = f.slug) regs FROM form_definitions f JOIN categories c ON c.slug = f.slug ORDER BY c.sort, c.label""")
    return render_template('admin/forms.html', rows=rows)

@bp.route('/forms/<slug>.json')
def form_json(slug):
    d = db.one('SELECT f.definition, c.grp, c.label, c.entity FROM form_definitions f JOIN categories c ON c.slug = f.slug WHERE f.slug = %s', slug) or abort(404)
    body = dict(d['definition'], category=d['grp'], label=d['label'], entity=d['entity'])
    return Response(json.dumps(body, indent=1, ensure_ascii=False), mimetype='application/json', headers={'Content-Disposition': f'attachment; filename={slug}.json'})

@bp.route('/forms/<slug>/preview')
def form_preview(slug):
    defn = F.get(slug) or abort(404)
    return render_template('admin/form_preview.html', defn=defn, states=F.INDIAN_STATES)

# ---------------- DPDP ----------------
@bp.route('/dsr')
def dsr():
    rows = db.all('SELECT * FROM data_requests ORDER BY status, due_at')
    return render_template('admin/dsr.html', rows=rows)

@bp.route('/dsr/<int:rid>', methods=['GET', 'POST'])
@fresh_auth(15)
def dsr_item(rid):
    r = db.one('SELECT * FROM data_requests WHERE id = %s', rid) or abort(404)
    if request.method == 'POST':
        st = request.form.get('status')
        db.run('UPDATE data_requests SET status = %s, response = %s, handled_by = %s, closed_at = CASE WHEN %s IN (\'completed\',\'rejected\') THEN now() ELSE NULL END WHERE id = %s',
               st, request.form.get('response', '')[:5000], g.user['id'], st, rid)
        if request.form.get('erase_now') and r['user_id'] and g.user['account_type'] == 'admin':
            from ..lib.retention import anonymise_user; anonymise_user(r['user_id'])
        notify.email(r['email'], f'Update on your request #{rid}', request.form.get('response', ''))
        audit('admin.dsr.update', 'data_request', rid, {'status': st}); flash('Updated and the requester has been emailed.', 'success')
        return redirect(url_for('admin.dsr'))
    u = db.one('SELECT * FROM users WHERE id = %s', r['user_id']) if r['user_id'] else None
    return render_template('admin/dsr_item.html', r=r, u=u)

@bp.route('/audit')
def audit_log():
    q = request.args.get('q', '')
    rows = db.all("SELECT a.*, u.email FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id WHERE (%s = '' OR a.action ILIKE %s OR a.entity_id = %s) ORDER BY a.id DESC LIMIT 500", q, f'%{q}%', q)
    return render_template('admin/audit.html', rows=rows, q=q)

@bp.route('/outbox', methods=['GET', 'POST'])
def outbox():
    if request.method == 'POST':
        if request.form.get('action') == 'retry': db.run("UPDATE outbox SET status = 'pending', attempts = 0, next_attempt_at = now() WHERE status = 'failed'")
        elif request.form.get('action') == 'run': flash(f'Delivered {crm.deliver_pending()} events.', 'success')
        return redirect(url_for('admin.outbox'))
    rows = db.all('SELECT * FROM outbox ORDER BY id DESC LIMIT 200')
    return render_template('admin/outbox.html', rows=rows)

@bp.route('/contact')
def contact():
    return render_template('admin/simple_table.html', title='Contact messages', rows=db.all('SELECT * FROM contact_messages ORDER BY id DESC LIMIT 300'),
                           cols=['created_at', 'name', 'email', 'phone', 'topic', 'message'])

@bp.route('/tickets')
def tickets():
    rows = db.all('SELECT t.*, u.email, o.name AS org_name FROM support_tickets t LEFT JOIN users u ON u.id = t.user_id LEFT JOIN organisations o ON o.id = t.org_id ORDER BY t.status, t.updated_at DESC LIMIT 300')
    return render_template('admin/tickets.html', rows=rows)

@bp.route('/tickets/<int:tid>', methods=['GET', 'POST'])
def ticket(tid):
    t = db.one('SELECT * FROM support_tickets WHERE id = %s', tid) or abort(404)
    if request.method == 'POST':
        if request.form.get('body'):
            db.insert('ticket_messages', dict(ticket_id=tid, user_id=g.user['id'], body=request.form['body'][:5000], staff=True), returning=None)
            notify.notify(t['user_id'], f"Reply on support ticket #{tid}", request.form['body'][:200], f'/dashboard/support/{tid}', mail=True)
        db.run('UPDATE support_tickets SET status = %s, updated_at = now() WHERE id = %s', request.form.get('status', 'pending'), tid)
        return redirect(url_for('admin.ticket', tid=tid))
    msgs = db.all('SELECT m.*, u.name FROM ticket_messages m LEFT JOIN users u ON u.id = m.user_id WHERE ticket_id = %s ORDER BY m.id', tid)
    return render_template('admin/ticket.html', t=t, msgs=msgs)

@bp.route('/podcast-questions')
def podcast_questions():
    return redirect(url_for('admin.moderation') + '#questions')


from . import admin_desks  # noqa: E402,F401  (registers the team desks on this blueprint)
