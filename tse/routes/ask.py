"""Ask The School Expert (verified school details + expert panel) and Personal Assistance."""
import datetime, decimal
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from ..db import db
from ..lib import payments, consent, crm, notify
from ..lib.auth import login_required, roles, is_staff
from ..lib.security import limited, audit

bp = Blueprint('ask', __name__)

TOPICS = {
  'mental-health': 'Mental health professional',
  'behaviour-consultant': 'Behaviour therapist / consultant',
  'special-educator-registration': 'Special educator',
  'career-guidance': 'Career counsellor',
  'fee-financing': 'School fee financing',
  'educational-consultant-registration': 'Education consultant (admissions, school selection)',
  'k12-curriculum-development-expert-registration': 'Curriculum development expert',
  'homeschooling': 'Homeschooling expert',
  'publish-child-work': "Publish my child's writing",
  'other': 'Something else',
}
IN_HOUSE_FEE = {'parent': 1500, 'organisation': 4999}     # in-house panel consultation (₹, ex-GST) — editable later by admin quote
REFERRAL_FEE = {'parent': 299, 'organisation': 999}

@bp.route('/ask')
def index():
    counts = {r['category']: r['n'] for r in db.all("SELECT category, count(*) n FROM listings WHERE is_published GROUP BY category")}
    return render_template('ask/index.html', topics=TOPICS, counts=counts, topic=request.args.get('topic'),
                           fees=(IN_HOUSE_FEE, REFERRAL_FEE), notice=consent.notice('expert_request'))

@bp.route('/ask/request', methods=['POST'])
@login_required
@limited(6, 3600, 'ask')
def request_expert():
    f = request.form
    topic = f.get('topic') if f.get('topic') in TOPICS else abort(400)
    if not f.get('message') or not f.get('consent'):
        flash('Please describe what you need and accept the notice.', 'error'); return redirect(url_for('ask.index', topic=topic))
    rid = db.insert('expert_requests', dict(user_id=g.user['id'], org_id=g.org['id'] if g.org else None, requester_type=g.user['account_type'],
                    topic=topic, category=topic if topic in TOPICS and '-' in topic else None, message=f['message'][:3000],
                    preferred_mode=f.get('mode'), city=f.get('city', '')[:60], panel=f.get('panel') if f.get('panel') in ('in_house', 'referral') else None,
                    child_info_consent=bool(f.get('child_consent'))))
    consent.record('expert_request', True, user_id=g.user['id'], context=f'expert_request:{rid}')
    crm.emit('expert_request.created', {'id': rid, 'topic': TOPICS[topic], 'name': g.user['name'], 'email': g.user['email'], 'phone': g.user['phone'],
             'city': f.get('city'), 'requester': g.user['account_type']})
    notify.notify_staff('New Ask The School Expert request', f"{TOPICS[topic]} — {g.user['name']}", f'/admin/expert-requests/{rid}')
    flash('Thank you — our team will review your request and send you options (in-house panel or referral) with the fee, usually within one working day.', 'success')
    return redirect(url_for('dashboard.requests'))

@bp.route('/ask/request/<int:rid>/pay', methods=['POST'])
@login_required
def pay_request(rid):
    r = db.one('SELECT * FROM expert_requests WHERE id = %s AND user_id = %s', rid, g.user['id']) or abort(404)
    if r['status'] != 'quoted' or not r['quote_paise']: abort(400)
    order = payments.create_order('expert', f"Ask The School Expert — {TOPICS.get(r['topic'], r['topic'])}", r['quote_paise'], user_id=g.user['id'],
                                  org_id=r['org_id'], meta={'expert_request_id': rid})
    db.run('UPDATE expert_requests SET order_id = %s WHERE id = %s', order['id'], rid)
    return redirect(url_for('pay.checkout', public_id=order['public_id']))

@payments.fulfiller('expert')
def _fulfil_expert(order):
    rid = order['meta']['expert_request_id']
    db.run("UPDATE expert_requests SET status = 'paid', updated_at = now() WHERE id = %s", rid)
    notify.notify_staff('Expert request paid', f'Request #{rid} is paid — please match an expert.', f'/admin/expert-requests/{rid}')

