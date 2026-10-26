"""AI School Match — helps parents shortlist the right school.

Design principles
- Neutral ranking: the score uses only fit to the parent's stated preferences, verification and verified reviews.
  Payment never changes a school's score. Sponsored schools are shown separately and labelled "Sponsored".
- Data minimisation: we ask about the family's preferences (city, area, grade, board, budget, priorities) —
  never the child's name, age, date of birth or any other child data.
- Transparency: every match shows the reasons. Reasons that rely on detailed data (fees, facilities, support)
  are shown in full to parents who unlock the school; others see that the reason exists.
- Schools on Plus/Pro share their verified detailed profile with the matcher (`ai_match` grant). For other schools
  only public fields are used, and unknown information scores neutral (never negative).
"""
import json, re
from flask import current_app
from ..db import db
from . import entitlements as E

SCHOOL_CATEGORIES = ('school-registration', 'preschool', 'inclusive-school', 'special-school', 'alternative-school', 'online-school-registration')
GRADES = ['Nursery', 'LKG', 'UKG', 'Grade 1–5', 'Grade 6–8', 'Grade 9–10', 'Grade 11–12']
BOARDS = ['CBSE', 'ICSE', 'State Board', 'IB', 'IGCSE']
BUDGETS = [(0, 'No limit'), (50000, 'Up to ₹50,000 / year'), (100000, 'Up to ₹1 lakh / year'), (150000, 'Up to ₹1.5 lakh / year'),
           (250000, 'Up to ₹2.5 lakh / year'), (400000, 'Up to ₹4 lakh / year'), (700000, 'Up to ₹7 lakh / year')]
MEDIUMS = ['English', 'Kannada', 'Hindi', 'Tamil', 'Telugu', 'Malayalam', 'Marathi', 'Gujarati', 'Bengali', 'Urdu']
TYPES = {'any': 'Any', 'school-registration': 'Regular school', 'preschool': 'Pre-school', 'inclusive-school': 'Inclusive school',
         'special-school': 'Special school', 'alternative-school': 'Alternative school', 'online-school-registration': 'Online school'}
PRIORITIES = {
    'academics': ('Strong academics & exam support', ['olympiad', 'competitive', 'achievement', 'result', 'curriculum']),
    'stem': ('STEM, coding & robotics', ['stem', 'coding', 'robotic', 'ai lab', 'science lab', 'computer lab', 'math lab']),
    'sports': ('Sports', ['cricket', 'football', 'basketball', 'athletics', 'swimming', 'skating', 'sports', 'yoga', 'karate', 'chess', 'playground']),
    'arts': ('Arts & co-curricular', ['music', 'dance', 'drama', 'art', 'craft', 'debate', 'public speaking', 'mun', 'theatre']),
    'support': ('Learning support & counselling', ['counsellor', 'special educator', 'inclusive', 'learning support', 'mental health', 'therapy', 'remedial']),
    'small_classes': ('Small class sizes', []),
    'transport': ('School transport', []),
    'hostel': ('Hostel / boarding', []),
    'languages': ('Languages', ['language lab', 'french', 'german', 'spanish', 'japanese', 'sanskrit']),
    'values': ('Values & holistic development', ['value', 'holistic', 'mindful', 'life skill', 'character', 'montessori', 'waldorf', 'experiential']),
}
WEIGHTS = dict(location=22, grade=16, board=14, budget=16, gender=6, medium=6, type=6, priorities=10, trust=4)

def _flat(d):
    out = []
    for v in (d or {}).values():
        if isinstance(v, list): out += [str(x) for x in v if not isinstance(x, dict)]
        elif isinstance(v, (str, int, float)) and not isinstance(v, bool): out.append(str(v))
    return ' '.join(out).lower()

def _find(d, *needles):
    for k, v in (d or {}).items():
        if any(n in k for n in needles): return v
    return None

def parse_fee(text):
    """'₹1,20,000 - 1,80,000', '1.2L to 1.8 lakh', '85k–1.1L' -> (min, max) rupees; None if unparseable."""
    if text is None: return None
    if isinstance(text, (int, float)): return (int(text), int(text))
    t = str(text).lower().replace(',', '')
    vals = []
    for num, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(lakhs?|lacs?|l\b|k\b|thousand|cr)?', t):
        v = float(num)
        if unit and unit.startswith(('l', 'lac')): v *= 100000
        elif unit in ('k', 'thousand'): v *= 1000
        elif unit == 'cr': v *= 10000000
        if v >= 1000: vals.append(int(v))
    if not vals: return None
    return (min(vals), max(vals))

def _yes(v):
    return v is True or (isinstance(v, str) and v.strip().lower() in ('yes', 'y', 'true', 'available'))

