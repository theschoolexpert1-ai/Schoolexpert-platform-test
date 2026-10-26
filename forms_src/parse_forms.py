"""Convert extracted form lines into JSON form definitions (heuristic, then patched)."""
import re, json, sys, os

SKIP_RE = [r'^A Unit of Poornaphala', r'^Registered Address', r'^#559', r'^26th Cross', r'^Bangalore - 560073',
           r'^\[\]$', r'^[-_=+|. …]+$', r'^THE SCHOOL EXPERT™$', r'^Connect • Collaborate • Grow$']
HINT_RE = re.compile(r'^(Short answer|Paragraph|Long answer|Dropdown|Optional|Date|Number|File upload|Upload|Checkboxes|Multiple choice|Select up to (\d+).*|Select (all|any)[^.]*|Tick (all|any)[^.]*|Select one.*|Choose one.*|\(Select all that apply\)|\(Tick all that apply\))\.?:?$', re.I)
SECTION_RE = re.compile(r'^(SECTION|Section|PART|Part)\s*([A-Z0-9IVX]+)\s*[:—–\-.]?\s*(.*)$')
NUM_RE = re.compile(r'^(\d+(?:\.\d+)*)[.)]?\s+(.+)$')
BLANK_RE = re.compile(r'(_{3,}|…{2,}|\.{6,}|-{4,})')
YN = {'yes', 'no', 'maybe', 'not sure', 'yes/no'}

def slugify(s):
    s = re.sub(r'[^a-z0-9]+', '_', s.lower()).strip('_')
    return s[:48] or 'field'

def clean(s):
    s = s.replace(' ', ' ').strip()
    return re.sub(r'\s+', ' ', s)

def tokenize(lines):
    toks = []
    for raw in lines:
        l = clean(raw)
        if not l or any(re.search(p, l) for p in SKIP_RE):
            continue
        marker = ''
        if l.startswith('# '): marker, l = 'num', l[2:].strip()
        elif l.startswith('- ') or l.startswith('• ') or l.startswith('◦ '): marker, l = 'bul', l[2:].strip()
        if not l: continue
        if l.startswith('☐') or l.startswith('□') or l.startswith('○'):
            opts = [clean(o) for o in re.split(r'[☐□○]', l) if clean(o)]
            toks.append(('OPT', opts, marker)); continue
        mft = re.match(r'^Field type:\s*(.+)$', l, re.I)
        if mft: l = mft.group(1).strip()
        if HINT_RE.match(l):
            toks.append(('HINT', l, marker)); continue
        m = SECTION_RE.match(l)
        if m and (m.group(3) or '').strip() and len(l) < 110:
            toks.append(('SEC', clean(m.group(3)) or l, marker)); continue
        if '☐' in l or '□' in l:
            head, *rest = re.split(r'[☐□]', l)
            toks.append(('INLINE', (clean(head).rstrip(':').strip(), [clean(o) for o in rest if clean(o)]), marker)); continue
        num = NUM_RE.match(l)
        if num and not re.match(r'^\d+\s*[–-]\s*\d+', l):
            body = clean(num.group(2))
            depth = num.group(1).count('.')
            if body.isupper() and len(body) < 90 and depth == 0:
                toks.append(('SEC', body.title() if body.isupper() else body, 'num')); continue
            toks.append(('TEXT', body, 'num' if depth == 0 else 'sub')); continue
        if l.isupper() and len(l) < 80 and not BLANK_RE.search(l) and len(l.split()) > 1:
            toks.append(('SEC', l.title(), marker)); continue
        if BLANK_RE.search(l):
            toks.append(('BLANK', l, marker)); continue
        toks.append(('TEXT', l, marker))
    return toks

def strip_req(label):
    req = False
    label = label.strip()
    if re.search(r'\*+\s*$', label) or re.search(r'\*\s*\(', label):
        req = True
    label = re.sub(r'\*+', '', label).strip().rstrip(':').strip()
    return label, req

def option_list(opts):
    out, other = [], False
    for o in opts:
        o2 = BLANK_RE.sub('', o).strip().rstrip(':').strip()
        if re.match(r'^(other|others|any other|other \(please specify\)|any other\( ?please specify\)|other professional memberships)$', o2, re.I) or re.match(r'^other[: ]', o2, re.I) and BLANK_RE.search(o):
            other = True
            if o2.lower().startswith('other'):
                continue
        if o2: out.append(o2)
    return out, other

RANGE_HINT = re.compile(r'(less than|more than|below|above|\d+\s*[–-]\s*\d+|\d+\+|years?$|months?$)', re.I)
SINGLE_LABEL = re.compile(r'^(gender|highest|have you|are you|do you|does |is |would you|will you|can you|total .*experience|experience|years of|approximate|current employment status|co-educational|nature of|primary|preferred mode|how would you describe|how did you hear|age group$|annual turnover|organisation size|team size|number of)', re.I)

