"""Per-question audit: each question in the document followed by an option list must map to one field
that carries every option (order-insensitive)."""
import subprocess, json, re, sys, glob, difflib
MAP = json.load(open(__import__('os').path.join(__import__('os').path.dirname(__file__), 'map.json'))); SRC = '/home/claude/app/forms_src'
norm = lambda t: re.sub(r'[^a-z0-9]+', ' ', (t or '').lower().replace('&', 'and')).strip()
SKIP = re.compile(r'^(response|field type|answer type|short answer|long answer|paragraph|dropdown|checkboxes|multiple choice|file upload|select all.*|select up to.*|required|optional|.*— (required|optional)|multiple selection|use multi select|if yes|conditional logic.*|example.*|e g .*)$')
def clean_opt(o):
    o = re.sub(r'^[\-☐•\s]+', '', o); o = re.sub(r'[_…]{3,}.*$', '', o); o = re.sub(r'\((please )?specify\)', '', o, flags=re.I)
    return o.strip(' :')
def groups(lines):
    q = None; opts = []; out = []
    for raw in lines + ['<END>']:
        r = re.sub(r'^\s*(#\s*)?(Q\s*)?\d{1,3}(\.\d+)*[.)]?\s+', '', raw).strip()
        is_opt = raw.lstrip().startswith(('- ', '☐')) or (r.count('☐') >= 2)
        if is_opt:
            parts = [clean_opt(p) for p in (re.split('☐', r) if '☐' in r else [r])]
            opts += [p for p in parts if norm(p)]
            continue
        if SKIP.match(norm(r)) and r != '<END>': continue
        if q and len(opts) >= 2: out.append((q, opts))
        q, opts = r, []
    return out
def fields(form):
    for s in form['sections']:
        for f in s['fields']:
            yield s, f
total = 0
for path in sorted(glob.glob(SRC + '/original_uploads/*.docx')):
    slug = next((v for k, v in MAP.items() if k in path), None)
    if not slug: continue
    lines = subprocess.run([sys.executable, SRC + '/docx2lines.py', path], capture_output=True, text=True).stdout.splitlines()
    form = json.load(open(f'/home/claude/app/tse/forms/{slug}.json'))
    fl = list(fields(form)); probs = []
    for q, opts in groups(lines):
        nq = norm(q)
        if re.search(r'internal (use|crm)|internal verification|engagement status|profile classification|recommended lead status', nq): continue
        cand = []
        for s, f in fl:
            lab = norm(f.get('label'))
            score = difflib.SequenceMatcher(None, nq, lab).ratio()
            if lab and (lab in nq or nq in lab): score = max(score, .9)
            fo = {norm(o) for o in (f.get('options') or []) + (f.get('rows') or []) + (f.get('columns') or [])}
            hit = sum(1 for o in opts if norm(o) in fo)
            cand.append((score + hit / max(len(opts), 1), f, fo, s))
        # also: sections whose title matches and whose fields are the options (bullets = sub-fields)
        best = max(cand, key=lambda c: c[0]) if cand else None
        if not best: continue
        _, f, fo, s = best
        if not fo:   # bullets were sub-fields of a section, check labels
            labs = {norm(x.get('label')) for _, x in fl}
            missing = [o for o in opts if norm(o) not in labs and not any(norm(o) in l or l in norm(o) for l in labs if len(l) > 4)]
        else:
            missing = [o for o in opts if norm(o) not in fo and not re.match(r'^(other|others|any other)\b', norm(o))
                       and not (norm(o) in ('yes', 'no'))]
        if missing:
            probs.append((q[:70], f['key'][:40], missing))
    total += len(probs)
    if probs:
        print(f'\n### {slug}: {len(probs)} questions with missing options')
        for q, k, m in probs: print(f'   Q: {q}  -> field {k}\n      missing: {m[:12]}{" …" if len(m) > 12 else ""}')
print('\nTOTAL', total)
