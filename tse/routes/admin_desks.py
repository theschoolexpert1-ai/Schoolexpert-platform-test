"""Admin team desks — one workspace per team, gated by staff role.

  Command Centre ............... everyone      (KPIs, revenue by stream, plan mix, funnel, renewals)
  Verification Desk ............ support, verifier
  Subscriptions & Billing Desk . finance, sales
  Payouts Desk ................. finance       (marketplace seller payouts, referral commissions)
  Leads & CRM Desk ............. sales, support
  Parent Services Desk ......... support, pa_agent (Ask The School Expert, Personal Assistance)
  Community & Moderation Desk .. moderator, support
  Content Studio ............... marketing, moderator
  Events & Sponsorship Desk .... sales, marketing
  Teachers Hub Desk ............ moderator, support, marketing (courses, tutorials, mentor approvals, Hub metrics)
  Growth & SEO Desk ............ marketing, sales (attribution, UTM builder, banner approvals, AI School Match insights)
  Site Integration Desk ........ marketing     (legacy schoolexpert.in pages & 301 redirects)
  Privacy & Compliance Desk .... admin (DPO)
  Platform Health .............. admin
"""
import csv, io, datetime, urllib.parse
from flask import render_template, request, redirect, url_for, flash, g, abort, Response
from ..db import db
from ..lib import notify, entitlements as E
from ..lib.security import audit
from .admin import bp

DESKS = [  # key, name, icon, roles (admin always), landing endpoint
    ('command', 'Command Centre', '🧭', '*', 'admin.index'),
    ('verification', 'Verification Desk', '✅', ('support', 'verifier'), 'admin.registrations'),
    ('billing', 'Subscriptions & Billing Desk', '💳', ('finance', 'sales'), 'admin.subscriptions'),
    ('payouts', 'Payouts Desk', '🏦', ('finance',), 'admin.payouts'),
    ('leads', 'Leads & CRM Desk', '📇', ('sales', 'support'), 'admin.leads'),
    ('parent', 'Parent Services Desk', '👪', ('support', 'pa_agent'), 'admin.expert_requests'),
    ('community', 'Community & Moderation Desk', '🛡️', ('moderator', 'support'), 'admin.moderation'),
    ('content', 'Content Studio', '✍️', ('marketing', 'moderator'), 'admin.cms_index'),
    ('events', 'Events & Sponsorship Desk', '🎟️', ('sales', 'marketing'), 'admin.events_desk'),
    ('teachers', 'Teachers Hub Desk', '🧑‍🏫', ('moderator', 'support', 'marketing'), 'admin.teachers_hub'),
    ('growth', 'Growth & SEO Desk', '📈', ('marketing', 'sales'), 'admin.growth'),
    ('site', 'Site Integration Desk', '🔗', ('marketing',), 'admin.site'),
    ('privacy', 'Privacy & Compliance Desk', '🔐', (), 'admin.dsr'),
    ('health', 'Platform Health', '🩺', (), 'admin.health'),
]
STAFF_ROLES = ['support', 'verifier', 'moderator', 'sales', 'finance', 'marketing', 'pa_agent']
ENDPOINT_DESK = {
    'admin.registrations': 'verification', 'admin.registration': 'verification', 'admin.listings': 'verification', 'admin.organisations': 'verification',
    'admin.forms_admin': 'verification', 'admin.form_json': 'verification', 'admin.form_preview': 'verification', 'admin.users': 'privacy',
    'admin.subscriptions': 'billing', 'admin.orders': 'billing', 'admin.order': 'billing', 'admin.revenue': 'billing',
    'admin.payouts': 'payouts',
    'admin.leads': 'leads', 'admin.tickets': 'leads', 'admin.ticket': 'leads', 'admin.contact': 'leads', 'admin.outbox': 'health',
    'admin.expert_requests': 'parent', 'admin.expert_request': 'parent', 'admin.pa_list': 'parent', 'admin.pa': 'parent',
    'admin.moderation': 'community',
    'admin.cms_index': 'content', 'admin.cms_list': 'content', 'admin.cms_edit': 'content', 'admin.album_photos': 'content', 'admin.podcast_questions': 'content',
    'admin.events_desk': 'events', 'admin.event': 'events',
    'admin.teachers_hub': 'teachers', 'admin.teachers_hub_mentor': 'teachers',
    'admin.growth': 'growth', 'admin.ads': 'growth', 'admin.utm': 'growth',
    'admin.site': 'site', 'admin.redirects_csv': 'site',
    'admin.dsr': 'privacy', 'admin.dsr_item': 'privacy', 'admin.audit_log': 'privacy', 'admin.security_desk': 'privacy', 'admin.security_unlock': 'privacy',
    'admin.health': 'health',
}
CMS_DESK = {'breach_incidents': 'privacy', 'plans': 'billing', 'referral_codes': 'payouts', 'ad_placements': 'growth', 'pages': 'site',
            'events': 'events', 'sponsorships': 'events', 'courses': 'teachers', 'course_lessons': 'teachers', 'tutorials': 'teachers'}

