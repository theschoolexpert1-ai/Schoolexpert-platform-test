"""Merge parsed + hand-written forms, clean up, add category metadata and DPDP visibility tiers."""
import json, re, os, sys, copy
sys.path.insert(0, os.path.dirname(__file__))
from parse_forms import slugify

SRC = {
 # slug: source dir
 'alternative-school': 'forms_raw', 'preschool': 'forms_raw', 'special-school': 'forms_raw',
 'individual-online-tutor-registration': 'forms_raw',
 'teacher-training-institute-registration': 'forms_q', 'educational-consultant-registration': 'forms_q',
 'online-tutoring-support-provider-institution-registration': 'forms_q', 'recreation-hobbies-enrichment-provider': 'forms_q',
 'parent-ambassador': 'forms_q', 'student-ambassador': 'forms_q', 'principal-roundtable-virtual': 'forms_q',
}
for fn in os.listdir('forms_dsl'):
    SRC[fn[:-5]] = 'forms_dsl'

# category, label shown in directory, entity kind, who sees it
META = {
 'school-registration':      ('schools', 'Schools', 'organisation'),
 'alternative-school':       ('schools', 'Alternative Schools', 'organisation'),
 'inclusive-school':         ('schools', 'Inclusive Schools', 'organisation'),
 'preschool':                ('schools', 'Nursery / Preschools', 'organisation'),
 'special-school':           ('schools', 'Special Schools', 'organisation'),
 'online-school-registration': ('schools', 'Online Schools', 'organisation'),
 'edtech-company':           ('vendors', 'EdTech Companies', 'organisation'),
 'educational-publisher':    ('vendors', 'Educational Publishers', 'organisation'),
 'infrastructure-vendor':    ('vendors', 'School Infrastructure Vendors', 'organisation'),
 'transport-logistics':      ('vendors', 'Transportation & Logistics', 'organisation'),
 'uniform-vendor':           ('vendors', 'Uniform, Badge, Bag & Stationery', 'organisation'),
 'fee-financing':            ('experts', 'Fee Financing Companies', 'organisation'),
 'course-provider':          ('learning', 'K-12 Course Providers', 'organisation'),
 'online-tutoring-support-provider-institution-registration': ('learning', 'Online Tutoring Institutions', 'organisation'),
 'individual-online-tutor-registration': ('learning', 'Individual Online Tutors', 'individual'),
 'recreation-hobbies-enrichment-provider': ('learning', 'Hobby & Enrichment Classes', 'organisation'),
 'skill-development':        ('learning', 'Skill Development Institutes', 'organisation'),
 'teacher-training-institute-registration': ('learning', 'Teacher Training Institutes', 'organisation'),
 'educational-consultant-registration': ('learning', 'Education Consultants', 'individual'),
 'behaviour-consultant':     ('experts', 'Behaviour Consultants & Therapists', 'organisation'),
 'career-guidance':          ('experts', 'Career Guidance & Counselling', 'organisation'),
 'mental-health':            ('experts', 'Mental Health Professionals', 'organisation'),
 'special-educator-registration': ('experts', 'Special Educators', 'individual'),
 'k12-curriculum-development-expert-registration': ('experts', 'Curriculum Development Experts', 'individual'),
 'teacher-registration':     ('teachers', 'Teachers', 'individual'),
 'parent-ambassador':        ('ambassadors', 'Parent Ambassadors', 'individual'),
 'student-ambassador':       ('ambassadors', 'Student Ambassadors', 'minor'),
 'principal-roundtable-virtual': ('events', 'Principals Virtual Roundtable', 'individual'),
 'principal-roundtable-delegate': ('events', 'Principal Roundtables – Delegate', 'individual'),
}
ORDER = list(META.keys())

