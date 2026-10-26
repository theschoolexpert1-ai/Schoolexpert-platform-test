"""Privacy Centre — DPDP Act 2023 data-principal rights (s.11–14) and consent management."""
import json, datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, Response, make_response, session
from ..db import db
from ..lib import consent, notify
from ..lib.auth import login_required
from ..lib.security import decrypt_json, limited, audit

bp = Blueprint('privacy', __name__)
DUE_DAYS = 90   # DPDP Rules 2025: grievances answered within a period not exceeding 90 days (we target 30)

@bp.route('/privacy-centre')
def centre():
    state = consent.current(g.user['id']) if g.user else {}
    reqs = db.all('SELECT * FROM data_requests WHERE user_id = %s ORDER BY id DESC', g.user['id']) if g.user else []
    notices = {n['purpose']: n for n in db.all("SELECT DISTINCT ON (purpose) * FROM consent_notices WHERE lang = 'en' AND active ORDER BY purpose, version DESC")}
    return render_template('privacy/centre.html', state=state, reqs=reqs, purposes=consent.PURPOSES, notices=notices)

@bp.route('/privacy-centre/consent', methods=['POST'])
@login_required
def toggle():
    p = request.form.get('purpose')
    if p not in consent.PURPOSES: abort(400)
    if request.form.get('grant') == '1': consent.record(p, True, user_id=g.user['id'], method='dashboard')
    else:
        if p == 'account':
            flash('To withdraw consent for your account itself, request account deletion below.', 'info'); return redirect(url_for('privacy.centre'))
        consent.withdraw(g.user['id'], p)
        if p == 'marketing': db.run("UPDATE newsletter_subscriptions SET status = 'unsubscribed' WHERE user_id = %s", g.user['id'])
        if p == 'hub_directory': db.run('UPDATE hub_members SET directory_visible = false WHERE user_id = %s', g.user['id'])
        if p == 'profile_listing':
            db.run('UPDATE listings SET is_published = false WHERE user_id = %s OR org_id IN (SELECT org_id FROM org_members WHERE user_id = %s AND role = %s)', g.user['id'], g.user['id'], 'owner')
            db.run("UPDATE teacher_profiles SET visibility = 'hidden' WHERE user_id = %s", g.user['id'])
            db.run('UPDATE hub_members SET directory_visible = false, open_to_mentor = false WHERE user_id = %s', g.user['id'])
    audit('consent.changed', 'user', g.user['id'], {'purpose': p, 'grant': request.form.get('grant')})
    flash('Your choice has been saved.', 'success')
    return redirect(url_for('privacy.centre'))

@bp.route('/privacy-centre/export')
@login_required
@limited(5, 3600, 'export')
def export():
    """Right to access (s.11): summary of personal data processed + with whom it was shared."""
    uid = g.user['id']
    u = db.one('SELECT id, email, phone, name, account_type, city, state, pincode, created_at, last_login_at, nominee FROM users WHERE id = %s', uid)
    regs = []
    for r in db.all('SELECT * FROM registrations WHERE user_id = %s', uid):
        a = dict(r['answers']); a.update(decrypt_json(r['private_enc']))
        regs.append({'form': r['form_slug'], 'status': r['status'], 'answers': a, 'files': r['files'], 'created_at': r['created_at']})
    data = {
        'generated_at': datetime.datetime.utcnow().isoformat() + 'Z', 'data_fiduciary': 'Poornaphala Media and Infotech Services LLP (The School Expert™)',
        'account': u, 'registrations': regs,
        'consents': db.all('SELECT purpose, granted, notice_version, method, context, created_at, withdrawn_at FROM consents WHERE user_id = %s ORDER BY id', uid),
        'shared_with': db.all("""SELECT 'enquiry' AS type, l.name AS organisation, ld.created_at FROM leads ld JOIN listings l ON l.id = ld.listing_id WHERE ld.user_id = %s
                                 UNION ALL SELECT 'job application', o.name, a.created_at FROM job_applications a JOIN jobs j ON j.id = a.job_id JOIN organisations o ON o.id = j.org_id WHERE a.teacher_id = %s""", uid, uid),
        'orders': db.all('SELECT invoice_no, kind, description, total_paise, status, created_at FROM orders WHERE user_id = %s', uid),
        'teacher_profile': db.one('SELECT * FROM teacher_profiles WHERE user_id = %s', uid),
        'job_applications': db.all('SELECT job_id, status, created_at FROM job_applications WHERE teacher_id = %s', uid),
        'expert_requests': db.all('SELECT topic, message, status, created_at FROM expert_requests WHERE user_id = %s', uid),
        'personal_assistance': db.all('SELECT school_name, services, status, created_at FROM pa_requests WHERE user_id = %s', uid),
        'posts': db.all('SELECT community, title, body, created_at FROM posts WHERE user_id = %s', uid),
        'comments': db.all('SELECT post_id, body, created_at FROM comments WHERE user_id = %s', uid),
        'reviews': db.all('SELECT listing_id, rating, body, created_at FROM reviews WHERE user_id = %s', uid),
        'addresses': db.all('SELECT * FROM addresses WHERE user_id = %s', uid),
        'data_requests': db.all('SELECT kind, status, created_at, closed_at FROM data_requests WHERE user_id = %s', uid),
        'teachers_hub': _hub_export(uid),
    }
    audit('dsr.export', 'user', uid)
    resp = Response(json.dumps(data, default=str, indent=1, ensure_ascii=False), mimetype='application/json')
    resp.headers['Content-Disposition'] = 'attachment; filename="my-data-schoolexpert.json"'
    return resp