def desk_allowed(key, user=None):
    u = user or g.user
    if not u: return False
    if u['account_type'] == 'admin': return True
    if u['account_type'] != 'staff': return False
    roles = next((d[3] for d in DESKS if d[0] == key), ())
    return roles == '*' or u['staff_role'] in roles

@bp.before_request
def _desk_guard():
    ep = request.endpoint or ''
    key = ENDPOINT_DESK.get(ep)
    if ep.startswith('admin.cms_') and request.view_args and request.view_args.get('table') in CMS_DESK:
        key = CMS_DESK[request.view_args['table']]
    if key and not desk_allowed(key): abort(403)
    g.desk = key or ('command' if ep == 'admin.index' else None)

@bp.app_context_processor
def _desk_ctx():
    if not getattr(g, 'user', None) or g.user['account_type'] not in ('admin', 'staff'): return {}
    return dict(desks=[d for d in DESKS if desk_allowed(d[0])], current_desk=getattr(g, 'desk', None))

# ---------------- Subscriptions & Billing Desk ----------------
@bp.route('/subscriptions', methods=['GET', 'POST'])
def subscriptions():
    if request.method == 'POST':
        f = request.form; act = f.get('action'); sid = f.get('id', type=int)
        s = db.one('SELECT * FROM subscriptions WHERE id = %s', sid) if sid else None
        if act == 'extend' and s:
            days = max(1, min(365, f.get('days', 30, type=int)))
            db.run('UPDATE subscriptions SET ends_at = COALESCE(ends_at, current_date) + %s::int WHERE id = %s', days, sid)
        elif act == 'cancel' and s and g.user['account_type'] == 'admin':
            db.run("UPDATE subscriptions SET status = 'cancelled' WHERE id = %s", sid)
        elif act == 'comp':   # complimentary plan, e.g. pilot schools / partnerships
            org = db.one('SELECT * FROM organisations WHERE id = %s', f.get('org_id', type=int)) or abort(404)
            plan = db.one('SELECT * FROM plans WHERE code = %s AND active', f.get('plan')) or abort(400)
            db.run("UPDATE subscriptions s SET status = 'upgraded' FROM plans p WHERE p.code = s.plan_code AND s.org_id = %s AND s.status = 'active' AND p.family = %s",
                   org['id'], plan['family'])
            db.insert('subscriptions', dict(org_id=org['id'], plan_code=plan['code'], ends_at=datetime.date.today() + datetime.timedelta(days=f.get('days', 365, type=int)),
                      amount_paise=0), returning=None)
        else: abort(400)
        if s or act == 'comp':
            oid = s['org_id'] if s else f.get('org_id', type=int)
            if oid:
                from ..lib import listings as L; L.refresh_org(oid)
        audit(f'admin.subscription.{act}', 'subscription', sid, dict(f)); flash('Saved.', 'success')
        return redirect(request.referrer or url_for('admin.subscriptions'))
    a = request.args
    fam = a.get('family', ''); lvl = a.get('level', '')
    rows = db.all("""SELECT s.*, p.name AS plan_name, p.family, p.level, p.price_paise, o.name AS org_name, o.founding_partner,
                            (s.ends_at - current_date) AS days_left FROM subscriptions s JOIN plans p ON p.code = s.plan_code
                     LEFT JOIN organisations o ON o.id = s.org_id
                     WHERE s.status = %s AND (%s = '' OR p.family = %s) AND (%s = '' OR p.level::text = %s)
                     ORDER BY s.ends_at NULLS LAST LIMIT 500""", a.get('status', 'active'), fam, fam, lvl, lvl)
    mix = db.all("""SELECT p.family, p.level, p.name, count(*) n, sum(COALESCE(s.amount_paise, p.price_paise)) amt FROM subscriptions s JOIN plans p ON p.code = s.plan_code
                    WHERE s.status = 'active' AND (s.ends_at IS NULL OR s.ends_at >= current_date) AND p.family IN ('school','vendor') GROUP BY 1,2,3 ORDER BY 1,2""")
    arr = db.val("""SELECT COALESCE(sum(p.price_paise),0) FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.status = 'active'
                    AND (s.ends_at IS NULL OR s.ends_at >= current_date) AND p.interval = 'annual'""")
    upgrades = db.all("""SELECT s.created_at, o.name AS org_name, s.upgraded_from, s.plan_code, s.amount_paise FROM subscriptions s JOIN organisations o ON o.id = s.org_id
                         WHERE s.upgraded_from IS NOT NULL ORDER BY s.id DESC LIMIT 20""")
    unpaid = db.all("""SELECT o.id, o.name, o.category, o.created_at, (SELECT max(progress) FROM registrations r WHERE r.org_id = o.id) progress FROM organisations o
                       WHERE NOT EXISTS (SELECT 1 FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.org_id = o.id AND s.status = 'active' AND p.family IN ('school','vendor'))
                       ORDER BY o.created_at DESC LIMIT 50""")
    plans = db.all("SELECT code, name FROM plans WHERE active AND family IN ('school','vendor','addon') ORDER BY family, sort")
    return render_template('admin/subscriptions.html', rows=rows, mix=mix, arr=arr, upgrades=upgrades, unpaid=unpaid, plans=plans, a=a)

