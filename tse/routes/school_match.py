"""AI School Match: questionnaire -> neutral ranked shortlist -> unlock / compare / contact (drives parent unlock revenue)."""
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from ..db import db
from ..lib import match as M, consent, listings as L, entitlements as E
from ..lib.auth import login_required
from ..lib.security import limited, attribution, audit, conversion

bp = Blueprint('school_match', __name__)

def _prefs(f):
    p = dict(city=f.get('city', '').strip()[:60], area=f.get('area', '').strip()[:80], pincode=''.join(ch for ch in f.get('pincode', '') if ch.isdigit())[:6],
             grade=f.get('grade') if f.get('grade') in M.GRADES else '', boards=[b for b in f.getlist('boards') if b in M.BOARDS],
             budget=int(f.get('budget') or 0) if (f.get('budget') or '0').isdigit() else 0, gender=f.get('gender') if f.get('gender') in ('Co-ed', 'Boys', 'Girls') else 'any',
             medium=f.get('medium') if f.get('medium') in M.MEDIUMS else '', type=f.get('type') if f.get('type') in M.TYPES else 'any',
             priorities=[x for x in f.getlist('priorities') if x in M.PRIORITIES][:5])
    return p

@bp.route('/school-match', methods=['GET', 'POST'])
@limited(20, 600, 'school_match')
def index():
    cities = [r['city'] for r in db.all(f"""SELECT city, count(*) n FROM listings WHERE is_published AND city <> '' AND category IN ({','.join(['%s'] * len(M.SCHOOL_CATEGORIES))})
                                            GROUP BY city ORDER BY n DESC LIMIT 60""", *M.SCHOOL_CATEGORIES)]
    if request.method == 'POST':
        p = _prefs(request.form)
        if not p['city'] and not p['pincode']:
            flash('Tell us your city or PIN code so we can find schools near you.', 'error')
            return render_template('school_match/index.html', M=M, cities=cities, p=p, notice=consent.notice('school_match')), 400
        results, pool = M.run(p)
        summary, ai = M.ai_summary(p, results)
        sid = db.insert('school_match_sessions', dict(user_id=g.user['id'] if g.user else None, prefs=p, results=[{'id': r['id'], 'score': r['score']} for r in results],
                        summary=summary, ai_used=ai, attribution=attribution()), returning='public_id')
        for r in results[:10]: E.bump_stat(r['id'], 'match_appearances')
        if g.user: consent.record('school_match', True, user_id=g.user['id'], context='school_match')
        if g.user: conversion('generate_lead', lead_source='school_match', results=len(results))
        return redirect(url_for('school_match.result', sid=sid))
    p = {k: request.args.get(k, '') for k in ('city', 'grade', 'area', 'pincode')}
    p['boards'] = request.args.getlist('boards'); p['priorities'] = []
    return render_template('school_match/index.html', M=M, cities=cities, p=p, notice=consent.notice('school_match'))

@bp.route('/school-match/r/<uuid:sid>')
def result(sid):
    s = db.one('SELECT * FROM school_match_sessions WHERE public_id = %s', str(sid)) or abort(404)
    if s['user_id'] and (not g.user or g.user['id'] != s['user_id']) and not (g.user and g.user['account_type'] in ('admin', 'staff')): abort(404)
    if not s['user_id'] and g.user and g.user['account_type'] == 'parent':   # claim an anonymous run after login/sign-up
        db.run('UPDATE school_match_sessions SET user_id = %s WHERE id = %s', g.user['id'], s['id'])
    results, _ = M.run(s['prefs'])
    unlocked = set(); shortlisted = set(); pack = None
    if g.user:
        ids = [r['id'] for r in results]
        unlocked = {r['listing_id'] for r in db.all('SELECT listing_id FROM unlocks WHERE user_id = %s AND listing_id = ANY(%s)', g.user['id'], ids or [0])}
        shortlisted = {r['listing_id'] for r in db.all('SELECT listing_id FROM shortlists WHERE user_id = %s', g.user['id'])}
        pack = db.one("SELECT * FROM unlock_packs WHERE user_id = %s AND used < quota AND expires_at > now() ORDER BY expires_at LIMIT 1", g.user['id'])
    unlock_plan = db.one("SELECT * FROM plans WHERE code = 'parent_unlock_10'")
    return render_template('school_match/result.html', s=s, results=results, prefs_text=M.describe_prefs(s['prefs']), unlocked=unlocked,
                           shortlisted=shortlisted, pack=pack, unlock_plan=unlock_plan, M=M)

