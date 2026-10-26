import re, time, datetime, hashlib
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, g, current_app, abort
from ..db import db
from ..lib import security as S, consent, notify, mfa as MFA
from ..lib.security import limited, audit

bp = Blueprint('auth', __name__)

TYPES = {
    'parent': ('Parent', 'Search schools and services, Ask The School Expert, Personal Assistance, communities, book club and more.'),
    'teacher': ('Teacher / Educator', 'Create your profile, generate an AI CV, apply to school jobs and join the Teachers Community.'),
    'organisation': ('School / Organisation / Professional', 'Register a school, education business, institute or professional practice and manage your listing.'),
}

def _safe_next(n):
    return n if n and n.startswith('/') and not n.startswith('//') else None

_DUMMY_HASH = S.hash_password('timing-equaliser-not-a-real-password')
LOCK_AFTER, LOCK_MINUTES = 5, 15

def _login(u, mfa=False):
    session.pop('mfa_pending', None)
    session['uid'] = u['id']; S.rotate_session(); session.permanent = True
    now = int(time.time()); session['auth_at'] = now; session['seen'] = now
    if mfa: session['mfa_at'] = now
    first_from_ip = u.get('last_login_ip') and str(u['last_login_ip']) != S.client_ip()
    db.run('UPDATE users SET last_login_at = now(), last_login_ip = %s, failed_logins = 0, locked_until = NULL WHERE id = %s', S.client_ip(), u['id'])
    audit('auth.login', 'user', u['id'], {'mfa': mfa}, actor_id=u['id'])
    if first_from_ip:
        notify.email(u['email'], 'New sign-in to your School Expert account',
                     f"Hello {u['name']},\n\nYour account was just signed in from a new network ({S.client_ip()}). If this was you, no action is needed. "
                     f"If not, reset your password now and sign out all devices from Account security.\n\nThe School Expert™")

def _fail(u, email):
    audit('auth.login_failed', 'user', u['id'] if u else None, {'email_hash': S.token_hash(email)[:16]})
    if not u: return
    n = (u['failed_logins'] or 0) + 1
    if n >= LOCK_AFTER:
        db.run("UPDATE users SET failed_logins = 0, locked_until = now() + make_interval(mins => %s) WHERE id = %s", LOCK_MINUTES, u['id'])
        audit('security.account_locked', 'user', u['id'], {'minutes': LOCK_MINUTES})
        notify.email(u['email'], 'Your School Expert account was temporarily locked',
                     f'After {LOCK_AFTER} unsuccessful sign-in attempts we have locked your account for {LOCK_MINUTES} minutes. '
                     'If this was not you, reset your password.')
    else:
        db.run('UPDATE users SET failed_logins = %s WHERE id = %s', n, u['id'])

@bp.route('/signup', methods=['GET', 'POST'])
@limited(8, 600, 'signup')
def signup():
    t = request.values.get('type') if request.values.get('type') in TYPES else None
    nxt = _safe_next(request.values.get('next'))
    if request.method == 'POST':
        if S.honeypot_tripped(): audit('security.bot_blocked', 'signup', None); abort(400)
        f = request.form; errors = {}
        name = f.get('name', '').strip(); email = f.get('email', '').strip().lower(); phone = re.sub(r'[^\d+]', '', f.get('phone', ''))
        if not t: errors['type'] = 'Choose an account type.'
        if len(name) < 2: errors['name'] = 'Enter your full name.'
        if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email): errors['email'] = 'Enter a valid email address.'
        if phone and not re.match(r'^\+?\d{10,13}$', phone): errors['phone'] = 'Enter a valid mobile number.'
        pw_err = S.password_problem(f.get('password', ''), f.get('email', ''), f.get('name', ''))
        if pw_err: errors['password'] = pw_err
        if not f.get('adult'): errors['adult'] = 'Accounts are for adults aged 18 or above.'
        if not f.get('consent_account'): errors['consent_account'] = 'Please accept to create your account.'
        if db.val('SELECT 1 FROM users WHERE email = %s', email): errors['email'] = 'An account with this email already exists. Try logging in.'
        if errors:
            return render_template('auth/signup.html', t=t, types=TYPES, errors=errors, form=f, nxt=nxt, notice=consent.notice('account'), mnotice=consent.notice('marketing')), 400
        uid = db.insert('users', dict(email=email, phone=phone or None, name=name[:120], password_hash=S.hash_password(f['password']),
                        account_type=t, is_adult=True, city=f.get('city', '')[:80] or None, attribution=S.attribution()))
        consent.record('account', True, user_id=uid, email=email, context='signup')
        if f.get('consent_marketing'): consent.record('marketing', True, user_id=uid, email=email, context='signup')
        tok = S.make_token('verify_email', email, uid, minutes=60 * 48)
        link = f"{current_app.config['SITE_URL']}{url_for('auth.verify_email', token=tok)}"
        notify.email(email, 'Verify your email — The School Expert™', f'Hello {name},\n\nWelcome to The School Expert™. Please verify your email:\n{link}\n\nThis link is valid for 48 hours.')
        u = db.one('SELECT * FROM users WHERE id = %s', uid); _login(u)
        S.conversion('sign_up', ads_label=current_app.config.get('GOOGLE_ADS_LABEL_SIGNUP') or None, method=t)
        if current_app.config['DEV_SHOW_OTP']: flash(f'Development mode: verification link {link}', 'info')
        flash('Welcome to The School Expert™! Please verify your email from the link we sent.', 'success')
        if t == 'organisation': return redirect(nxt or url_for('register.index'))
        if t == 'teacher': return redirect(nxt or url_for('register.start', slug='teacher-registration'))
        return redirect(nxt or url_for('dashboard.home'))
    return render_template('auth/signup.html', t=t, types=TYPES, errors={}, form={}, nxt=nxt, notice=consent.notice('account'), mnotice=consent.notice('marketing'))

