"""Compact form DSL -> JSON.

@slug x / @title / @intro text / @def NAME = a; b; c
## Section title
> description line
Label* | type | options (; separated, $NAME expands, 'Other' -> other input) | help
types: text textarea email tel url file files number year date state pincode yesno radio checkbox select boolean consent heading matrix repeat
matrix: options = rows ; help slot = 'cols: A, B, C'
repeat N: options = 'sub label:type, sub label:type'
"""
import re, json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from parse_forms import slugify

def parse(text):
    form = {'slug': '', 'title': '', 'intro': [], 'sections': [], 'outro': []}
    defs = {}
    sec = None; used = set()
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.strip().startswith('//'): continue
        if line.startswith('@def '):
            k, v = line[5:].split('=', 1); defs[k.strip()] = v.strip(); continue
        if line.startswith('@'):
            k, _, v = line[1:].partition(' ')
            if k in ('intro', 'outro'): form[k].append(v.strip())
            else: form[k] = v.strip()
            continue
        if line.startswith('## '):
            sec = {'title': line[3:].strip(), 'description': '', 'fields': []}
            form['sections'].append(sec); used_local = set(); continue
        if line.startswith('> '):
            sec['description'] = (sec['description'] + '\n' + line[2:].strip()).strip(); continue
        parts = [p.strip() for p in line.split(' | ')]
        label = parts[0]; ftype = parts[1] if len(parts) > 1 else 'text'
        opts = parts[2] if len(parts) > 2 else ''
        help_ = parts[3] if len(parts) > 3 else ''
        req = label.endswith('*')
        label = label.rstrip('*').strip()
        key = slugify(label); b = key; n = 2
        while key in used: key = f'{b}_{n}'; n += 1
        used.add(key)
        f = {'key': key, 'label': label, 'type': ftype, 'required': req}
        mrep = re.match(r'repeat\s*(\d+)', ftype)
        if mrep:
            f['type'] = 'repeat'; f['max'] = int(mrep.group(1))
            subs = []
            for s in opts.split(','):
                s = s.strip();
                if not s: continue
                sl, _, st = s.partition(':')
                subs.append({'key': slugify(sl), 'label': sl.strip(), 'type': (st or 'text').strip()})
            f['fields'] = subs; opts = ''
        if opts:
            def expand(o):
                o = o.strip()
                return defs[o[1:]].split(';') if o.startswith('$') else [o]
            ol = [x.strip() for o in opts.split(';') for x in expand(o) if x.strip()]
            other = False; clean = []
            for o in ol:
                if re.match(r'^(other|any other|others)(\b.*)?$', o, re.I) and len(o) < 32: other = True
                else: clean.append(o)
            if ftype == 'matrix': f['rows'] = clean + (['Other'] if other else [])
            else:
                f['options'] = clean
                if other: f['other'] = True
        if help_:
            if ftype == 'matrix' and help_.startswith('cols:'):
                f['columns'] = [c.strip() for c in help_[5:].split(',')]
            elif ftype == 'consent': f['text'] = help_
            elif help_.startswith('max:'): f['maxSelect'] = int(help_[4:])
            else: f['help'] = help_
        if ftype == 'consent' and not f.get('text'): f['text'] = label
        sec['fields'].append(f)
    return form

if __name__ == '__main__':
    src_dir, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    for fn in sorted(os.listdir(src_dir)):
        if not fn.endswith('.form'): continue
        common = open(os.path.join(src_dir, 'common.defs'), encoding='utf-8').read()
        form = parse(common + '\n' + open(os.path.join(src_dir, fn), encoding='utf-8').read())
        json.dump(form, open(os.path.join(out, form['slug'] + '.json'), 'w'), indent=1, ensure_ascii=False)
        print('ok', form['slug'], sum(len(s['fields']) for s in form['sections']), 'fields')