PRIVATE = re.compile(r'(date of birth|^dob|^age$|gender|\bpan\b|gstin|gst (number|registration|certificate)|\bcin\b|llpin|registration number|business registration|aadhaar|signature|declaration|consent|confirm|agree|salary|alternate|alternative contact|reference|referee|how did you hear|internal|verification|verify|willing to undergo|background verified|proof of|parent / guardian|relationship to student|student email|student mobile|organisation registration|registration certificate|qualification certificate|experience certificate|experience letters|certificate\(s\)|rci / crr certificate|instructor credentials|supporting documents|registration / gst|permits|why would you like|partnership / collaboration proposal|partnership interest|features that you would like|services$|the school expert™ services|would you like to|are you interested|would you be interested|do you agree|best time to contact|preferred method of communication|preferred contact method|anything else|additional comments|additional information|notice period|expected|open to new|willing to relocate|profile visibility|community guidelines|upload cv)', re.I)
PUBLIC = re.compile(r'^(school name|school / preschool name|school / centre name|institution name|name of online school|company name|vendor / company name|brand|brand name|brand / trade name|brand / platform name|brand / chain name|provider / organisation name|provider name|organisation name|organisation / practice name|publisher / organisation name|name of organisation|organisation / academy|preferred name|full name|professional headline|professional title|school logo|institution logo|logo|company logo|school / institution logo|organisation / institute logo|logo / profile photo|profile photograph|photograph / profile photo|school motto|tagline|motto|year established|school type|school category|type of institution|organisation type|provider type|practice type|type of provider|affiliated boards|board|recognition & registration|grades offered|co-ed|co-educational|city|current city|district|state|state/ut|state / union territory|city / state|age groups|programmes offered|business category|categories|product categories|what do you publish|activities|what type of activities|services offered|subjects you teach|areas of specialisation|type of educational consultant|what type of training|skill areas|concerns|professional categories|services\*?|primary subject|total teaching experience|years of experience|medium of instruction|languages offered|languages of instruction)', re.I)

def walk(form):
    for s in form['sections']:
        for f in s['fields']:
            yield s, f

def postprocess(form):
    # 1. checkbox lists hidden in section descriptions
    for s in form['sections']:
        d = s.get('description') or ''
        if '☐' not in d: continue
        lines = d.split('\n'); keep = []; opts = []; lead = None
        for l in lines:
            if l.startswith('☐'): opts.append(l.lstrip('☐ ').strip())
            else:
                if opts: break
                keep.append(l)
        if not opts: continue
        rest_idx = len(keep) + len(opts)
        tail = lines[rest_idx:]
        new = []
        if all(len(o) > 55 or o.lower().startswith('i ') for o in opts):
            for i, o in enumerate(opts):
                new.append({'key': slugify(o)[:40] + f'_{i}', 'label': 'I agree' if o.lower() == 'i agree' else 'Acknowledgement', 'type': 'consent', 'text': o, 'required': True})
            new = [n for n in new if n['text'].lower() != 'i agree'] or new
        else:
            lead = next((l for l in reversed(keep) if l and not l.lower().startswith('select')), s['title'])
            new.append({'key': slugify(s['title']), 'label': s['title'] if lead.lower().startswith('select') else s['title'], 'type': 'checkbox', 'options': [o for o in opts if not o.lower().startswith('other')], 'other': any(o.lower().startswith('other') for o in opts), 'required': False})
        s['fields'] = new + s['fields']
        s['description'] = '\n'.join([k for k in keep if not k.lower().startswith('select all')] + tail).strip()
    # 2. options that are actually consent statements or trailing junk
    for s, f in walk(form):
        if f.get('options'):
            junk = [o for o in f['options'] if o.isupper() and len(o) > 12]
            if junk:
                idx = f['options'].index(junk[0])
                form.setdefault('outro', []).extend(f['options'][idx:])
                f['options'] = f['options'][:idx]
                if not f['options']:
                    f['type'] = 'textarea'; f.pop('options'); f.pop('other', None)
        if f.get('options') and f['type'] in ('checkbox', 'radio') and all(len(o) > 55 or o.lower().startswith('i ') for o in f['options']):
            f['type'] = 'consent'; f['text'] = ' '.join(f['options']); f.pop('options'); f.pop('other', None)
        if '(optional)' in f['label'].lower():
            f['label'] = re.sub(r'\s*\(optional\)', '', f['label'], flags=re.I); f['required'] = False
        if f['type'] == 'select' and re.search(r'\bstate\b', f['label'], re.I) and len(f.get('options', [])) > 15:
            f['type'] = 'state'; f.pop('options', None); f.pop('other', None)
    # 3. wet signatures + manual dates -> replaced by e-consent (timestamped automatically)
    for s in form['sections']:
        s['fields'] = [f for f in s['fields'] if not re.search(r'signature', f['label'], re.I) and not (f['label'].lower() == 'date' and f['type'] in ('date', 'consent', 'text'))]
    form['sections'] = [s for s in form['sections'] if s['fields'] or s.get('description')]

