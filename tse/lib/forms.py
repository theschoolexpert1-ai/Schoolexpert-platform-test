"""Dynamic form engine driven by JSON definitions stored in form_definitions.

Every registration form becomes: a multi-step registration form, a profile page (public / paid-detailed tiers),
and filterable directory data — no per-form code.
"""
import re, json
from ..db import db
from . import storage

INDIAN_STATES = ['Andhra Pradesh', 'Arunachal Pradesh', 'Assam', 'Bihar', 'Chhattisgarh', 'Goa', 'Gujarat', 'Haryana',
    'Himachal Pradesh', 'Jharkhand', 'Karnataka', 'Kerala', 'Madhya Pradesh', 'Maharashtra', 'Manipur', 'Meghalaya',
    'Mizoram', 'Nagaland', 'Odisha', 'Punjab', 'Rajasthan', 'Sikkim', 'Tamil Nadu', 'Telangana', 'Tripura',
    'Uttar Pradesh', 'Uttarakhand', 'West Bengal', 'Andaman & Nicobar Islands', 'Chandigarh',
    'Dadra & Nagar Haveli and Daman & Diu', 'Delhi', 'Jammu & Kashmir', 'Ladakh', 'Lakshadweep', 'Puducherry']

_cache = {}
def get(slug):
    row = db.one('SELECT f.*, c.grp, c.label, c.entity FROM form_definitions f JOIN categories c ON c.slug = f.slug WHERE f.slug = %s', slug)
    if not row: return None
    key = (slug, row['version'], str(row['updated_at']))
    if key not in _cache:
        d = row['definition']
        d['_meta'] = dict(slug=slug, version=row['version'], provisional=row['provisional'], grp=row['grp'], label=row['label'], entity=row['entity'])
        _cache.clear() if len(_cache) > 200 else None
        _cache[key] = d
    return _cache[key]

def fields(defn):
    for si, s in enumerate(defn['sections']):
        for f in s['fields']:
            yield si, s, f

def field_by_role(defn, role):
    for _, _, f in fields(defn):
        if f.get('role') == role: return f
    return None

def is_empty(v):
    return v is None or v == '' or v == [] or v == {} or (isinstance(v, dict) and not any(v.values()))

# ---------------- parsing ----------------
def parse_section(defn, si, form, files, existing_files):
    """Read one section from the request. Returns (answers, file_updates, errors_for_format)."""
    sec = defn['sections'][si]
    out, fout, errs = {}, {}, {}
    for f in sec['fields']:
        k, t = f['key'], f['type']
        try:
            if t in ('checkbox',):
                vals = [v for v in form.getlist(k) if v in f.get('options', [])]
                if f.get('other') and form.get(k + '__other', '').strip():
                    vals.append('Other: ' + form.get(k + '__other').strip()[:200])
                if f.get('maxSelect') and len(vals) > f['maxSelect']:
                    errs[k] = f"Select up to {f['maxSelect']}."
                out[k] = vals
            elif t in ('radio', 'select'):
                v = form.get(k, '')
                if v == '__other' and f.get('other'):
                    v = 'Other: ' + form.get(k + '__other', '').strip()[:200]
                elif v and v not in f.get('options', []):
                    v = ''
                out[k] = v
            elif t == 'state':
                v = form.get(k, ''); out[k] = v if v in INDIAN_STATES else ''
            elif t in ('yesno',):
                v = form.get(k, ''); out[k] = v if v in ('Yes', 'No') else ''
            elif t in ('boolean', 'consent'):
                out[k] = form.get(k) == 'on'
            elif t == 'matrix':
                m = {}
                for ri, row in enumerate(f.get('rows', [])):
                    sel = [c for c in form.getlist(f'{k}__{ri}') if c in f.get('columns', [])]
                    if sel: m[row] = sel
                out[k] = m
            elif t == 'repeat':
                items = []
                for i in range(f.get('max', 5)):
                    item = {sf['key']: form.get(f'{k}__{i}__{sf["key"]}', '').strip()[:4000] for sf in f['fields']}
                    if any(item.values()): items.append(item)
                out[k] = items
            elif t in ('file', 'files'):
                private = f.get('visibility') == 'private'
                current = list(existing_files.get(k, []))
                removed = set(form.getlist(k + '__remove'))
                current = [x for x in current if x['url'] not in removed]
                for fs in files.getlist(k):
                    if fs and fs.filename:
                        lab = f['label'].lower()
                        kinds = ('image', 'doc', 'video') if 'video' in lab else ('image',) if (f.get('role') == 'logo' or re.search(r'(logo|photo|photograph)', lab)) else ('image', 'doc')
                        saved = storage.save(fs, private=private, folder='registrations', kinds=kinds, allow_ext=f.get('accept'))
                        if t == 'file': current = [saved]
                        else: current.append(saved)
                fout[k] = current[:20]
            else:
                v = (form.get(k) or '').strip()
                limit = f.get('maxLength') or (6000 if t == 'textarea' else 500)
                if len(v) > limit: errs[k] = f'Please keep this to {limit:,} characters (currently {len(v):,}).'
                v = v[:limit]
                if v:
                    if t == 'email' and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', v): errs[k] = 'Enter a valid email address.'
                    elif t == 'tel' and not re.match(r'^[+\d][\d\s-]{7,15}$', v): errs[k] = 'Enter a valid phone number.'
                    elif t == 'pincode' and not re.match(r'^\d{6}$', v): errs[k] = 'PIN code must be 6 digits.'
                    elif t == 'year' and not (re.match(r'^\d{4}$', v) and 1800 <= int(v) <= 2100): errs[k] = 'Enter a 4-digit year.'
                    elif t == 'number' and not re.match(r'^\d+(\.\d+)?$', v.replace(',', '')): errs[k] = 'Enter a number.'
                    elif t == 'url':
                        if not re.match(r'^https?://', v): v = 'https://' + v
                        if not re.match(r'^https?://[^\s/$.?#].[^\s]*$', v): errs[k] = 'Enter a valid web address.'
                    elif t == 'date' and not re.match(r'^\d{4}-\d{2}-\d{2}$', v): errs[k] = 'Enter a valid date.'
                out[k] = v
        except storage.UploadError as e:
            errs[k] = str(e)
    return out, fout, errs

