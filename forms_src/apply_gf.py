"""Bring a live form in line with its Google Form (forms_src/google_forms/<slug>.txt).

For forms that also have a Word document, the Word version stays the base (it often captures more, e.g. actual fee
amounts instead of "we have a registration fee" ticks). From the Google Form we take:
  * required flags  (the Word documents rarely mark them; the Google Form is what applicants see today)
  * answer choices the Word version lacks
  * questions the Word version lacks (added to the matching section)
For forms without a Word document, the Google Form is the whole source: python forms_src/apply_gf.py --build <slug>

Every change is written to forms_src/google_forms/<slug>.changes.txt
"""
import json, os, re, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'audit'))
from compare_gf import parse, match, norm, fields

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TYPE = {'text': 'text', 'paragraph': 'textarea', 'radio': 'radio', 'checkbox': 'checkbox', 'dropdown': 'select', 'file': 'files',
        'date': 'date', 'email': 'email', 'tel': 'tel', 'url': 'url', 'number': 'number', 'scale': 'radio', 'yesno': 'yesno', 'state': 'state'}

def keyify(label, used):
    k = re.sub(r'[^a-z0-9]+', '_', label.lower()).strip('_')[:45] or 'q'
    base, n = k, 2
    while k in used: k = f'{base}_{n}'; n += 1
    used.add(k); return k

def guess_type(q):
    t = TYPE.get(q['type'], 'text'); lab = q['label'].lower()
    if t == 'text':
        if 'email' in lab: return 'email'
        if re.search(r'phone|mobile|whatsapp|contact number', lab): return 'tel'
        if re.search(r'website|url|link|linkedin|profile link', lab): return 'url'
        if re.search(r'\bpin ?code\b|pincode', lab): return 'pincode'
        if re.search(r'year (established|of establishment|founded)', lab): return 'year'
        if lab.strip() in ('state', 'state / ut', 'state/ut'): return 'state'
    return t

def clean_options(opts):
    other = any(norm(o) in ('other', 'others') or norm(o).startswith('other ') and len(norm(o)) < 20 for o in opts)
    return [o for o in opts if not (norm(o) in ('other', 'others') or (norm(o).startswith('other ') and len(norm(o)) < 20))], other

def merge(slug):
    path = os.path.join(ROOT, 'tse', 'forms', slug + '.json')
    d = json.load(open(path, encoding='utf-8'))
    used = {f['key'] for _, f in fields(d)}
    labels = {norm(f['label']) for _, f in fields(d)}
    log = []
    for q in parse(os.path.join(ROOT, 'forms_src', 'google_forms', slug + '.txt')):
        score, f = match(q, d)
        opts, other = clean_options(q['options'])
        modelled_as_fields = opts and all(norm(o) in labels for o in opts)
        if modelled_as_fields:
            continue                                   # the Word form asks for each item's value as its own question
        if f is None or (score < 1.0 and not (opts and f.get('options') and score >= 1.2)):
            sec = next((s for s in d['sections'] if norm(s['title']) == norm(q['section'])), None)
            if sec is None:
                sec = dict(title=q['section'], description='', fields=[]); d['sections'].append(sec)
            nf = dict(key=keyify(q['label'], used), label=q['label'], type=guess_type(q), required=q['required'], visibility='detailed')
            if opts: nf['options'] = opts
            if other: nf['other'] = True
            sec['fields'].append(nf); labels.add(norm(q['label']))
            log.append(f"added question  {q['section']} › {q['label']}")
            continue
        if opts and f.get('options') is not None:
            have = {norm(o) for o in f['options']}
            add = [o for o in opts if norm(o) not in have]
            if add:
                f['options'] = f['options'] + add
                log.append(f"added choices   {f['label']}: {'; '.join(add)}")
            if other and not f.get('other'):
                f['other'] = True; log.append(f"added “Other”   {f['label']}")
        if q['required'] and not f.get('required') and f['type'] not in ('heading',):
            f['required'] = True; log.append(f"now required    {f['label']}")
    json.dump(d, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(os.path.join(ROOT, 'forms_src', 'google_forms', slug + '.changes.txt'), 'w', encoding='utf-8').write('\n'.join(log) + '\n')
    return log

if __name__ == '__main__':
    for slug in sys.argv[1:]:
        log = merge(slug); print(f'{slug}: {len(log)} change(s)'); [print('  ' + l) for l in log]