def patch(slug, form):
    def find(label_re):
        for s, f in walk(form):
            if re.search(label_re, f['label'], re.I): return f
    if slug == 'student-ambassador':
        f = find(r'parent / guardian email'); f.update(type='email'); f.pop('options', None)
        sec = form['sections'][-1]
        sec['fields'].append({'key': 'guardian_consent', 'label': 'Parent / Guardian consent', 'type': 'consent', 'required': True,
            'text': 'I am the parent / lawful guardian of the student named above. I have read and understood the Student Ambassador programme details, role boundaries and the Privacy Policy, and I give verifiable consent for The School Expert™ to process the information in this form only for the Student Ambassador programme.'})
        for s, f in walk(form):
            if f['label'].lower() in ('age',): f['type'] = 'number'
        sd = form['sections'][0]
        sd['fields'] = [f for f in sd['fields'] if f['label'].lower() != 'date of birth']  # data minimisation: age band is enough
        form['intro'].insert(0, 'For students aged 14 to 18 years. This form must be completed by, or with, a parent or lawful guardian, who verifies consent by OTP before submission.')
    if slug == 'principal-roundtable-virtual':
        f = find(r'^designation$'); f['type'] = 'radio'
        f = find(r'which areas would you most like'); f['maxSelect'] = 3
        f = find(r'any additional comments');
        if f: f.update(type='textarea'); f.pop('options', None)
    if slug == 'recreation-hobbies-enrichment-provider':
        for s in form['sections']:
            for f in list(s['fields']):
                if f['label'] == 'Optional' and f.get('options'):
                    f.update(label='Email Address', type='email', key='email_address'); f.pop('options'); f.pop('other', None)
                if f['label'] == 'WhatsApp':
                    s['fields'].remove(f)
                if f['label'] == 'Preferred method of communication':
                    f.update(type='radio', options=['WhatsApp', 'Phone', 'Email'])
                if f['label'].startswith('Is a trial'):
                    f['options'] = ['Yes – Free', 'Yes – Paid', 'No']
                if f['label'] == 'Years of Experience':
                    f.update(type='radio', options=['Less than 1 year', '1–3 years', '3–5 years', '5–10 years', '10+ years'])
                if f['label'] == 'Primary Area of Expertise':
                    f.update(type='text')
        sec = next(s for s in form['sections'] if s['title'] == 'Fees')
        i = next(i for i, f in enumerate(sec['fields']) if f['label'].startswith('Is a trial'))
        sec['fields'].insert(i + 1, {'key': 'trial_class_fee', 'label': 'Trial Class Fee', 'type': 'text', 'required': False, 'help': 'If the trial class is paid'})
        sec['fields'].append({'key': 'admission_registration_fee', 'label': 'Admission / Registration Fee', 'type': 'text', 'required': False, 'help': 'If applicable'})
        loc = next(s for s in form['sections'] if s['title'] == 'Location')
        loc['fields'].append({'key': 'list_the_locations', 'label': 'List the locations', 'type': 'textarea', 'required': False, 'help': 'If you offer classes in multiple locations'})
        for s in form['sections']:
            if s['title'] in ('Individual Instructor', 'Organisation / Centre'):
                s['showIf'] = {'field': 'what_type_of_provider_are_you', 'equals' if s['title'].startswith('Individual') else 'notEquals': 'Individual Instructor / Coach'}
        f = find(r'Number of instructors')
        if not f:
            sec = next(s for s in form['sections'] if s['title'].startswith('Instructor'))
            sec['fields'].insert(0, {'key': 'number_of_instructors_coaches', 'label': 'Number of instructors / coaches', 'type': 'number', 'required': True})
    if slug == 'educational-consultant-registration':
        f = find(r'Highest Educational Qualification')
        f.update(type='radio', options=['Diploma', 'Graduate', 'Postgraduate', 'M.Phil.', 'Ph.D.', 'Professional Qualification'], other=True)
    if slug == 'teacher-training-institute-registration':
        f = find(r'Key Trainers'); f.update(type='textarea', help='Suggested format: Name – Qualification – Experience – Area of Expertise'); f.pop('text', None)
        f = find(r'NCTE Recognition Number'); f['showIf'] = {'field': 'does_your_organisation_have_ncte_recognition', 'equals': 'Yes'}
    if slug == 'online-tutoring-support-provider-institution-registration':
        f = find(r'^State$');
        if f: f['type'] = 'state'; f.pop('options', None); f.pop('other', None)
        form['title'] = 'Online Tutoring Support Provider Registration Form (Institution)'
    if slug == 'parent-ambassador':
        f = find(r'^anything else')
        if f: f.update(type='textarea'); f.pop('options', None)
    if slug in ('preschool',):
        for s, f in walk(form):
            if s['title'] in ('School Timings',) : f['type'] = 'text'
            if s['title'] == 'Admissions' and f['type'] == 'text': f['type'] = 'yesno'
            if s['title'] == 'Daycare Facilities' and f['label'] == 'If Yes': f['label'] = '_drop'
            if s['title'] == 'Media Uploads': f['type'] = 'file' if f['label'] in ('School Logo', 'Video Tour', 'Prospectus (PDF)') else 'files'
        for s in form['sections']:
            s['fields'] = [f for f in s['fields'] if f['label'] != '_drop']
            if s['title'] == 'Daycare Facilities':
                for f in s['fields']:
                    if f['type'] == 'boolean': f.update(label='Daycare Available', type='yesno')
    if slug == 'special-school':
        for s, f in walk(form):
            if s['title'] == 'Admissions': f['type'] = 'yesno'
            if s['title'] == 'Media Uploads': f['type'] = 'file' if f['label'] in ('School Logo', 'Prospectus (PDF)') else 'files'
            if f['label'].startswith('(Aligned'):
                f['label'] = 'Disability Categories Served'; f['help'] = 'Aligned with the Rights of Persons with Disabilities (RPwD) Act, 2016'
    if slug == 'alternative-school':
        for s, f in walk(form):
            if s['title'] in ('Digital Presence',) and f['label'] in ('Gallery', 'Prospectus', 'Virtual Tour'):
                f['type'] = 'files' if f['label'] == 'Gallery' else 'file'
    if slug == 'individual-online-tutor-registration':
        f = find(r'Date of Birth / Age Group')
        if f: f.update(label='Age Group', type='radio', options=['18–25', '26–35', '36–45', '46–60', '60+'])
        f = find(r'Do you provide any specialised academic support')
        if f: f['type'] = 'checkbox'
    # fix titles
    form['title'] = re.sub(r'^The School Expert™\s*[-–—]\s*', '', form['title']).replace(' (India)', '').strip()
    if form['title'].isupper(): form['title'] = form['title'].title().replace("'S", "'s")