# ---------------- Payouts Desk ----------------
@bp.route('/payouts', methods=['GET', 'POST'])
def payouts():
    if request.method == 'POST':
        f = request.form; act = f.get('action')
        if act == 'pay_seller':
            org = f.get('org_id', type=int); ref = f.get('ref', '')[:80] or None
            n = db.run("UPDATE seller_ledger SET status = 'paid', paid_at = now(), payout_ref = %s WHERE seller_org_id = %s AND status IN ('pending','payable') AND created_at < now() - interval '7 days'", ref, org)
            notify.notify_org(org, 'Marketplace payout sent', f'Your marketplace payout has been processed (ref {ref or "—"}).', '/dashboard/sales')
        elif act in ('approve_ref', 'pay_ref', 'reject_ref'):
            st = {'approve_ref': 'approved', 'pay_ref': 'paid', 'reject_ref': 'rejected'}[act]
            db.run('UPDATE referrals SET status = %s WHERE id = %s', st, f.get('id', type=int))
        audit(f'admin.payout.{act}', None, None, dict(f)); flash('Saved.', 'success')
        return redirect(url_for('admin.payouts'))
    sellers = db.all("""SELECT o.id, o.name, count(*) n, sum(l.gross_paise) gross, sum(l.commission_paise) comm, sum(l.net_paise) net,
                        sum(l.net_paise) FILTER (WHERE l.created_at < now() - interval '7 days') payable FROM seller_ledger l JOIN organisations o ON o.id = l.seller_org_id
                        WHERE l.status IN ('pending','payable') GROUP BY o.id, o.name ORDER BY net DESC""")
    paid = db.all("""SELECT o.name, l.payout_ref, max(l.paid_at) paid_at, sum(l.net_paise) net FROM seller_ledger l JOIN organisations o ON o.id = l.seller_org_id
                     WHERE l.status = 'paid' GROUP BY o.name, l.payout_ref ORDER BY max(l.paid_at) DESC LIMIT 30""")
    refs = db.all("""SELECT r.*, rc.kind, u.name AS owner_name, o.kind AS order_kind FROM referrals r JOIN referral_codes rc ON rc.code = r.code
                     LEFT JOIN users u ON u.id = rc.user_id LEFT JOIN orders o ON o.id = r.order_id ORDER BY (r.status = 'pending') DESC, r.id DESC LIMIT 100""")
    commission = db.val('SELECT COALESCE(sum(commission_paise),0) FROM seller_ledger')
    return render_template('admin/payouts.html', sellers=sellers, paid=paid, refs=refs, commission=commission)

# ---------------- Events & Sponsorship Desk ----------------
@bp.route('/events-desk')
def events_desk():
    events = db.all("""SELECT e.*, (SELECT count(*) FROM event_registrations r WHERE r.event_id = e.id) regs,
                       (SELECT COALESCE(sum(o.total_paise),0) FROM event_registrations r JOIN orders o ON o.id = r.order_id WHERE r.event_id = e.id AND o.status = 'paid') revenue
                       FROM events e ORDER BY e.starts_at DESC LIMIT 100""")
    sponsors = db.all('SELECT * FROM sponsorships ORDER BY id DESC LIMIT 100')
    return render_template('admin/events_desk.html', events=events, sponsors=sponsors)

