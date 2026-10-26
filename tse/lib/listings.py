"""Registration -> directory listing synchronisation, tiers, search."""
import re, unicodedata, secrets, datetime
from ..db import db
from . import forms
from .security import decrypt_json

def slugify(s, maxlen=70):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    s = re.sub(r'[^a-zA-Z0-9]+', '-', s).strip('-').lower()
    return s[:maxlen].strip('-') or 'item'

def unique_slug(table, base, col='slug'):
    s = slugify(base); cand = s; i = 2
    while db.val(f'SELECT 1 FROM {table} WHERE {col} = %s', cand):
        cand = f'{s}-{i}'; i += 1
    return cand

def _txt(v):
    if isinstance(v, list): return ', '.join(str(x) for x in v if not isinstance(x, dict))
    return str(v) if v not in (None, False) else ''

def sync(reg_id):
    """Create/update the listing for a registration. Returns listing id (or None for non-listed categories)."""
    with db.elevated():
        return _sync(reg_id)

def _sync(reg_id):
    reg = db.one('SELECT r.*, c.listed, c.grp FROM registrations r JOIN categories c ON c.slug = r.form_slug WHERE r.id = %s', reg_id)
    if not reg or not reg['listed']: return None
    defn = forms.get(reg['form_slug'])
    a = reg['answers']; files = reg['files']
    role = lambda r: forms.answer_by_role(defn, a, r)
    name = role('name') or role('name_alt') or 'Untitled'
    if reg['form_slug'] == 'recreation-hobbies-enrichment-provider' and a.get('organisation_academy_centre_name'):
        name = a['organisation_academy_centre_name']
    logo_f = forms.field_by_role(defn, 'logo')
    logo = (files.get(logo_f['key']) or [{}])[0].get('url') if logo_f else None
    city = role('city') or ''
    if forms.field_by_role(defn, 'city') and forms.field_by_role(defn, 'city')['label'] == 'City / State' and ',' in city:
        city = city.split(',')[0].strip()
    state = role('state') or ''
    district = a.get('district') or a.get('current_district') or ''
    pincode = a.get('pin_code') or ''
    pub, det = {}, {}
    boards, tags = [], []
    for _, s, f in forms.fields(defn):
        v = a.get(f['key'])
        if forms.is_empty(v): continue
        vis = f.get('visibility', 'detailed')
        if vis == 'public': pub[f['key']] = v
        elif vis == 'detailed': det[f['key']] = v
        if re.search(r'board|curricul', f['label'], re.I) and isinstance(v, list): boards += [x for x in v if isinstance(x, str)]
        if f['type'] in ('checkbox',) and vis != 'private' and isinstance(v, list): tags += [x for x in v if isinstance(x, str)][:40]
    search_text = ' '.join([name, city, district, state, _txt(role('headline')), _txt(role('about'))[:2000], ' '.join(boards), ' '.join(tags)])
    data = dict(name=name[:200], headline=_txt(role('headline'))[:300] or None, about=_txt(role('about'))[:4000] or None,
                logo_url=logo, city=city[:100], state=state, district=district[:100], pincode=pincode[:6],
                boards=sorted(set(boards))[:30], tags=sorted(set(tags))[:200], public_data=pub, detailed_data=det,
                verified=reg['status'] == 'verified', is_published=reg['status'] == 'verified')
    existing = db.one('SELECT id, slug FROM listings WHERE registration_id = %s', reg_id)
    if existing:
        sets = ', '.join(f'{k} = %s' for k in data)
        vals = [db.Json(v) if k in ('public_data', 'detailed_data') else v for k, v in data.items()]
        db.run(f'UPDATE listings SET {sets}, updated_at = now() WHERE id = %s', *vals, existing['id'])
        lid = existing['id']
    else:
        lid = db.insert('listings', dict(registration_id=reg_id, org_id=reg['org_id'], user_id=reg['user_id'] if not reg['org_id'] else None,
                        category=reg['form_slug'], slug=unique_slug('listings', f'{name} {city}'), **data))
    db.run("UPDATE listings SET search = to_tsvector('simple', %s) WHERE id = %s", search_text, lid)
    refresh_tier(lid)
    return lid

