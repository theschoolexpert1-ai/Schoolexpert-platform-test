"""Strict fidelity audit. Option lines (☐ / '-' bullets / ';' lists) must exist as real options;
question lines must match a field label, section title/description, help or intro text."""
import subprocess, json, re, sys, glob, difflib
sys.path.insert(0, '/home/claude/app')
from tse.lib.forms import INDIAN_STATES
MAP = __import__('json').load(open(__import__('os').path.join(__import__('os').path.dirname(__file__), 'map.json')))
SRC = '/home/claude/app/forms_src'
norm = lambda t: re.sub(r'[^a-z0-9]+', ' ', (t or '').lower().replace('&', 'and')).strip()
STATES = {norm(x) for x in INDIAN_STATES} | {norm('Andaman & Nicobar Islands'), norm('Dadra & Nagar Haveli and Daman & Diu'), norm('Jammu & Kashmir')}
NOISE = re.compile(r'^(response|field type|answer type|google form type|short answer|long answer|paragraph|dropdown|checkboxes|checkbox|multiple choice|file upload|date|yes no|yes|no|other|others|linear scale|signature.*|full name|reviewer|date registered|expert registration id|show if.*|optional.*|required|conditional|a unit of poornaphala.*|559 sanjeevini|26th cross.*|bangalore 560073|the school expert( tm)?|page \d+|select all.*|select up to \d+|select one|multiple selection|use multi select|tick all.*|please tick.*|if yes|if no|url|email|phone|question|allow|form description|conditional logic|\d{4} \d{4}|pdf|jpg|png|docx)$')
def build(form):
    labels, opts = [], set()
    def add(t): t = norm(t); t and labels.append(t)
    for k in ('title', 'label'): add(form.get(k))
    for x in form.get('intro', []) + form.get('outro', []): add(x)
    for s in form['sections']:
        add(s.get('title')); add(s.get('description'))
        for f in s['fields']:
            add(f.get('label')); add(f.get('help')); add(f.get('placeholder'))
            for o in f.get('options') or []: opts.add(norm(o))
            if f.get('type') in ('consent', 'boolean'): opts.add(norm(f.get('text') or f.get('label')))
            for o in (f.get('rows') or []) + (f.get('columns') or []): opts.add(norm(o)); add(o)
            for sf in f.get('fields') or []: add(sf.get('label')); opts.add(norm(sf.get('label')))
    return labels, opts
def label_hit(t, labels):
    if t in labels: return True
    for l in labels:
        if len(t) >= 10 and (t in l or (len(l) >= 10 and l in t)): return True
    return max((difflib.SequenceMatcher(None, t, l).ratio() for l in labels), default=0) >= 0.86
out = {}
for path in sorted(glob.glob(SRC + '/original_uploads/*.docx')):
    slug = next((v for k, v in MAP.items() if k in path), None)
    if not slug: continue
    lines = subprocess.run([sys.executable, SRC + '/docx2lines.py', path], capture_output=True, text=True).stdout.splitlines()
    form = json.load(open(f'/home/claude/app/tse/forms/{slug}.json')); labels, opts = build(form)
    miss = []; internal = False
    for raw in lines:
        if re.search(r'internal (use|crm|field)|for the school expert\W+internal', raw, re.I): internal = True
        if internal: continue
        r = re.sub(r'^\s*(#\s*)?(Q\s*)?\d{1,3}(\.\d+)*[.)]?\s+', '', raw)
        r = re.sub(r'[_…\.]{3,}.*$', '', r).strip(' :*')
        if re.match(r'^(response|field type|answer type|registered address|# ?(short answer|paragraph|dropdown|file upload|checkboxes|multiple choice))\b', r, re.I): continue
        if not r: continue
        is_opt = '☐' in r or r.startswith('- ') or ';' in r
        parts = [p for p in re.split(r'☐|;|^- ', r) if norm(p)] if is_opt else [r]
        for p in parts:
            p = re.sub(r'\((please )?specify\)|please specify|\(description box\)', '', p, flags=re.I)
            p = re.sub(r':.*$', '', p) if is_opt and re.match(r'^\s*other', p, re.I) else p
            n = norm(p)
            if len(n) < 2 or NOISE.match(n) or n in STATES: continue
            if is_opt:
                n2 = re.sub(r'\b(yes no|yes|no)$', '', n).strip()
                if n in opts or n2 in opts or any(len(n) > 25 and (n in o or o in n) for o in opts if len(o) > 25): continue
                if n in labels or n2 in labels or max((difflib.SequenceMatcher(None, n2, l).ratio() for l in labels), default=0) >= 0.9: continue
                if any(l.startswith(n2 + ' ') or n2.startswith(l + ' ') for l in labels if len(l) >= 6 and len(n2) >= 6): continue
                if re.match(r'^(any )?other\b', n): continue
                miss.append(('OPTION', p.strip()[:110]))
            else:
                if n in opts or label_hit(n, labels): continue
                miss.append(('TEXT', p.strip()[:110]))
    out[slug] = miss
    print(f'\n### {slug}: {len(miss)}')
    for k, m in miss: print(f'   {k:6} {m}')