@bp.route('/shortlist', methods=['GET', 'POST'])
@login_required
def shortlist():
    if request.method == 'POST':
        lid = request.form.get('listing_id', type=int)
        l = db.one('SELECT id FROM listings WHERE id = %s AND is_published', lid) or abort(404)
        if request.form.get('remove'):
            db.run('DELETE FROM shortlists WHERE user_id = %s AND listing_id = %s', g.user['id'], l['id'])
        elif db.val('SELECT count(*) FROM shortlists WHERE user_id = %s', g.user['id']) >= 30:
            flash('Your shortlist is full (30). Remove a school to add another.', 'warning')
        else:
            db.run('INSERT INTO shortlists (user_id, listing_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', g.user['id'], l['id'])
        nxt = request.form.get('next') or ''
        return redirect(nxt if nxt.startswith('/') and not nxt.startswith('//') else url_for('school_match.shortlist'))
    rows = db.all("""SELECT l.*, c.label AS category_label, s.created_at AS added_at, (u.listing_id IS NOT NULL) AS unlocked FROM shortlists s
                     JOIN listings l ON l.id = s.listing_id JOIN categories c ON c.slug = l.category
                     LEFT JOIN unlocks u ON u.listing_id = l.id AND u.user_id = s.user_id WHERE s.user_id = %s ORDER BY s.created_at DESC""", g.user['id'])
    runs = db.all('SELECT public_id, prefs, created_at FROM school_match_sessions WHERE user_id = %s ORDER BY id DESC LIMIT 10', g.user['id'])
    return render_template('school_match/shortlist.html', rows=rows, runs=runs, describe=M.describe_prefs)

COMPARE_PUBLIC = [('Type', lambda l: l['category_label']), ('Boards', lambda l: ', '.join(l['boards'] or []) or '—'), ('City', lambda l: l['city'] or '—')]
COMPARE_FIELDS = [('Grades offered', 'grades_offered', 'public'), ('Co-ed / boys / girls', 'co_ed_boys_girls', 'public'), ('Medium of instruction', 'medium_of_instruction', 'public'),
                  ('Year established', 'year_established', 'public'), ('Annual fee range', 'annual_fee_range_per_annum', 'detailed'), ('Admission fee', 'admission_fee', 'detailed'),
                  ('Student–teacher ratio', 'student_teacher_ratio', 'detailed'), ('Transport', 'transport_available', 'detailed'), ('Hostel', 'hostel_available', 'detailed'),
                  ('Facilities', 'facilities', 'detailed'), ('Sports', 'sports_activities', 'detailed'), ('Student support', 'student_support', 'detailed'),
                  ('Scholarships', 'scholarships_available', 'detailed')]

@bp.route('/compare')
def compare():
    ids = [int(x) for x in request.args.getlist('id') if x.isdigit()][:4]
    if len(ids) < 2:
        flash('Pick 2 to 4 schools to compare.', 'info'); return redirect(url_for('school_match.shortlist') if g.user else url_for('school_match.index'))
    rows = db.all("""SELECT l.*, c.label AS category_label FROM listings l JOIN categories c ON c.slug = l.category WHERE l.id = ANY(%s) AND l.is_published""", ids)
    cols = []
    for l in rows:
        det_ok = L.can_view_detailed(g.user, l)
        vals = [fn(l) for _, fn in COMPARE_PUBLIC]
        for label, key, vis in COMPARE_FIELDS:
            src = l['public_data'] if vis == 'public' else (l['detailed_data'] if det_ok else None)
            if src is None: vals.append(None)   # locked
            else:
                v = src.get(key); vals.append(', '.join(v) if isinstance(v, list) else (v if v not in (None, '') else '—'))
        vals.append(f"{float(l['rating_avg'] or 0):.1f}★ ({l['rating_count']})" if l['rating_count'] else 'No reviews yet')
        cols.append(dict(l=l, vals=vals, det_ok=det_ok))
    labels = [x[0] for x in COMPARE_PUBLIC] + [x[0] for x in COMPARE_FIELDS] + ['Verified parent reviews']
    audit('school.compare', 'listing', None, {'ids': ids})
    return render_template('school_match/compare.html', cols=cols, labels=labels)