@bp.route('/login', methods=['GET', 'POST'])
@limited(10, 300, 'login')
def login():
    nxt = _safe_next(request.values.get('next'))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        u = db.one("SELECT * FROM users WHERE email = %s AND status IN ('active','pending_deletion')", email)
        if u and u['locked_until'] and u['locked_until'] > datetime.datetime.now(datetime.timezone.utc):
            S.verify_password(_DUMMY_HASH, 'x')
            flash('Too many unsuccessful attempts. Your account is locked for a few minutes — or reset your password.', 'error')
            return render_template('auth/login.html', nxt=nxt, email=email), 429
        ok = S.verify_password(u['password_hash'] if u else _DUMMY_HASH, request.form.get('password', ''))   # same work whether or not the account exists
        if not (u and ok):
            _fail(u, email)
            flash('Incorrect email or password.', 'error')
            return render_template('auth/login.html', nxt=nxt, email=email), 401
        if u['mfa_enabled']:
            session['mfa_pending'] = {'uid': u['id'], 'at': int(time.time()), 'next': nxt}
            return redirect(url_for('auth.mfa_verify'))
        _login(u)
        if MFA.required_for(u) and current_app.config['MFA_REQUIRED_FOR_STAFF']:
            flash('Two-step verification is required for staff accounts. Please set it up now.', 'warning')
            return redirect(url_for('auth.security'))
        if u['status'] == 'pending_deletion':
            flash('Your account is scheduled for deletion. You can cancel this from the Privacy Centre.', 'warning')
        if u['account_type'] in ('admin', 'staff'): return redirect(nxt or url_for('admin.index'))
        return redirect(nxt or url_for('dashboard.home'))
    return render_template('auth/login.html', nxt=nxt, email='')

@bp.route('/login/verify', methods=['GET', 'POST'])
@limited(10, 300, 'mfa')
def mfa_verify():
    p = session.get('mfa_pending')
    if not p or time.time() - p['at'] > 300:
        session.pop('mfa_pending', None); flash('Please sign in again.', 'info'); return redirect(url_for('auth.login'))
    if request.method == 'POST':
        u = db.one('SELECT * FROM users WHERE id = %s', p['uid'])
        if u and MFA.check(u, request.form.get('code')):
            _login(u, mfa=True)
            return redirect(p.get('next') or (url_for('admin.index') if u['account_type'] in ('admin', 'staff') else url_for('dashboard.home')))
        _fail(u, u['email'] if u else '')
        flash('That code did not work. Use the current 6-digit code from your authenticator app, or a recovery code.', 'error')
    return render_template('auth/mfa_verify.html')

@bp.route('/account/security', methods=['GET', 'POST'])
def security():
    if not g.user: return redirect(url_for('auth.login', next=request.path))
    u = db.one('SELECT * FROM users WHERE id = %s', g.user['id'])
    codes = None; secret = session.get('mfa_setup')
    if request.method == 'POST':
        act = request.form.get('action')
        if act == 'start':
            secret = session['mfa_setup'] = MFA.new_secret()
        elif act == 'confirm' and secret:
            if MFA.verify(secret, request.form.get('code')):
                codes = MFA.enable(u['id'], secret); session.pop('mfa_setup', None); session['mfa_at'] = int(time.time()); secret = None
                audit('security.mfa_enabled', 'user', u['id'])
                flash('Two-step verification is on. Save your recovery codes somewhere safe.', 'success')
            else:
                flash('That code did not match. Check the time on your phone and try again.', 'error')
        elif act == 'disable':
            if MFA.required_for(u) and current_app.config['MFA_REQUIRED_FOR_STAFF']: abort(403)
            if not S.verify_password(u['password_hash'], request.form.get('password', '')):
                flash('Password incorrect.', 'error')
            else:
                MFA.disable(u['id']); audit('security.mfa_disabled', 'user', u['id']); flash('Two-step verification turned off.', 'info')
        elif act == 'signout_others':
            keep = hashlib.sha256(session.sid.encode()).hexdigest()
            n = db.run('DELETE FROM sessions WHERE user_id = %s AND sid <> %s', u['id'], keep)
            audit('security.sessions_revoked', 'user', u['id'], {'n': n}); flash(f'Signed out of {n} other device(s).', 'success')
        u = db.one('SELECT * FROM users WHERE id = %s', g.user['id'])
    sessions = db.all('SELECT sid, created_at, last_seen_at, ip, user_agent FROM sessions WHERE user_id = %s AND expires_at > now() ORDER BY last_seen_at DESC LIMIT 20', u['id'])
    current_sid = hashlib.sha256(session.sid.encode()).hexdigest()
    events = db.all("SELECT action, ip, created_at FROM audit_log WHERE actor_id = %s AND (action LIKE 'auth.%%' OR action LIKE 'security.%%') ORDER BY id DESC LIMIT 15", u['id'])
    return render_template('auth/security.html', u=u, secret=secret, uri=MFA.provisioning_uri(secret, u['email']) if secret else None, codes=codes,
                           sessions=sessions, current_sid=current_sid, events=events, required=MFA.required_for(u) and current_app.config['MFA_REQUIRED_FOR_STAFF'])