# ---------- verified school details (unlock packs) ----------
@bp.route('/ask/schools')
def schools():
    city = request.args.get('city', '').strip()[:60]
    cities = db.all("""SELECT l.city, count(*) FILTER (WHERE l.tier IN ('detailed','featured')) detailed, count(*) total
                       FROM listings l JOIN categories c ON c.slug = l.category WHERE c.grp = 'schools' AND l.is_published AND l.city <> ''
                       GROUP BY l.city ORDER BY detailed DESC, total DESC""")
    rows = []
    if city:
        rows = db.all("""SELECT l.*, c.label AS category_label FROM listings l JOIN categories c ON c.slug = l.category
                         WHERE c.grp = 'schools' AND l.is_published AND lower(l.city) = lower(%s) AND l.tier IN ('detailed','featured')
                         ORDER BY (l.featured_until >= current_date) DESC NULLS LAST, l.rating_avg DESC, l.name""", city)
    plan = db.one("SELECT * FROM plans WHERE code = 'parent_unlock_10'")
    packs = db.all('SELECT * FROM unlock_packs WHERE user_id = %s AND expires_at > now() ORDER BY expires_at', g.user['id']) if g.user else []
    unlocked = {r['listing_id'] for r in db.all('SELECT listing_id FROM unlocks WHERE user_id = %s', g.user['id'])} if g.user else set()
    return render_template('ask/schools.html', city=city, cities=cities, rows=rows, plan=plan, packs=packs, unlocked=unlocked)

@bp.route('/ask/schools/buy', methods=['POST'])
@roles('parent')
def buy_pack():
    city = request.form.get('city', '').strip()[:60]
    if not city: abort(400)
    plan = db.one("SELECT * FROM plans WHERE code = 'parent_unlock_10' AND active") or abort(404)
    order = payments.create_order('unlock_pack', f'{plan["name"]} — {city}', plan['price_paise'], user_id=g.user['id'], gst_rate=float(plan['gst_rate']),
                                  meta={'plan': plan['code'], 'city': city, 'locality': request.form.get('locality', '')[:80]},
                                  items=[{'title': plan['name'], 'qty': 1, 'unit_paise': plan['price_paise']}])
    return redirect(url_for('pay.checkout', public_id=order['public_id']))

@payments.fulfiller('unlock_pack')
def _fulfil_pack(order):
    plan = db.one('SELECT * FROM plans WHERE code = %s', order['meta']['plan'])
    db.insert('unlock_packs', dict(user_id=order['user_id'], order_id=order['id'], city=order['meta']['city'], locality=order['meta'].get('locality'),
              quota=plan['grants'].get('unlocks', 10), expires_at=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=plan['grants'].get('days', 90))), returning=None)
    notify.notify(order['user_id'], 'Your Ask The School Expert pack is ready', f"You can now unlock detailed views of up to {plan['grants'].get('unlocks', 10)} schools in {order['meta']['city']}.",
                  f"/ask/schools?city={order['meta']['city']}", mail=True)

# ---------- Personal Assistance ----------
def pa_quote(city_row, services, distance_km):
    svc = {s['code']: s for s in db.all('SELECT * FROM pa_services WHERE active')}
    total = svc['standard']['price_paise'] if 'standard' in svc else 0
    lines = [(svc['standard']['name'], svc['standard']['price_paise'])] if 'standard' in svc else []
    for code in services:
        if code in svc and code != 'standard':
            total += svc[code]['price_paise']; lines.append((svc[code]['name'], svc[code]['price_paise']))
    loc = city_row['base_paise'] + int(decimal.Decimal(distance_km or 0) * city_row['per_km_paise'])
    if loc: lines.append((f"Location charge ({city_row['city']}, ~{distance_km or 0} km)", loc)); total += loc
    return total, lines

@bp.route('/personal-assistance')
def pa_index():
    services = db.all('SELECT * FROM pa_services WHERE active ORDER BY sort')
    cities = db.all('SELECT * FROM pa_cities WHERE active ORDER BY city')
    mine = db.all('SELECT * FROM pa_requests WHERE user_id = %s ORDER BY id DESC', g.user['id']) if g.user else []
    school = db.one('SELECT id, name, city FROM listings WHERE slug = %s', request.args.get('school')) if request.args.get('school') else None
    return render_template('ask/pa_index.html', services=services, cities=cities, mine=mine, school=school, notice=consent.notice('personal_assistance'))

