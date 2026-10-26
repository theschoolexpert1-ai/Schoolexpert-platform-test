import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from ..db import db
from ..lib import payments, forms as F, notify, crm, consent
from ..lib.auth import login_required
from ..lib.security import limited

bp = Blueprint('events', __name__)

KINDS = {'conference': 'Conferences', 'roundtable': 'Principal Roundtables', 'workshop': 'Workshops', 'webinar': 'Webinars', 'meetup': 'Meetups',
         'homeschool_meetup': 'Homeschool Meetups', 'storytelling': 'Storytelling Sessions', 'bookclub': 'Book Club Sessions', 'expo': 'Expos'}

@bp.route('/events')
def index():
    kind = request.args.get('kind') if request.args.get('kind') in KINDS else None
    when = request.args.get('when', 'upcoming')
    where = ["status IN ('published','completed')"]; args = []
    if kind: where.append('kind = %s'); args.append(kind)
    where.append('starts_at >= now()' if when == 'upcoming' else 'starts_at < now()')
    rows = db.all(f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY starts_at {'ASC' if when == 'upcoming' else 'DESC'} LIMIT 60", *args)
    return render_template('events/index.html', rows=rows, kinds=KINDS, kind=kind, when=when)

@bp.route('/events/<slug>')
def detail(slug):
    e = db.one('SELECT * FROM events WHERE slug = %s', slug) or abort(404)
    if e['status'] == 'draft': abort(404)
    defn = F.get(e['form_slug']) if e['form_slug'] else None
    mine = db.all('SELECT * FROM event_registrations WHERE event_id = %s AND user_id = %s ORDER BY id DESC', e['id'], g.user['id']) if g.user else []
    taken = db.val("SELECT COALESCE(sum(attendees),0) FROM event_registrations WHERE event_id = %s AND status IN ('confirmed','requested')", e['id'])
    sponsors = db.all("SELECT * FROM sponsorships WHERE event_id = %s AND status = 'confirmed'", e['id'])
    album = db.one('SELECT * FROM gallery_albums WHERE event_id = %s AND published', e['id'])
    member = g.user and db.val("SELECT 1 FROM club_memberships WHERE user_id = %s AND club = 'bookclub' AND status = 'active'", g.user['id'])
    price = e['member_price_paise'] if (member and e['member_price_paise'] is not None) else e['price_paise']
    return render_template('events/detail.html', e=e, defn=defn, mine=mine, left=(e['capacity'] - taken) if e['capacity'] else None,
                           sponsors=sponsors, album=album, price=price, states=F.INDIAN_STATES, kinds=KINDS)

@bp.route('/events/<slug>/register', methods=['POST'])
@login_required
@limited(10, 3600, 'event_reg')
def register(slug):
    e = db.one("SELECT * FROM events WHERE slug = %s AND status = 'published' AND starts_at > now()", slug) or abort(404)
    n = max(1, min(20, request.form.get('attendees', 1, type=int)))
    if g.user['account_type'] != 'organisation': n = 1 if e['kind'] not in ('meetup', 'homeschool_meetup', 'storytelling') else min(n, 4)
    answers = {}
    if e['form_slug']:
        defn = F.get(e['form_slug'])
        for si in range(len(defn['sections'])):
            a, _, errs = F.parse_section(defn, si, request.form, request.files, {})
            answers.update(a)
            if errs: flash('Please correct: ' + '; '.join(errs.values()), 'error'); return redirect(url_for('events.detail', slug=slug))
        miss = F.missing_required(defn, answers, {})
        if miss:
            flash(f'Please complete all required fields ({len(miss)} missing).', 'error'); return redirect(url_for('events.detail', slug=slug))
    if e['capacity']:
        taken = db.val("SELECT COALESCE(sum(attendees),0) FROM event_registrations WHERE event_id = %s AND status IN ('confirmed','requested')", e['id'])
        if taken + n > e['capacity']:
            flash('Sorry, this event is full.', 'error'); return redirect(url_for('events.detail', slug=slug))
    member = db.val("SELECT 1 FROM club_memberships WHERE user_id = %s AND club = 'bookclub' AND status = 'active'", g.user['id'])
    price = e['member_price_paise'] if (member and e['member_price_paise'] is not None) else e['price_paise']
    rid = db.insert('event_registrations', dict(event_id=e['id'], user_id=g.user['id'], org_id=g.org['id'] if g.org else None, attendees=n, answers=answers,
                    status='requested'))
    crm.emit('event.registration', {'event': e['title'], 'name': g.user['name'], 'email': g.user['email'], 'phone': g.user['phone'], 'attendees': n})
    if price:
        o = payments.create_order('event_pass', f"{e['title']} — {n} pass(es)", price * n, user_id=g.user['id'], org_id=g.org['id'] if g.org else None,
                                  meta={'event_registration_id': rid}, items=[{'title': f"Pass: {e['title']}", 'qty': n, 'unit_paise': price}])
        db.run('UPDATE event_registrations SET order_id = %s WHERE id = %s', o['id'], rid)
        return redirect(url_for('pay.checkout', public_id=o['public_id']))
    if e['passes_require_approval']:
        notify.notify_staff('Event pass request', f"{g.user['name']} requested {n} pass(es) for {e['title']}", f"/admin/events/{e['id']}")
        flash('Your pass request has been received. We will confirm by email.', 'success')
    else:
        _confirm(rid); flash('You are registered! Your pass is in your dashboard.', 'success')
    return redirect(url_for('dashboard.events'))

def _confirm(rid):
    db.run("UPDATE event_registrations SET status = 'confirmed', pass_code = COALESCE(pass_code, %s) WHERE id = %s", 'TSE-' + secrets.token_hex(3).upper(), rid)
    r = db.one('SELECT er.*, e.title, e.starts_at FROM event_registrations er JOIN events e ON e.id = er.event_id WHERE er.id = %s', rid)
    notify.notify(r['user_id'], f"Pass confirmed: {r['title']}", f"Pass code {r['pass_code']}. See you there!", '/dashboard/events', mail=True)

@payments.fulfiller('event_pass')
def _fulfil(order):
    _confirm(order['meta']['event_registration_id'])

@bp.route('/events/<slug>/sponsor', methods=['POST'])
@limited(5, 3600, 'sponsor')
def sponsor(slug):
    e = db.one('SELECT * FROM events WHERE slug = %s', slug) or abort(404)
    f = request.form
    if not f.get('sponsor_name') or not f.get('contact_email'): abort(400)
    db.insert('sponsorships', dict(event_id=e['id'], org_id=g.org['id'] if g.org else None, sponsor_name=f['sponsor_name'][:160], tier=f.get('tier', 'Partner')[:40],
              contact_email=f['contact_email'][:200], message=f.get('message', '')[:2000]), returning=None)
    crm.emit('sponsorship.enquiry', {'event': e['title'], 'org_name': f['sponsor_name'], 'email': f['contact_email'], 'tier': f.get('tier')})
    notify.notify_staff('Sponsorship enquiry', f"{f['sponsor_name']} — {e['title']}", f"/admin/events/{e['id']}")
    flash('Thank you for your interest in sponsoring. Our partnerships team will contact you.', 'success')
    return redirect(url_for('events.detail', slug=slug))

@bp.route('/events/<slug>.ics')
def ics(slug):
    """Add-to-calendar file (public event details only)."""
    from flask import Response, current_app
    import datetime as _dt
    e = db.one("SELECT * FROM events WHERE slug = %s AND status IN ('published','completed')", slug) or abort(404)
    fmt = lambda d: d.astimezone(_dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    esc = lambda s: (s or '').replace('\\', '\\\\').replace(';', r'\;').replace(',', '\\,').replace('\r', '').replace('\n', '\\n')
    end = e['ends_at'] or (e['starts_at'] + _dt.timedelta(minutes=90))
    url = f"{current_app.config['SITE_URL']}/events/{e['slug']}"
    desc = (e['summary'] or '') + (f" — Facilitator: {e['facilitator']}" if e.get('facilitator') else '') + (f" — {e['cpd_hours']} CPD hours" if e.get('cpd_hours') else '') + f' — {url}'
    body = '\r\n'.join(['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//The School Expert//Events//EN', 'CALSCALE:GREGORIAN', 'BEGIN:VEVENT',
                        f"UID:event-{e['id']}@schoolexpert.in", f'DTSTAMP:{fmt(_dt.datetime.now(_dt.timezone.utc))}', f"DTSTART:{fmt(e['starts_at'])}", f'DTEND:{fmt(end)}',
                        f"SUMMARY:{esc(e['title'])}", f'DESCRIPTION:{esc(desc)}', f"LOCATION:{esc(e['venue'] or ('Online' if e['mode'] == 'online' else e['city']))}",
                        f'URL:{url}', 'END:VEVENT', 'END:VCALENDAR']) + '\r\n'
    return Response(body, mimetype='text/calendar', headers={'Content-Disposition': f'attachment; filename="{e["slug"][:60]}.ics"'})