@bp.route('/reauth', methods=['GET', 'POST'])
@limited(10, 300, 'reauth')
def reauth():
    """Step-up authentication before sensitive actions (viewing private documents, refunds, exports, role changes)."""
    if not g.user: return redirect(url_for('auth.login'))
    nxt = _safe_next(request.values.get('next')) or '/'
    if request.method == 'POST':
        u = db.one('SELECT * FROM users WHERE id = %s', g.user['id'])
        ok = S.verify_password(u['password_hash'], request.form.get('password', ''))
        if ok and u['mfa_enabled']: ok = MFA.check(u, request.form.get('code'))
        if ok:
            session['auth_at'] = int(time.time()); audit('security.reauth', 'user', u['id']); return redirect(nxt)
        _fail(u, u['email']); flash('Could not confirm it is you.', 'error')
    return render_template('auth/reauth.html', nxt=nxt, mfa=g.user['mfa_enabled'])

@bp.route('/logout', methods=['POST'])
def logout():
    if g.user: audit('auth.logout', 'user', g.user['id'])
    session.clear(); session.modified = True
    flash('You have been logged out.', 'info')
    return redirect(url_for('public.home'))

@bp.route('/verify-email/<token>')
def verify_email(token):
    row = S.use_token('verify_email', token)
    if not row:
        flash('This verification link is invalid or has expired.', 'error'); return redirect(url_for('public.home'))
    db.run('UPDATE users SET email_verified_at = now() WHERE id = %s', row['user_id'])
    flash('Email verified. Thank you!', 'success')
    return redirect(url_for('dashboard.home'))

@bp.route('/resend-verification', methods=['POST'])
@limited(3, 600, 'resend')
def resend_verification():
    if g.user and not g.user['email_verified_at']:
        tok = S.make_token('verify_email', g.user['email'], g.user['id'], minutes=60 * 48)
        link = f"{current_app.config['SITE_URL']}{url_for('auth.verify_email', token=tok)}"
        notify.email(g.user['email'], 'Verify your email — The School Expert™', f'Verify your email: {link}')
        if current_app.config['DEV_SHOW_OTP']: flash(f'Development mode: {link}', 'info')
        flash('Verification email sent.', 'success')
    return redirect(request.referrer or url_for('dashboard.home'))

@bp.route('/forgot-password', methods=['GET', 'POST'])
@limited(5, 900, 'forgot')
def forgot():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        u = db.one("SELECT * FROM users WHERE email = %s AND status = 'active'", email)
        if u:
            tok = S.make_token('reset_password', email, u['id'], minutes=60)
            link = f"{current_app.config['SITE_URL']}{url_for('auth.reset', token=tok)}"
            notify.email(email, 'Reset your password — The School Expert™', f'Reset your password (valid 60 minutes): {link}\n\nIf you did not ask for this, ignore this email.')
            if current_app.config['DEV_SHOW_OTP']: flash(f'Development mode: {link}', 'info')
        flash('If an account exists for that email, we have sent a reset link.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/forgot.html')

@bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset(token):
    row = S.use_token('reset_password', token, consume=False)
    if not row:
        flash('This reset link is invalid or has expired.', 'error'); return redirect(url_for('auth.forgot'))
    if request.method == 'POST':
        ru = db.one('SELECT email, name FROM users WHERE id = %s', row['user_id'])
        err = S.password_problem(request.form.get('password', ''), ru['email'] if ru else '', ru['name'] if ru else '')
        if err:
            flash(err, 'error'); return render_template('auth/reset.html', token=token)
        S.use_token('reset_password', token)
        db.run('UPDATE users SET password_hash = %s, password_changed_at = now(), failed_logins = 0, locked_until = NULL WHERE id = %s', S.hash_password(request.form['password']), row['user_id'])
        db.run('DELETE FROM sessions WHERE user_id = %s', row['user_id'])
        audit('auth.password_reset', 'user', row['user_id'], actor_id=row['user_id'])
        flash('Password updated. Please log in.', 'success'); return redirect(url_for('auth.login'))
    return render_template('auth/reset.html', token=token)

@bp.route('/switch-org/<int:org_id>', methods=['POST'])
def switch_org(org_id):
    if g.user and any(o['id'] == org_id for o in g.orgs):
        session['org_id'] = org_id
    return redirect(url_for('dashboard.home'))