@bp.route('/personal-assistance/request', methods=['POST'])
@roles('parent')
@limited(5, 3600, 'pa')
def pa_request():
    f = request.form
    city = db.one('SELECT * FROM pa_cities WHERE city = %s AND active', f.get('city')) or abort(400)
    services = [s for s in f.getlist('services') if s]
    if not services or not (f.get('school_name') or f.get('listing_id')) or not f.get('consent'):
        flash('Choose the school, at least one service and accept the notice.', 'error'); return redirect(url_for('ask.pa_index'))
    try: dist = max(0, min(150, float(f.get('distance_km') or 0)))
    except ValueError: dist = 0
    total, lines = pa_quote(city, services, dist)
    listing_id = f.get('listing_id', type=int)
    school = f.get('school_name') or (db.val('SELECT name FROM listings WHERE id = %s', listing_id) if listing_id else '')
    addr = None
    if 'post_back' in services:
        addr = {k: f.get(k, '')[:200] for k in ('addr_name', 'addr_phone', 'addr_line1', 'addr_line2', 'addr_city', 'addr_pincode')}
        if not addr['addr_line1'] or not addr['addr_pincode']:
            flash('Please give the postal address for posting documents back to you.', 'error'); return redirect(url_for('ask.pa_index'))
    rid = db.insert('pa_requests', dict(user_id=g.user['id'], listing_id=listing_id, school_name=school[:200], city=city['city'], distance_km=dist,
                    services=services, postal_address=addr, notes=f.get('notes', '')[:2000], quote_paise=total, status='quoted'))
    db.insert('pa_updates', dict(request_id=rid, stage='requested', note='Request received. Pay to confirm and our team will begin.', created_by=g.user['id']), returning=None)
    consent.record('personal_assistance', True, user_id=g.user['id'], context=f'pa:{rid}')
    if listing_id:
        l = db.one('SELECT * FROM listings WHERE id = %s', listing_id)
        if l and l['org_id']:
            db.insert('leads', dict(listing_id=listing_id, org_id=l['org_id'], source='personal_assistance', user_id=g.user['id'], name=g.user['name'],
                      email=g.user['email'], phone=g.user['phone'], message='Parent requested The School Expert Personal Assistance for admission.', verified=True), returning=None)
    crm.emit('pa_request.created', {'id': rid, 'name': g.user['name'], 'email': g.user['email'], 'phone': g.user['phone'], 'school': school, 'city': city['city'], 'quote_inr': total / 100})
    order = payments.create_order('personal_assistance', f'Personal Assistance — {school}', total, user_id=g.user['id'], meta={'pa_request_id': rid, 'lines': lines},
                                  items=[{'title': n, 'qty': 1, 'unit_paise': p} for n, p in lines])
    db.run('UPDATE pa_requests SET order_id = %s WHERE id = %s', order['id'], rid)
    return redirect(url_for('pay.checkout', public_id=order['public_id']))

@payments.fulfiller('personal_assistance')
def _fulfil_pa(order):
    rid = order['meta']['pa_request_id']
    db.run("UPDATE pa_requests SET status = 'paid' WHERE id = %s", rid)
    db.insert('pa_updates', dict(request_id=rid, stage='paid', note='Payment received. A member of The School Expert team will be assigned shortly.'), returning=None)
    notify.notify_staff('Personal Assistance paid', f'Request #{rid} — assign an agent.', f'/admin/pa/{rid}', role=None)

PA_STAGES = [('requested', 'Request received'), ('paid', 'Confirmed'), ('assigned', 'Team member assigned'), ('form_collected', 'Application form collected'),
             ('form_filled', 'Application filled'), ('submitted', 'Application submitted'), ('fee_info', 'Fee information shared'),
             ('fee_coordination', 'Fee payment coordinated (paid by parent directly)'), ('tc_collected', 'TC collected'), ('posted', 'Documents posted to you'), ('completed', 'Completed')]

@bp.route('/personal-assistance/<int:rid>')
@login_required
def pa_track(rid):
    r = db.one('SELECT * FROM pa_requests WHERE id = %s', rid) or abort(404)
    if r['user_id'] != g.user['id'] and not is_staff(): abort(404)
    updates = db.all('SELECT * FROM pa_updates WHERE request_id = %s ORDER BY created_at', rid)
    svc = {s['code']: s['name'] for s in db.all('SELECT code, name FROM pa_services')}
    order = db.one('SELECT * FROM orders WHERE id = %s', r['order_id']) if r['order_id'] else None
    return render_template('ask/pa_track.html', r=r, updates=updates, stages=PA_STAGES, svc=svc, order=order)