# ---------------- Growth & SEO Desk ----------------
@bp.route('/growth')
def growth():
    days = request.args.get('days', 30, type=int)
    q = lambda t, extra='': db.all(f"""SELECT COALESCE(attribution->>'utm_source','(unknown)') src, COALESCE(attribution->>'utm_medium','') med,
                                       COALESCE(attribution->>'utm_campaign','') camp, count(*) n {extra} FROM {t}
                                       WHERE created_at > now() - make_interval(days => %s) {"AND status IN ('paid','fulfilled','shipped','delivered')" if t == 'orders' else ''}
                                       GROUP BY 1,2,3 ORDER BY n DESC LIMIT 40""", days)
    signups = q('users'); orgs = q('organisations'); orders = q('orders', ', sum(total_paise) amt')
    landing = db.all("""SELECT attribution->>'landing' page, count(*) n FROM users WHERE attribution IS NOT NULL AND created_at > now() - make_interval(days => %s)
                        GROUP BY 1 ORDER BY n DESC LIMIT 20""", days)
    funnel = dict(
        visitors_matched=db.val("SELECT count(*) FROM school_match_sessions WHERE created_at > now() - make_interval(days => %s)", days),
        signups=db.val("SELECT count(*) FROM users WHERE created_at > now() - make_interval(days => %s)", days),
        regs_started=db.val("SELECT count(*) FROM registrations WHERE created_at > now() - make_interval(days => %s)", days),
        regs_submitted=db.val("SELECT count(*) FROM registrations WHERE submitted_at > now() - make_interval(days => %s)", days),
        paid_orgs=db.val("""SELECT count(DISTINCT s.org_id) FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE p.family IN ('school','vendor')
                            AND s.created_at > now() - make_interval(days => %s)""", days),
        unlocks=db.val("SELECT count(*) FROM unlocks WHERE created_at > now() - make_interval(days => %s)", days))
    match = dict(runs=funnel['visitors_matched'],
                 ai=db.val("SELECT count(*) FROM school_match_sessions WHERE ai_used AND created_at > now() - make_interval(days => %s)", days),
                 cities=db.all("""SELECT prefs->>'city' city, count(*) n FROM school_match_sessions WHERE created_at > now() - make_interval(days => %s)
                                  GROUP BY 1 ORDER BY n DESC LIMIT 10""", days),
                 grades=db.all("""SELECT prefs->>'grade' grade, count(*) n FROM school_match_sessions WHERE created_at > now() - make_interval(days => %s) AND prefs->>'grade' <> ''
                                  GROUP BY 1 ORDER BY n DESC LIMIT 10""", days))
    ads = db.all("""SELECT a.*, o.name AS org_name FROM ad_placements a LEFT JOIN organisations o ON o.id = a.org_id ORDER BY (a.status = 'pending') DESC, a.id DESC LIMIT 60""")
    return render_template('admin/growth.html', days=days, signups=signups, orgs=orgs, orders=orders, landing=landing, funnel=funnel, match=match, ads=ads)

@bp.route('/growth/ads', methods=['POST'])
def ads():
    f = request.form; ad = db.one('SELECT * FROM ad_placements WHERE id = %s', f.get('id', type=int)) or abort(404)
    act = f.get('action')
    if act == 'approve':
        db.run("UPDATE ad_placements SET status = 'approved', active = true WHERE id = %s", ad['id'])
        if ad['org_id']: notify.notify_org(ad['org_id'], 'Sponsored banner approved', f"“{ad['title']}” is now live.", '/dashboard/promote')
    elif act == 'reject':
        db.run("UPDATE ad_placements SET status = 'rejected', active = false WHERE id = %s", ad['id'])
        if ad['org_id']: notify.notify_org(ad['org_id'], 'Sponsored banner needs changes', (f.get('reason') or 'Please review our advertising guidelines.')[:300], '/dashboard/promote')
    elif act == 'pause': db.run('UPDATE ad_placements SET active = NOT active WHERE id = %s', ad['id'])
    else: abort(400)
    audit(f'admin.ad.{act}', 'ad_placement', ad['id']); return redirect(url_for('admin.growth') + '#ads')