def score(l, prefs, full):
    """Return (score 0-100, reasons[{text, detail, good}]). `full`: may use detailed_data (school shares it via ai_match)."""
    pub = l['public_data'] or {}; det = (l['detailed_data'] or {}) if full else {}
    both = {**det, **pub}
    reasons = []; pts = 0.0; total = 0.0
    def add(w, frac, text=None, detail=False, good=True):
        nonlocal pts, total
        total += w; pts += w * max(0.0, min(1.0, frac))
        if text: reasons.append(dict(text=text, detail=detail, good=good))

    # location
    city = (prefs.get('city') or '').strip().lower(); pin = (prefs.get('pincode') or '').strip(); area = (prefs.get('area') or '').strip().lower()
    if l['category'] == 'online-school-registration': add(WEIGHTS['location'], .8, 'Online school — no commute')
    elif pin and l['pincode'] == pin: add(WEIGHTS['location'], 1, f"In your PIN code {pin}")
    elif pin and l['pincode'] and l['pincode'][:4] == pin[:4]: add(WEIGHTS['location'], .85, 'Close to your PIN code')
    elif area and area in ((l['locality'] or '') + ' ' + (l['district'] or '') + ' ' + _flat({'a': both.get('address'), 'l': both.get('landmark')})).lower():
        add(WEIGHTS['location'], .9, f"In or near {prefs.get('area')}")
    elif city and city == (l['city'] or '').lower(): add(WEIGHTS['location'], .6, f"In {l['city']}")
    else: add(WEIGHTS['location'], .2)

    # grade
    g = prefs.get('grade')
    grades = _find(pub, 'grades_offered', 'grade', 'classes', 'age_group', 'programmes') or []
    if g:
        gl = grades if isinstance(grades, list) else [str(grades)]
        if g in gl: add(WEIGHTS['grade'], 1, f"Offers {g}")
        elif gl: add(WEIGHTS['grade'], 0, f"Does not list {g}", good=False)
        elif l['category'] == 'preschool' and g in ('Nursery', 'LKG', 'UKG'): add(WEIGHTS['grade'], .8, 'Pre-school programmes')
        else: add(WEIGHTS['grade'], .5)

    # board
    want = prefs.get('boards') or []
    if want:
        have = set(l['boards'] or [])
        hit = [b for b in want if b in have]
        if hit: add(WEIGHTS['board'], 1, ' / '.join(hit) + ' board')
        elif have: add(WEIGHTS['board'], 0, 'Board: ' + ', '.join(sorted(have)), good=False)
        else: add(WEIGHTS['board'], .5)

    # budget (detailed)
    budget = int(prefs.get('budget') or 0)
    if budget:
        fee = parse_fee(_find(det, 'annual_fee', 'fee_range', 'fees', 'fee'))
        if fee:
            lo, hi = fee
            if hi <= budget: add(WEIGHTS['budget'], 1, 'Annual fees within your budget', detail=True)
            elif lo <= budget: add(WEIGHTS['budget'], .6, 'Some grades within your budget', detail=True)
            else: add(WEIGHTS['budget'], .1, 'Fees above your budget', detail=True, good=False)
        else: add(WEIGHTS['budget'], .5)

    # gender
    gp = prefs.get('gender')
    if gp and gp != 'any':
        gv = _find(pub, 'co_ed', 'gender')
        if gv: add(WEIGHTS['gender'], 1 if gv == gp else 0, gv if gv == gp else f"{gv} school", good=gv == gp)
        else: add(WEIGHTS['gender'], .5)

    # medium
    md = prefs.get('medium')
    if md:
        mv = _find(pub, 'medium_of_instruction', 'medium') or _find(det, 'medium')
        ml = mv if isinstance(mv, list) else ([mv] if mv else [])
        if ml: add(WEIGHTS['medium'], 1 if md in ml else 0, f"{md} medium" if md in ml else None)
        else: add(WEIGHTS['medium'], .5)

    # type
    tp = prefs.get('type')
    if tp and tp != 'any':
        add(WEIGHTS['type'], 1 if l['category'] == tp else (.6 if tp == 'inclusive-school' and _yes(_find(det, 'inclusive')) else 0),
            TYPES.get(tp) if l['category'] == tp else None)

    # priorities
    pr = [p for p in (prefs.get('priorities') or []) if p in PRIORITIES]
    if pr:
        text = _flat(both) + ' ' + ' '.join(l['tags'] or []).lower()
        got = 0
        for p in pr:
            label, kws = PRIORITIES[p]; ok = False
            if p == 'transport': ok = _yes(_find(det, 'transport'))
            elif p == 'hostel': ok = _yes(_find(det, 'hostel', 'boarding'))
            elif p == 'small_classes':
                r = _find(det, 'student_teacher_ratio', 'ratio')
                m = re.search(r'1\s*:\s*(\d+)', str(r or '')) or re.search(r'(\d+)\s*:\s*1', str(r or ''))
                ok = bool(m and int(m.group(1)) <= 20)
            else: ok = any(k in text for k in kws)
            if ok: got += 1; reasons.append(dict(text=label, detail=p in ('transport', 'hostel', 'small_classes', 'support') or not any(k in _flat(pub).lower() for k in kws), good=True))
        add(WEIGHTS['priorities'], got / len(pr))

    # trust: verification + verified parent reviews (reviews only from parents who paid to unlock)
    rc = l['rating_count'] or 0; ra = float(l['rating_avg'] or 0)
    trust = (.5 if l['verified'] else 0) + (.5 * (ra / 5) * min(1, rc / 5) if rc else .25)
    add(WEIGHTS['trust'], trust, f"{ra:.1f}★ from {rc} verified parent review{'s' if rc != 1 else ''}" if rc else None)

    return (round(100 * pts / total) if total else 0), reasons

