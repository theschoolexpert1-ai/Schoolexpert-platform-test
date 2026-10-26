"""Compare a Google Form extraction (forms_src/google_forms/<slug>.txt) with the live form definition.

Reports, per Google-Form question: missing questions, missing answer choices, and required-flag differences.
Usage: python forms_src/audit/compare_gf.py <slug> [<slug> ...]
"""
import json, os, re, sys, difflib
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
norm = lambda t: re.sub(r'[^a-z0-9]+', ' ', (t or '').lower().replace('&', 'and')).strip()

def parse(path):
    qs, sec = [], None
    for line in open(path, encoding='utf-8'):
        line = line.rstrip('\n')
        if line.startswith('## '): sec = line[3:]
        elif line.startswith('Q|'):
            _, label, typ, req = (line.split('|') + [''] * 4)[:4]
            qs.append(dict(section=sec, label=label, type=typ, required=req == 'req', options=[]))
        elif line.startswith('- ') and qs: qs[-1]['options'].append(line[2:])
    return qs

def fields(d):
    for s in d['sections']:
        for f in s['fields']:
            yield s, f

def match(q, d):
    """Best field for a Google-Form question: by label, or by section title for unlabeled checkbox lists."""
    nq, best = norm(q['label']), (0, None)
    for s, f in fields(d):
        score = difflib.SequenceMatcher(None, nq, norm(f['label'])).ratio()
        if norm(f['label']) == nq: score = 2
        if norm(s['title']) == norm(q['section']) or norm(q['section']) in norm(s['title']): score += 0.3   # same section wins ties
        if q['options'] and f.get('options'):
            have = {norm(o) for o in f['options']}
            score += sum(norm(o) in have for o in q['options']) / len(q['options'])
        if score > best[0]: best = (score, f)
    return best

def compare(slug):
    d = json.load(open(os.path.join(ROOT, 'tse', 'forms', slug + '.json'), encoding='utf-8'))
    labels = {norm(f['label']) for _, f in fields(d)}
    out = []
    for q in parse(os.path.join(ROOT, 'forms_src', 'google_forms', slug + '.txt')):
        score, f = match(q, d)
        if score < 0.75 and not q['options']:
            out.append(('missing question', q['section'], q['label'], '')); continue
        if q['options']:
            have = {norm(o) for o in (f.get('options') or [])} if f else set()
            miss = [o for o in q['options'] if norm(o) not in have and not norm(o).startswith('other')
                    and norm(o) not in labels]                               # docx may model a choice as its own field
            if miss: out.append(('missing choices', q['section'], q['label'], '; '.join(miss)))
            if f is None or score < 0.6: out.append(('missing question', q['section'], q['label'], ''))
        if f is not None and q['required'] and not f.get('required') and score >= 1.3:
            out.append(('not required here', q['section'], q['label'], f['key']))
    return out

if __name__ == '__main__':
    for slug in sys.argv[1:]:
        res = compare(slug)
        print(f'\n### {slug}: {len(res)} difference(s)')
        for kind, sec, label, extra in res: print(f'  [{kind}] {sec} › {label}' + (f'  → {extra}' if extra else ''))