@bp.route('/growth/utm')
def utm():
    """UTM builder for SEM / social campaigns aimed at the right audience."""
    from flask import current_app
    base = current_app.config['SITE_URL']
    targets = [('/list-your-school', 'Schools — list your school'), ('/become-a-vendor', 'Vendors — become a partner'), ('/for-teachers', 'Teachers — join & find jobs'),
               ('/school-match', 'Parents — AI School Match'), ('/pricing', 'Pricing'), ('/founding-partners', 'Founding Partner Programme'), ('/events', 'Events')]
    a = request.args; url = None
    if a.get('path'):
        params = {k: a.get(k, '').strip() for k in ('utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content') if a.get(k, '').strip()}
        url = base + a['path'] + ('?' + urllib.parse.urlencode(params) if params else '')
    return render_template('admin/utm.html', targets=targets, url=url, a=a)

# ---------------- Site Integration Desk ----------------
@bp.route('/site', methods=['GET', 'POST'])
def site():
    if request.method == 'POST':
        f = request.form; act = f.get('action')
        if act == 'add':
            src = '/' + f.get('from_path', '').strip().lstrip('/'); dst = f.get('to_url', '').strip()
            if not dst or src == '/': flash('Both paths are required.', 'error')
            else:
                db.run("""INSERT INTO redirects (from_path, to_url, code) VALUES (%s,%s,%s) ON CONFLICT (from_path) DO UPDATE SET to_url = EXCLUDED.to_url, code = EXCLUDED.code""",
                       src.rstrip('/') or '/', dst, 302 if f.get('code') == '302' else 301)
        elif act == 'delete': db.run('DELETE FROM redirects WHERE from_path = %s', f.get('from_path'))
        elif act == 'import':
            up = request.files.get('csv')
            if up:
                n = 0
                for row in csv.reader(io.StringIO(up.read().decode('utf-8-sig'))):
                    if len(row) >= 2 and row[0].strip().startswith('/') and not row[0].lower().startswith('/from'):
                        db.run("""INSERT INTO redirects (from_path, to_url, code) VALUES (%s,%s,%s) ON CONFLICT (from_path) DO UPDATE SET to_url = EXCLUDED.to_url""",
                               row[0].strip().rstrip('/') or '/', row[1].strip(), int(row[2]) if len(row) > 2 and row[2].strip() in ('301', '302') else 301); n += 1
                flash(f'{n} redirects imported.', 'success')
        elif act == 'page_path':
            db.run('UPDATE pages SET path = %s, show_in_footer = %s WHERE slug = %s', (f.get('path') or '').strip() or None, bool(f.get('footer')), f.get('slug'))
        audit(f'admin.site.{act}', 'redirect', None, dict(f)); return redirect(url_for('admin.site'))
    redirects = db.all('SELECT * FROM redirects ORDER BY hits DESC, from_path LIMIT 500')
    pages = db.all('SELECT slug, title, path, show_in_footer, updated_at FROM pages ORDER BY slug')
    return render_template('admin/site.html', redirects=redirects, pages=pages)