def infer_type(label, hint=None):
    l = label.lower()
    if hint:
        h = hint.lower()
        if h.startswith('paragraph') or h.startswith('long'): return 'textarea'
        if h.startswith('dropdown') and re.search(r'\bstate', l): return 'state'
        if h.startswith('date'): return 'date'
        if h.startswith('number'): return 'number'
        if h.startswith('file') or h.startswith('upload'): return 'file'
    if re.search(r'\b(state(/ut)?|state / ut)\b', l) and len(l) < 25: return 'state'
    if re.search(r'e-?mail', l): return 'email'
    if re.search(r'(mobile|phone|whatsapp|contact number|telephone)', l) and 'preferred' not in l: return 'tel'
    if re.search(r'(website|url|link|linkedin|facebook|instagram|youtube|twitter|portfolio|google business|blog|google maps)', l): return 'url'
    if re.search(r'(logo|photo|photograph|upload|\(pdf\)|prospectus|brochure|video tour|videos?$|resume|\bcv\b|certificate copy|signature|gallery|virtual tour|campus photos)', l): return 'file'
    if re.search(r'(pin code|pincode)', l): return 'pincode'
    if re.search(r'(year established|year of establishment|year of completion|year founded)', l): return 'year'
    if re.search(r'^(date|date of birth)$', l): return 'date'
    if re.search(r'(description box|describe|description|brief|summary|achievements|tell us|explain|what is one|what would|why do you|how do you|address$|highlights|methodology|recognition & certifications|approach)', l): return 'textarea'
    if re.search(r'\(yes ?/ ?no\)', l): return 'yesno'
    return 'text'