FEE_FINANCING = {
 'slug': 'fee-financing', 'title': 'Fee Financing Company Registration', 'provisional': 'New category referenced in the parent journey; no source form was provided.',
 'intro': [], 'outro': [], 'sections': [
  {'title': 'Company', 'description': '', 'fields': [
   {'key': 'company_name', 'label': 'Company Name', 'type': 'text', 'required': True},
   {'key': 'brand_name', 'label': 'Brand Name', 'type': 'text', 'required': False},
   {'key': 'legal_entity_name', 'label': 'Legal Entity Name', 'type': 'text', 'required': True},
   {'key': 'regulatory_status', 'label': 'Regulatory Status', 'type': 'radio', 'required': True, 'options': ['RBI-registered NBFC', 'Bank', 'Partner of an RBI-regulated lender (LSP)', 'Other']},
   {'key': 'rbi_registration_number', 'label': 'RBI Registration / CoR Number', 'type': 'text', 'required': True},
   {'key': 'logo', 'label': 'Logo', 'type': 'file', 'required': False},
   {'key': 'about', 'label': 'About', 'type': 'textarea', 'required': True}]},
  {'title': 'Contact', 'description': '', 'fields': [
   {'key': 'contact_person', 'label': 'Contact Person', 'type': 'text', 'required': True},
   {'key': 'mobile_number', 'label': 'Mobile Number', 'type': 'tel', 'required': True},
   {'key': 'email', 'label': 'Email', 'type': 'email', 'required': True},
   {'key': 'website', 'label': 'Website', 'type': 'url', 'required': True},
   {'key': 'city', 'label': 'City', 'type': 'text', 'required': True},
   {'key': 'state', 'label': 'State', 'type': 'state', 'required': True}]},
  {'title': 'Products', 'description': '', 'fields': [
   {'key': 'products', 'label': 'Products', 'type': 'checkbox', 'required': True, 'options': ['Zero-cost EMI on school fees', 'Interest-bearing fee loans', 'Fee payment platform for schools', 'Scholarship / CSR fee support', 'Working-capital finance for schools']},
   {'key': 'interest_range', 'label': 'Interest / APR Range Disclosed to Parents', 'type': 'text', 'required': True},
   {'key': 'grievance_officer', 'label': 'Grievance Redressal Officer (name & email)', 'type': 'text', 'required': True},
   {'key': 'cities_served', 'label': 'Cities Served', 'type': 'text', 'required': False}]},
  {'title': 'Declaration', 'description': '', 'fields': [
   {'key': 'declaration', 'label': 'Declaration', 'type': 'consent', 'required': True, 'text': 'I confirm the information is accurate, that all lending is by an RBI-regulated entity, and agree to verification by The School Expert™.'}]}]}