def _hub_export(uid):
    """Teachers Hub data: profile, learning record, certificates, plans, network, mentorships and messages (decrypted for you)."""
    from ..lib import hub as H
    msgs = db.all('''SELECT d.sender_id, d.recipient_id, s.name AS sender, r.name AS recipient, d.body_enc, d.created_at, d.read_at FROM direct_messages d
                     JOIN users s ON s.id = d.sender_id JOIN users r ON r.id = d.recipient_id WHERE d.sender_id = %s OR d.recipient_id = %s ORDER BY d.id''', uid, uid)
    for m in msgs: m['body'] = H.unseal(m.pop('body_enc'))
    return {
        'hub_profile': db.one('SELECT * FROM hub_members WHERE user_id = %s', uid),
        'courses': db.all('''SELECT c.title, e.enrolled_at, e.completed_at, e.certificate_code, c.cpd_hours FROM course_enrolments e JOIN courses c ON c.id = e.course_id
                             WHERE e.user_id = %s ORDER BY e.enrolled_at''', uid),
        'lessons_completed': db.all('''SELECT c.title AS course, l.title AS lesson, p.done_at FROM lesson_progress p JOIN course_lessons l ON l.id = p.lesson_id
                                       JOIN courses c ON c.id = l.course_id WHERE p.user_id = %s ORDER BY p.done_at''', uid),
        'saved_tutorials': db.all('SELECT t.title, s.saved, s.viewed_at FROM tutorial_saves s JOIN tutorials t ON t.id = s.tutorial_id WHERE s.user_id = %s', uid),
        'lesson_plans': db.all('SELECT * FROM lesson_plans WHERE user_id = %s ORDER BY id', uid),
        'connections': db.all('''SELECT u.name AS with_teacher, c.status, CASE WHEN c.requester_id = %s THEN 'sent' ELSE 'received' END AS direction, c.created_at
                                 FROM connections c JOIN users u ON u.id = CASE WHEN c.requester_id = %s THEN c.addressee_id ELSE c.requester_id END
                                 WHERE c.requester_id = %s OR c.addressee_id = %s''', uid, uid, uid, uid),
        'mentorships': db.all('''SELECT a.name AS mentee, b.name AS mentor, m.topic, m.message, m.status, m.created_at FROM mentorships m
                                 JOIN users a ON a.id = m.mentee_id JOIN users b ON b.id = m.mentor_id WHERE m.mentee_id = %s OR m.mentor_id = %s''', uid, uid),
        'messages': msgs,
    }

@bp.route('/privacy-centre/request', methods=['POST'])
@limited(6, 3600, 'dsr')
def request_right():
    kind = request.form.get('kind')
    if kind not in ('access', 'correction', 'erasure', 'withdraw_consent', 'nomination', 'grievance'): abort(400)
    email = g.user['email'] if g.user else request.form.get('email', '').strip().lower()
    if not email or '@' not in email: flash('Please give your email address.', 'error'); return redirect(url_for('privacy.centre'))
    details = request.form.get('details', '')[:4000]
    if kind == 'nomination' and g.user:
        nominee = {'name': request.form.get('nominee_name', '')[:120], 'relationship': request.form.get('nominee_relationship', '')[:60],
                   'email': request.form.get('nominee_email', '')[:200], 'phone': request.form.get('nominee_phone', '')[:20]}
        db.run('UPDATE users SET nominee = %s WHERE id = %s', db.Json(nominee), g.user['id'])
        details = f"Nominee registered: {nominee['name']} ({nominee['relationship']})"
    rid = db.insert('data_requests', dict(user_id=g.user['id'] if g.user else None, email=email, kind=kind, details=details,
                    due_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=DUE_DAYS),
                    status='completed' if kind == 'nomination' else 'open'))
    if kind == 'erasure' and g.user:
        db.run("UPDATE users SET status = 'pending_deletion', deleted_at = now() WHERE id = %s", g.user['id'])
        flash('Your account will be deleted in 30 days. Log in before then and cancel from here if you change your mind. '
              'Invoices are kept as required by tax law.', 'warning')
    else:
        flash(f'Request #{rid} received. We respond as soon as possible and in any case within {DUE_DAYS} days.', 'success')
    notify.notify_staff(f'Data request: {kind}', f'{email}: {details[:120]}', f'/admin/dsr/{rid}')
    notify.email(email, f'We received your {kind.replace("_", " ")} request (#{rid})', f'Thank you. Your request #{rid} has been logged. Our Grievance Officer will respond within {DUE_DAYS} days.')
    audit('dsr.created', 'data_request', rid, {'kind': kind})
    return redirect(url_for('privacy.centre'))

