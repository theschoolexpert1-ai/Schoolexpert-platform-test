"""Parser for question-style forms: numbered question, optional type line, plain option lines."""
import re, json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from parse_forms import slugify, clean, infer_type, SINGLE_LABEL, RANGE_HINT, YN

SKIP = re.compile(r'^(A Unit of Poornaphala|Registered Address|#559|26th Cross|Bangalore - 560073|\[\]$|[-_=+|. …]+$|THE SCHOOL EXPERT™$)')
SEC = re.compile(r'^(?:SECTION|Section|PART|Part)\s*([A-Z0-9]+)\s*[—–:\-.]\s*(.+)$')
Q = re.compile(r'^(\d+)[.)]\s+(.+)$')
TYPEWORDS = r'(Short answer|Paragraph|Long answer|Multiple choice|Checkbox(?:es)?|Dropdown|Date|Time|File upload|Linear scale|Yes ?/ ?No|Number|Email|Phone|URL)'
TYPE = re.compile(r'^(?:Response:\s*|Field type:\s*|Answer type:\s*)?' + TYPEWORDS + r'(\s*(?:[—–+(/].*)?)$', re.I)

def parse(path, slug, title=None):
    raw = [l.rstrip('\n') for l in open(path, encoding='utf-8')]
    items = []
    for l in raw:
        l = clean(l)
        if not l or SKIP.match(l): continue
        mk = ''
        if l.startswith('# '): mk, l = 'num', l[2:].strip()
        elif l.startswith('- '): mk, l = 'bul', l[2:].strip()
        items.append((mk, l))
    form = {'slug': slug, 'title': title or '', 'intro': [], 'sections': [], 'outro': []}
    sec = None; q = None; used = set(); qnum = 0
    def close_q():
        nonlocal q
        if not q: return
        f = q
        opts = f.pop('_opts')
        t = f.pop('_t')
        label = f['label']
        other = False
        clean_opts = []
        for o in opts:
            o2 = re.sub(r'_{3,}', '', o).strip().rstrip(':').strip()
            if re.match(r'^(other|others)\b', o2, re.I) and len(o2) < 30:
                other = True; continue
            clean_opts.append(o2)
        tl = (t or '').lower()
        if tl.startswith('yes'):
            f['type'] = 'yesno'
        elif clean_opts or other:
            if len(clean_opts) == 1 and not other and len(clean_opts[0]) > 40:
                f['type'] = 'consent'; f['text'] = clean_opts[0]
            else:
                f['options'] = clean_opts
                if other: f['other'] = True
                if tl.startswith('checkbox'): f['type'] = 'checkbox'
                elif tl.startswith('multiple') : f['type'] = 'radio'
                elif tl.startswith('dropdown'): f['type'] = 'state' if re.search(r'\bstate', label, re.I) and len(clean_opts) > 25 else 'select'
                else:
                    if set(x.lower() for x in clean_opts) <= YN or (SINGLE_LABEL.search(label) and not re.search(r'\b(age|grade|services|areas)', label, re.I)) or (clean_opts and all(RANGE_HINT.search(x) for x in clean_opts) and not re.search(r'\b(age|grade|duration)', label, re.I)):
                        f['type'] = 'radio'
                    else: f['type'] = 'checkbox'
                if f['type'] == 'state': f.pop('options', None); f.pop('other', None)
        else:
            if tl.startswith('paragraph') or tl.startswith('long'): f['type'] = 'textarea'
            elif tl.startswith('date'): f['type'] = 'date'
            elif tl.startswith('file'): f['type'] = 'file'
            elif tl.startswith('dropdown'): f['type'] = 'state' if re.search(r'\bstate', label, re.I) else 'select'
            elif tl.startswith('checkbox'): f['type'] = 'consent'
            else: f['type'] = infer_type(label)
            if f['type'] == 'select' and not f.get('options'):
                f['type'] = 'text'
        if 'required' in tl and 'optional' not in tl.split('required')[0]: f['required'] = True
        if re.search(r'—\s*optional', tl): f['required'] = False
        sec['fields'].append(f); q = None
    def ensure_sec(title='General Information'):
        nonlocal sec
        if sec is None:
            sec = {'title': title, 'description': '', 'fields': []}; form['sections'].append(sec)
    for idx, (mk, l) in enumerate(items):
        if not form['title']:
            if re.search(r'(form|registration)', l, re.I):
                form['title'] = re.sub(r'\s*\(.*?\)\s*', ' ', l).strip(); continue
        m = SEC.match(l)
        if m and len(l) < 120:
            close_q(); sec = {'title': m.group(2).strip().title() if m.group(2).isupper() else m.group(2).strip(), 'description': '', 'fields': []}
            form['sections'].append(sec); continue
        if l in ('Question', 'Field type', 'Required', 'Form description', 'Conditional logic:', 'Allow:', 'PDF', 'JPG', 'PNG', 'If Yes:', 'If Yes →'): continue
        if l == '✅' and q is not None: q['required'] = True; continue
        if re.match(r'^(If |Recommended:|All others|Example:)', l) and q is not None:
            q['help'] = (q.get('help', '') + ' ' + l).strip(); continue
        msub = re.match(r'^(\d+[A-Z])\s*[—–-]\s*(.+)$', l)
        if msub:
            close_q(); sec = {'title': msub.group(2).strip(), 'description': '', 'fields': []}
            form['sections'].append(sec); continue
        mq = Q.match(l)
        nxt = items[idx + 1][1] if idx + 1 < len(items) else ''
        isq = bool(mq) or (mk == 'num' and not TYPE.match(l)) or (not TYPE.match(l) and bool(TYPE.match(nxt)) and not l.startswith('→'))
        if isq and not re.match(r'^\d+\s*[–-]', l):
            close_q(); ensure_sec()
            label = mq.group(2) if mq else l
            req = bool(re.search(r'\*\s*$', label)) or bool(re.search(r'\*\s*\(', label))
            label = re.sub(r'\s*\*+', '', label).strip().rstrip(':')
            tt = None
            mt2 = re.search(r'\s+(Checkboxes|Multiple choice|Short answer|Paragraph|Dropdown)(\s*[—–-].*)?$', label)
            if mt2: tt = mt2.group(1) + (mt2.group(2) or ''); label = label[:mt2.start()].strip()
            key = slugify(label); b = key; n = 2
            while key in used: key = f'{b}_{n}'; n += 1
            used.add(key)
            q = {'key': key, 'label': label, 'type': 'text', 'required': req, '_opts': [], '_t': tt}
            continue
        if q is not None:
            mt = TYPE.match(l)
            if mt and q['_t'] is None and not q['_opts']:
                q['_t'] = mt.group(1) + (mt.group(2) or ''); continue
            if re.match(r'^(Optional|Optional / where applicable)$', l, re.I):
                q['required'] = False; continue
            mshow = re.match(r'^Show if:\s*(.+)$', l, re.I)
            if mshow: q['showIf'] = mshow.group(1); continue
            if re.match(r'^(Accepted formats|Suggested format|Format|Note|Max|Hint|e\.g\.)', l, re.I) or l.startswith('→'):
                q['help'] = (q.get('help', '') + ' ' + l.lstrip('→ ')).strip(); continue
            if re.match(r'^(Select (all|any|up to)|Tick (all|any))', l, re.I):
                mm = re.search(r'up to (\d+)', l)
                if mm: q['maxSelect'] = int(mm.group(1))
                if q['_t'] is None: q['_t'] = 'Checkboxes'
                continue
            if l.startswith('«') or l.startswith('Thank you'):
                close_q(); form['outro'].append(l.strip('«»')); continue
            if len(l) > 160 and not q['_opts'] and q['_t'] and not q['_t'].lower().startswith('checkbox'):
                q['help'] = (q.get('help', '') + ' ' + l).strip(); continue
            q['_opts'].append(l.replace('☐', '').strip()); continue
        # free text
        if form['outro'] or l.startswith('«'):
            form['outro'].append(l.strip('«»')); continue
        if sec is None: form['intro'].append(l)
        else: sec['description'] = (sec['description'] + '\n' + l).strip()
    close_q()
    return form

if __name__ == '__main__':
    src, slug, out = sys.argv[1], sys.argv[2], sys.argv[3]
    f = parse(src, slug)
    json.dump(f, open(out, 'w'), indent=1, ensure_ascii=False)