@bp.route('/site/redirects.csv')
def redirects_csv():
    out = io.StringIO(); w = csv.writer(out); w.writerow(['from_path', 'to_url', 'code', 'hits'])
    for r in db.all('SELECT * FROM redirects ORDER BY from_path'): w.writerow([r['from_path'], r['to_url'], r['code'], r['hits']])
    return Response(out.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=redirects.csv'})

# ---------------- Platform Health ----------------
@bp.route('/health')
def health():
    tables = db.all("""SELECT relname AS t, n_live_tup AS n FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 25""")
    size = db.val('SELECT pg_size_pretty(pg_database_size(current_database()))')
    outbox = db.all('SELECT status, count(*) n FROM outbox GROUP BY status')
    sessions = db.val('SELECT count(*) FROM sessions')
    mig = db.all('SELECT * FROM schema_migrations ORDER BY 1') if db.val("SELECT to_regclass('schema_migrations') IS NOT NULL") else []
    slow = db.all("""SELECT action, count(*) n FROM audit_log WHERE created_at > now() - interval '24 hours' GROUP BY action ORDER BY n DESC LIMIT 15""")
    return render_template('admin/health.html', tables=tables, size=size, outbox=outbox, sessions=sessions, mig=mig, slow=slow)

# ---------------- Security monitoring (Privacy & Compliance Desk) ----------------
@bp.route('/security')
def security_desk():
    events = db.all("""SELECT a.*, u.email FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id
                       WHERE a.action LIKE 'security.%%' OR a.action IN ('auth.login_failed', 'auth.idle_timeout', 'private_file.viewed', 'admin.registration.viewed_private')
                       ORDER BY a.id DESC LIMIT 200""")
    failed_24h = db.val("SELECT count(*) FROM audit_log WHERE action = 'auth.login_failed' AND created_at > now() - interval '24 hours'")
    locked = db.all('SELECT id, email, locked_until FROM users WHERE locked_until > now() ORDER BY locked_until DESC')
    staff = db.all("SELECT id, name, email, account_type, staff_role, mfa_enabled, last_login_at, last_login_ip FROM users WHERE account_type IN ('admin','staff') ORDER BY mfa_enabled, name")
    top_ips = db.all("""SELECT ip, count(*) n FROM audit_log WHERE action = 'auth.login_failed' AND created_at > now() - interval '24 hours' AND ip IS NOT NULL
                        GROUP BY ip ORDER BY n DESC LIMIT 10""")
    return render_template('admin/security.html', events=events, failed_24h=failed_24h, locked=locked, staff=staff, top_ips=top_ips)

@bp.route('/security/unlock', methods=['POST'])
def security_unlock():
    uid = request.form.get('id', type=int)
    db.run('UPDATE users SET locked_until = NULL, failed_logins = 0 WHERE id = %s', uid)
    audit('security.account_unlocked', 'user', uid); flash('Account unlocked.', 'success')
    return redirect(url_for('admin.security_desk'))


# ---------------- Teachers Hub Desk ----------------
@bp.route('/teachers-hub')
def teachers_hub():
    v = db.val
    stats = dict(members=v('SELECT count(*) FROM hub_members'), visible=v('SELECT count(*) FROM hub_members WHERE directory_visible'),
                 mentors=v("SELECT count(*) FROM hub_members WHERE mentor_status = 'approved'"),
                 enrolments=v('SELECT count(*) FROM course_enrolments'), certificates=v('SELECT count(*) FROM course_enrolments WHERE completed_at IS NOT NULL'),
                 cpd_hours=v('SELECT COALESCE(sum(c.cpd_hours),0) FROM course_enrolments e JOIN courses c ON c.id = e.course_id WHERE e.completed_at IS NOT NULL'),
                 connections=v("SELECT count(*) FROM connections WHERE status = 'accepted'"), messages_7d=v("SELECT count(*) FROM direct_messages WHERE created_at > now() - interval '7 days'"),
                 mentorships=v("SELECT count(*) FROM mentorships WHERE status = 'active'"), plans=v('SELECT count(*) FROM lesson_plans'))
    pending = db.all("""SELECT m.*, u.name, u.email, u.city, tp.slug AS profile_slug FROM hub_members m JOIN users u ON u.id = m.user_id
                        LEFT JOIN teacher_profiles tp ON tp.user_id = m.user_id WHERE m.mentor_status = 'pending' ORDER BY m.updated_at""")
    courses = db.all("""SELECT c.*, (SELECT count(*) FROM course_lessons l WHERE l.course_id = c.id) lessons,
                        (SELECT count(*) FROM course_enrolments e WHERE e.course_id = c.id) learners,
                        (SELECT count(*) FROM course_enrolments e WHERE e.course_id = c.id AND e.completed_at IS NOT NULL) completed FROM courses c ORDER BY c.sort, c.id""")
    return render_template('admin/teachers_hub.html', stats=stats, pending=pending, courses=courses)

@bp.route('/teachers-hub/mentor/<int:uid>', methods=['POST'])
def teachers_hub_mentor(uid):
    decision = 'approved' if request.form.get('decision') == 'approve' else 'rejected'
    n = db.run("UPDATE hub_members SET mentor_status = %s, updated_at = now() WHERE user_id = %s AND mentor_status = 'pending'", decision, uid)
    if n:
        audit('hub.mentor_' + decision, 'user', uid)
        notify.notify(uid, 'Mentor application ' + decision, 'You now appear in the Teachers Hub mentor list. Thank you for supporting fellow teachers!' if decision == 'approved'
                      else 'Thank you for offering to mentor. We could not approve it right now; you can apply again from your Hub profile.', '/teachers/mentors', mail=True)
    flash(f'Mentor {decision}.', 'success')
    return redirect(url_for('admin.teachers_hub'))