@bp.route('/privacy-centre/cancel-deletion', methods=['POST'])
@login_required
def cancel_deletion():
    db.run("UPDATE users SET status = 'active', deleted_at = NULL WHERE id = %s AND status = 'pending_deletion'", g.user['id'])
    db.run("UPDATE data_requests SET status = 'rejected', response = 'Cancelled by user', closed_at = now() WHERE user_id = %s AND kind = 'erasure' AND status = 'open'", g.user['id'])
    flash('Account deletion cancelled.', 'success'); return redirect(url_for('privacy.centre'))

@bp.route('/cookie-consent', methods=['POST'])
def cookie_consent():
    choice = 'all' if request.form.get('choice') == 'all' else 'essential'
    consent.record('analytics_cookies', choice == 'all', user_id=g.user['id'] if g.user else None, method='cookie_banner')
    resp = make_response('', 204)
    resp.set_cookie('tse_cookie_consent', choice, max_age=60 * 60 * 24 * 180, samesite='Lax', secure=request.is_secure)
    return resp

@bp.route('/cookie-settings', methods=['GET', 'POST'])
def cookies():
    if request.method == 'POST':
        choice = 'all' if request.form.get('choice') == 'all' else 'essential'
        consent.record('analytics_cookies', choice == 'all', user_id=g.user['id'] if g.user else None, method='cookie_banner')
        resp = make_response(redirect(url_for('privacy.cookies')))
        resp.set_cookie('tse_cookie_consent', choice, max_age=60 * 60 * 24 * 180, samesite='Lax', secure=request.is_secure)
        flash('Cookie preference saved.', 'success'); return resp
    return render_template('privacy/cookies.html')

@bp.route('/private-file')
@login_required
def private_file():
    """Stream a private upload after an authorisation check (owner org member, applicant/hiring school, or staff)."""
    from ..lib import storage
    from flask import send_file
    import re as _re
    ref = request.args.get('ref', '')
    if not _re.fullmatch(r'private:[a-z_-]+/\d{4}/\d{2}/[0-9a-f]{32}\.[a-z0-9]{2,5}', ref): abort(404)   # no wildcards / traversal
    allowed = g.user['account_type'] in ('admin', 'staff')
    if not allowed:
        allowed = bool(db.val("""SELECT 1 FROM registrations r LEFT JOIN org_members m ON m.org_id = r.org_id
                                 WHERE r.files::text LIKE %s AND (r.user_id = %s OR m.user_id = %s)""", f'%{ref}%', g.user['id'], g.user['id']))
    if not allowed:
        allowed = bool(db.val("""SELECT 1 FROM job_applications a JOIN jobs j ON j.id = a.job_id JOIN org_members m ON m.org_id = j.org_id
                                 WHERE a.cv_url = %s AND (m.user_id = %s OR a.teacher_id = %s)""", ref, g.user['id'], g.user['id']))
    if not allowed:
        allowed = bool(db.val('SELECT 1 FROM teacher_profiles WHERE uploaded_cv_url = %s AND user_id = %s', ref, g.user['id']))
    if not allowed: abort(404)
    audit('private_file.viewed', 'file', ref)
    import mimetypes, io
    data = storage.read_private(ref)
    mt = mimetypes.guess_type(ref)[0] or 'application/octet-stream'
    resp = send_file(io.BytesIO(data), mimetype=mt, as_attachment=not mt.startswith(('image/', 'application/pdf')), max_age=0,
                     download_name=ref.rsplit('/', 1)[-1])
    resp.headers['Cache-Control'] = 'private, no-store'
    resp.headers['Content-Security-Policy'] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    return resp