def visibility(f, entity):
    l = f['label']
    if f['type'] in ('consent', 'heading'): return 'private'
    if PRIVATE.search(l): return 'private'
    if entity in ('individual', 'minor') and f['type'] in ('tel', 'email', 'date'): return 'private'
    if entity in ('individual', 'minor') and re.search(r'address|pin code', l, re.I): return 'private'
    if entity == 'minor': return 'private'
    if f['type'] in ('file', 'files') and re.search(r'(certificate|document|credential|registration|permit|pan|gst|cv|resume)', l, re.I): return 'private'
    if PUBLIC.search(l.strip()): return 'public'
    return 'detailed'

def main():
    out = 'app/forms'; os.makedirs(out, exist_ok=True)
    index = []
    for slug in ORDER:
        if slug == 'fee-financing': form = copy.deepcopy(FEE_FINANCING)
        else:
            form = json.load(open(os.path.join(SRC[slug], slug + '.json')))
            postprocess(form); patch(slug, form)
        cat, label, entity = META[slug]
        form.update(category=cat, label=label, entity=entity)
        for s, f in walk(form):
            f['visibility'] = visibility(f, entity)
            if f['type'] == 'repeat':
                f['visibility'] = 'private' if re.search(r'reference', f['label'], re.I) else 'detailed'
        # guarantee a display-name field
        ROLES = [
          ('name', r'^(school name|school / preschool name|school / centre name|institution name|name of online school|company name|vendor / company name|provider / organisation name|provider name|organisation name|organisation / practice name|publisher / organisation name|name of organisation|organisation / academy / centre name|full name)', ('text',)),
          ('name2', r'^(full name)$', ('text',)),
          ('logo', r'(logo|profile photograph|photograph / profile photo|profile photo)', ('file',)),
          ('city', r'^(city|current city|city / state)$', ('text',)),
          ('state', r'^(state|state/ut|state / union territory)$', ('state',)),
          ('email', r'(admissions email|school email|organisation email|official email|company email|business email|^email|email address)', ('email',)),
          ('phone', r'(phone|mobile|contact number)', ('tel',)),
          ('whatsapp', r'whatsapp', ('tel',)),
          ('website', r'^(website|organisation website|website / platform url)', ('url',)),
          ('about', r'(^about|company profile|provider description|brief description of your solution|briefly describe your programmes|about me|curriculum highlights|professional biography|describe your professional expertise|please describe your primary areas)', ('textarea',)),
          ('headline', r'(professional headline|school motto|tagline|motto)', ('text',)),
        ]
        taken = set()
        for role, rx, types in ROLES:
            for s2, f2 in walk(form):
                if role in taken: break
                if f2['type'] in types and re.search(rx, f2['label'], re.I) and not f2.get('role'):
                    if role == 'name2':
                        if 'name' in taken: break
                        role = 'name'
                    f2['role'] = role; taken.add(role)
        if 'name' not in taken:
            f2 = next(f for _, f in walk(form) if f['type'] == 'text'); f2['role'] = 'name'
        for _, f2 in walk(form):
            if f2.get('role') in ('name', 'logo', 'city', 'state', 'headline') and entity != 'minor': f2['visibility'] = 'public'
            if entity == 'minor': f2['visibility'] = 'private'
        json.dump(form, open(os.path.join(out, slug + '.json'), 'w'), indent=1, ensure_ascii=False)
        n = sum(1 for _ in walk(form))
        index.append({'slug': slug, 'title': form['title'], 'category': cat, 'label': label, 'entity': entity, 'fields': n, 'provisional': bool(form.get('provisional'))})
    json.dump(index, open(os.path.join(out, '_index.json'), 'w'), indent=1, ensure_ascii=False)
    for i in index: print(f"{i['category']:12} {i['slug']:62} {i['fields']:3} {'PROVISIONAL' if i['provisional'] else ''}")

main()