def visible(f, answers):
    """Conditional logic from the documents: equals / notEquals / in (one of) / includesAny (checkbox has any) /
    notEmpty / excludes (checkbox does not contain)."""
    cond = f.get('showIf')
    if not isinstance(cond, dict): return True
    v = answers.get(cond['field'])
    vals = v if isinstance(v, list) else ([v] if v else [])
    ok = True
    if 'equals' in cond: ok = ok and v == cond['equals']
    if 'notEquals' in cond: ok = ok and v != cond['notEquals']
    if 'in' in cond: ok = ok and v in cond['in']
    if 'includesAny' in cond: ok = ok and any(x in vals for x in cond['includesAny'])
    if cond.get('notEmpty'): ok = ok and bool(vals)
    if 'excludes' in cond: ok = ok and cond['excludes'] not in vals
    return ok

def missing_required(defn, answers, files, si=None):
    miss = {}
    for i, s, f in fields(defn):
        if si is not None and i != si: continue
        if not f.get('required') or f['type'] == 'heading': continue
        if not visible(s, answers) or not visible(f, answers): continue
        v = files.get(f['key']) if f['type'] in ('file', 'files') else answers.get(f['key'])
        if f['type'] in ('consent', 'boolean'):
            if not v: miss[f['key']] = 'Please confirm to continue.'
        elif is_empty(v):
            miss[f['key']] = 'This field is required.'
    return miss

def section_visible(sec, answers):
    return visible(sec, answers)

def progress(defn, answers, files):
    total = done = 0
    for _, s, f in fields(defn):
        if f['type'] in ('heading',): continue
        if not visible(s, answers): continue
        total += 1
        v = files.get(f['key']) if f['type'] in ('file', 'files') else answers.get(f['key'])
        if not is_empty(v) and v is not False: done += 1
    return int(100 * done / total) if total else 0

# ---------------- splitting & display ----------------
def split_private(defn, answers):
    pub, priv = {}, {}
    for _, _, f in fields(defn):
        if f['key'] not in answers: continue
        (priv if f.get('visibility') == 'private' else pub)[f['key']] = answers[f['key']]
    return pub, priv

def display_value(f, v):
    if is_empty(v): return None
    t = f['type']
    if t in ('checkbox',): return ', '.join(v)
    if t in ('boolean', 'consent'): return 'Yes' if v else None
    if t == 'matrix': return '; '.join(f"{r}: {', '.join(c)}" for r, c in v.items())
    if t == 'repeat': return v
    return v

def profile_sections(defn, answers, files, tiers=('public',)):
    """Sections/fields to show for given visibility tiers, skipping empties."""
    out = []
    for s in defn['sections']:
        if not visible(s, answers): continue
        items = []
        for f in s['fields']:
            if f.get('visibility', 'detailed') not in tiers or f['type'] in ('heading', 'consent'): continue
            if f.get('role') in ('name',): continue
            if f['type'] in ('file', 'files'):
                fl = [x for x in files.get(f['key'], []) if not x.get('private')]
                if fl: items.append({'field': f, 'files': fl})
                continue
            dv = display_value(f, answers.get(f['key']))
            if dv: items.append({'field': f, 'value': dv})
        if items: out.append({'title': s['title'], 'items': items})
    return out

def answer_by_role(defn, answers, role):
    f = field_by_role(defn, role)
    return answers.get(f['key']) if f else None

EDITABLE_AFTER_VERIFY = re.compile(r'(photo|video|gallery|virtual tour|principal|contact person|centre head|logo)', re.I)
def editable_after_verification(f):
    """Schools: once verified, only photos, videos, Principal name and Contact person name can change."""
    return bool(EDITABLE_AFTER_VERIFY.search(f['label'])) and f['type'] in ('file', 'files', 'text')

def filter_facets(defn):
    """checkbox/radio fields useful as directory filters (boards, grades, curriculum, activities...)."""
    want = re.compile(r'(board|curricul|grades offered|medium|co-ed|school type|type of institution|age group|programmes offered|services offered|subjects|activities|categor|delivery|mode)', re.I)
    out = []
    for _, s, f in fields(defn):
        if f['type'] in ('checkbox', 'radio') and f.get('visibility') != 'private' and want.search(f['label']) and f.get('options'):
            out.append(f)
    return out[:6]