def refresh_tier(listing_id):
    """Payment decides visibility: tier, featured status and publication come from the organisation's active plan."""
    from . import entitlements as E
    with db.elevated():   # visibility is recomputed server-side from the registration status
        l = db.one('SELECT l.*, r.status AS reg_status FROM listings l LEFT JOIN registrations r ON r.id = l.registration_id WHERE l.id = %s', listing_id)
    if not l: return
    e = E.for_org(l['org_id']) if l['org_id'] else dict(E.NONE)
    tier = e.get('tier', 'basic') if e['level'] else 'basic'
    featured = e.get('ends_at') or (datetime.date.today() + datetime.timedelta(days=365)) if e.get('featured') else None
    published = bool(l['reg_status'] == 'verified' and e.get('published'))
    db.run('UPDATE listings SET tier = %s, tier_until = %s, featured_until = %s, is_published = %s WHERE id = %s',
           tier, e.get('ends_at'), featured, published, listing_id)

def refresh_org(org_id):
    for l in db.all('SELECT id FROM listings WHERE org_id = %s', org_id): refresh_tier(l['id'])

def search(category=None, grp=None, q=None, city=None, state=None, board=None, tag=None, verified_only=False, sort='relevance', limit=24, offset=0, tier_min=None):
    where = ['l.is_published']; args = []
    if category: where.append('l.category = %s'); args.append(category)
    if grp: where.append('c.grp = %s'); args.append(grp)
    if city: where.append('lower(l.city) = lower(%s)'); args.append(city)
    if state: where.append('l.state = %s'); args.append(state)
    if board: where.append('%s = ANY(l.boards)'); args.append(board)
    if tag: where.append('%s = ANY(l.tags)'); args.append(tag)
    if verified_only: where.append('l.verified')
    if tier_min == 'detailed': where.append("l.tier IN ('detailed','featured')")
    rank = '0'
    if q:
        where.append("(l.search @@ plainto_tsquery('simple', %s) OR l.name ILIKE %s)"); args += [q, f'%{q}%']
        rank = "ts_rank(l.search, plainto_tsquery('simple', %s))";
    tier_rank = "CASE l.tier WHEN 'featured' THEN 3 WHEN 'detailed' THEN 2 ELSE 1 END"
    order = {'rating': 'l.rating_avg DESC, l.rating_count DESC', 'name': 'l.name', 'new': 'l.created_at DESC'}.get(sort,
             f"(l.featured_until >= current_date) DESC NULLS LAST, {tier_rank} DESC, l.rating_avg DESC, l.name")
    sql = f"""SELECT l.*, c.label AS category_label, c.grp, count(*) OVER() AS total FROM listings l JOIN categories c ON c.slug = l.category
              WHERE {' AND '.join(where)} ORDER BY {order} LIMIT %s OFFSET %s"""
    rows = db.all(sql, *args, limit, offset)
    return rows, (rows[0]['total'] if rows else 0)

def can_view_detailed(user, listing):
    """Detailed view rules:
       - owner / staff always
       - listing must be on a paid detailed/featured tier, then:
         - parents: unlocked via a paid pack (Ask The School Expert)
         - schools: teacher-training institutes free pan-India; others require a paid organisation plan
         - verified teachers: may view schools they applied to"""
    if not user: return False
    if user['account_type'] in ('admin', 'staff'): return True
    if listing['org_id'] and db.val('SELECT 1 FROM org_members WHERE org_id = %s AND user_id = %s', listing['org_id'], user['id']): return True
    if listing['user_id'] == user['id']: return True
    if listing['tier'] not in ('detailed', 'featured'): return False
    if db.val('SELECT 1 FROM unlocks WHERE user_id = %s AND listing_id = %s', user['id'], listing['id']): return True
    cat = db.one('SELECT * FROM categories WHERE slug = %s', listing['category'])
    if user['account_type'] == 'organisation':
        from . import entitlements as E
        e = E.current()
        if cat['school_access'] == 'detailed_free' and e.get('level', 0) >= 1: return True
        return bool(e.get('directory_access'))
    return False

def private_answers(reg):
    try: return decrypt_json(reg['private_enc'])
    except Exception: return {}