def build(path, slug):
    lines = open(path, encoding='utf-8').read().splitlines()
    toks = tokenize(lines)
    gform = any(t[0]=='HINT' and re.match(r'(short answer|paragraph|long answer)', t[1], re.I) for t in toks)
    if not gform:
        nt=[]
        for k,v,m in toks:
            if k=='TEXT' and m=='num' and len(v)<70 and not v.endswith('?') and not v.endswith('*'):
                nt.append(('SEC',v,m))
            elif k=='TEXT' and re.match(r'^\(.*\)$', v):
                nt.append(('DESC',v,m))
            else: nt.append((k,v,m))
        toks=nt
    form = {'slug': slug, 'title': '', 'intro': [], 'sections': []}
    sec = None
    used = set()
    def new_sec(title):
        nonlocal sec
        sec = {'title': title, 'description': '', 'fields': []}
        form['sections'].append(sec)
    def add_field(label, ftype='text', options=None, other=False, required=False, max_select=None, help=None):
        nonlocal sec
        if sec is None: new_sec('General Information')
        label, req2 = strip_req(label)
        required = required or req2
        if not label: return
        m = re.search(r'\((?:…|\.)+\s*description box\s*(?:…|\.)+\)', label, re.I)
        if m or 'Description Box' in label:
            label = re.sub(r'\(.*description box.*\)', '', label, flags=re.I).strip(); ftype = 'textarea'
        if re.search(r'\(yes ?/ ?no\)', label, re.I):
            label = re.sub(r'\s*\(yes ?/ ?no\)', '', label, flags=re.I); ftype = 'yesno'
        key = slugify(label); base = key; n = 2
        while key in used: key = f'{base}_{n}'; n += 1
        used.add(key)
        f = {'key': key, 'label': label, 'type': ftype, 'required': required}
        if options is not None: f['options'] = options
        if other: f['other'] = True
        if max_select: f['maxSelect'] = max_select
        if help: f['help'] = help
        sec['fields'].append(f)
        return f
    i = 0
    title_done = False
    while i < len(toks):
        kind, val, mk = toks[i]
        nxt = toks[i + 1] if i + 1 < len(toks) else (None, None, None)
        if not title_done and kind in ('TEXT', 'SEC') and re.search(r'(form|registration|profile)', str(val), re.I):
            form['title'] = clean(re.sub(r'\(.*?\)', '', val)) if len(val) < 140 else val; title_done = True; i += 1; continue
        if kind == 'SEC':
            new_sec(re.sub(r'\s+', ' ', val).strip(' :–—-').strip()); i += 1; continue
        if kind == 'BLANK':
            lab = BLANK_RE.sub('', val).strip()
            unit = None
            mm = re.search(r'\b(years?|months?|%)\s*$', lab)
            if mm and lab.endswith(mm.group(1)):
                unit = mm.group(1); lab = lab[: -len(unit)].strip()
            if lab:
                f = add_field(lab, 'number' if unit else infer_type(lab))
                if unit and f: f['unit'] = unit
            i += 1; continue
        if kind == 'INLINE':
            lab, opts = val
            o, other = option_list(opts)
            if lab:
                t = 'radio' if (set(x.lower() for x in o) <= YN or SINGLE_LABEL.search(lab)) else 'checkbox'
                add_field(lab, t, o, other)
            else:
                # inline options continuing previous field
                if sec and sec['fields'] and 'options' in sec['fields'][-1]:
                    sec['fields'][-1]['options'] += o
                else:
                    add_field(sec['title'] if sec else 'Options', 'checkbox', o, other)
            i += 1; continue
        if kind == 'OPT':
            # options with no label -> belong to section
            opts = []
            while i < len(toks) and toks[i][0] == 'OPT':
                opts += toks[i][1]; i += 1
            o, other = option_list(opts)
            if sec and sec['fields'] and sec['fields'][-1].get('_open'):
                sec['fields'][-1]['options'] += o
            else:
                add_field(sec['title'] if sec else 'Options', 'checkbox', o, other)
            continue
        if kind == 'HINT':
            i += 1; continue
        if kind == 'DESC':
            if sec: sec['description'] = (sec['description'] + ' ' + val.strip('()')).strip()
            i += 1; continue
        # TEXT
        label = val
        if len(label) > 120 or re.match(r'^(Please|Note|This|The School Expert|Because|Student Ambassadors|If you|All information|By submitting|Programme note|I hereby|I confirm|I declare|I understand|I agree|I consent)', label):
            target = sec if sec else form
            if sec is None:
                form['intro'].append(label)
            else:
                sec['description'] = (sec['description'] + '\n' + label).strip()
            i += 1; continue
        # look ahead
        j = i + 1; hint = None; max_sel = None; optional = False
        while j < len(toks) and toks[j][0] == 'HINT':
            h = toks[j][1]
            mm = re.match(r'select up to (\d+)', h, re.I)
            if mm: max_sel = int(mm.group(1))
            elif h.lower().startswith('optional'): optional = True
            else: hint = h
            j += 1
        nk = toks[j][0] if j < len(toks) else None
        if nk == 'OPT':
            opts = []
            while j < len(toks) and toks[j][0] == 'OPT':
                opts += toks[j][1]; j += 1
            o, other = option_list(opts)
            lab = strip_req(label)[0]
            t = 'radio' if (set(x.lower() for x in o) <= YN or SINGLE_LABEL.search(lab) or (o and all(RANGE_HINT.search(x) for x in o))) else 'checkbox'
            if re.search(r'\b(age|grade|stage|class)', lab, re.I) and not re.search(r'experience', lab, re.I) and len(o) > 2: t = 'checkbox'
            if hint and re.match(r'(select one|choose one|multiple choice)', hint, re.I): t = 'radio'
            add_field(label, t, o, other, max_select=max_sel)
            i = j; continue
        if gform and nk == 'TEXT' and mk == 'num' and toks[j][2] == 'bul':
            # numbered question followed by bullet options (google-form style single select)
            opts = []
            while j < len(toks) and toks[j][0] == 'TEXT' and toks[j][2] == 'bul':
                opts.append(toks[j][1]); j += 1
            o, other = option_list(opts)
            add_field(label, 'radio', o, other)
            i = j; continue
        if hint or optional:
            f = add_field(label, infer_type(strip_req(label)[0], hint))
            i = j; continue
        # subheading? short label followed by blanks/bullets of fields
        if nk in ('BLANK',) and not label.endswith(':') and mk != 'num' and len(label) < 60 and not BLANK_RE.search(label):
            new_sec_title = strip_req(label)[0]
            req = strip_req(label)[1]
            add_field(new_sec_title, 'heading', required=req)
            i += 1; continue
        if mk == '' and nk == 'TEXT' and toks[j][2] == 'bul' and len(label) < 50 and not label.endswith(':') and not label.endswith('?'):
            add_field(strip_req(label)[0], 'heading', required=strip_req(label)[1])
            i += 1; continue
        add_field(label, infer_type(strip_req(label)[0], hint))
        i += 1
    # cleanup: drop empty sections, mark single-option checkbox etc
    form['sections'] = [s for s in form['sections'] if s['fields'] or s['description']]
    for s in form['sections']:
        for f in s['fields']:
            f.pop('_open', None)
            if f['type'] == 'checkbox' and f.get('options') and len(f['options']) == 1 and not f.get('other'):
                f['type'] = 'boolean'; f['label'] = f['options'][0] if f['label'] == s['title'] else f['label']; f.pop('options')
    return form

if __name__ == '__main__':
    mapping = json.load(open(sys.argv[1]))
    out = sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for fname, slug in mapping.items():
        form = build(fname, slug)
        json.dump(form, open(os.path.join(out, slug + '.json'), 'w'), indent=1, ensure_ascii=False)