def run(prefs, limit=12):
    city = (prefs.get('city') or '').strip()
    rows = db.all(f"""SELECT l.*, c.label AS category_label FROM listings l JOIN categories c ON c.slug = l.category
                      WHERE l.is_published AND l.parent_listing_id IS NULL AND l.category IN ({','.join(['%s'] * len(SCHOOL_CATEGORIES))})
                        AND (%s = '' OR lower(l.city) = lower(%s) OR l.category = 'online-school-registration')
                      LIMIT 1500""", *SCHOOL_CATEGORIES, city, city)
    full_cache = {}
    out = []
    for l in rows:
        oid = l['org_id']
        if oid not in full_cache: full_cache[oid] = bool(E.for_org(oid).get('ai_match')) if oid else False
        s, reasons = score(l, prefs, full_cache[oid])
        out.append(dict(id=l['id'], slug=l['slug'], name=l['name'], city=l['city'], locality=l['locality'], logo_url=l['logo_url'],
                        category_label=l['category_label'], boards=l['boards'], verified=l['verified'], rating_avg=float(l['rating_avg'] or 0),
                        rating_count=l['rating_count'], headline=l['headline'], score=s, reasons=reasons, rich=full_cache[oid]))
    # neutral ordering: score, then verified reviews, then name — never plan/tier
    out.sort(key=lambda r: (-r['score'], -r['rating_count'], r['name']))
    return out[:limit], len(rows)

def describe_prefs(p):
    bits = []
    if p.get('grade'): bits.append(p['grade'])
    if p.get('boards'): bits.append('/'.join(p['boards']))
    if p.get('type') and p['type'] != 'any': bits.append(TYPES.get(p['type'], ''))
    loc = ', '.join(x for x in [p.get('area'), p.get('pincode'), p.get('city')] if x)
    if loc: bits.append('near ' + loc)
    if p.get('budget'): bits.append(dict(BUDGETS).get(int(p['budget']), '').lower())
    if p.get('priorities'): bits.append('priorities: ' + ', '.join(PRIORITIES[x][0].lower() for x in p['priorities'] if x in PRIORITIES))
    return '; '.join(b for b in bits if b)

def template_summary(prefs, results):
    if not results: return ('We could not find verified schools that match yet. Try widening the area or budget, or use Ask The School Expert '
                            'and our team will research options for you.')
    top = results[0]
    lines = [f"For {describe_prefs(prefs) or 'your preferences'}, {len(results)} verified schools fit well. "
             f"{top['name']} is the closest match ({top['score']}%)."]
    lines.append('Before you decide, visit at least two schools, ask about the admission timeline, total annual cost (including transport, '
                 'books and activities), class size, teacher experience and how the school supports children who need extra help.')
    return ' '.join(lines)

SYSTEM = ("You are The School Expert™ school-choice advisor for Indian parents. You are given the parent's preferences (no child personal data) "
          "and a ranked list of verified schools with match reasons. Write a warm, practical 90-140 word summary: why the top 2-3 fit, any trade-offs, "
          "and 3 specific questions to ask on a school visit. Never invent facts about schools beyond what is given, never mention fees amounts, "
          "never rank by anything except fit, and do not ask for the child's personal details. Plain text, no markdown headings.")

def ai_summary(prefs, results):
    key = current_app.config.get('ANTHROPIC_API_KEY')
    base = template_summary(prefs, results)
    if not key or not results: return base, False
    brief = [{'name': r['name'], 'match': r['score'], 'type': r['category_label'], 'boards': r['boards'], 'verified': r['verified'],
              'reasons': [x['text'] for x in r['reasons'] if x['good'] and not x['detail']][:6]} for r in results[:5]]
    try:
        import requests
        resp = requests.post('https://api.anthropic.com/v1/messages', timeout=30, headers={
            'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            json={'model': current_app.config['ANTHROPIC_MODEL'], 'max_tokens': 600, 'system': SYSTEM,
                  'messages': [{'role': 'user', 'content': json.dumps({'preferences': describe_prefs(prefs), 'schools': brief}, ensure_ascii=False)}]})
        resp.raise_for_status()
        text = ''.join(b.get('text', '') for b in resp.json().get('content', [])).strip()
        return (text or base), bool(text)
    except Exception as e:
        current_app.logger.warning('School Match AI summary failed, using template: %s', e)
        return base, False
