"""Fidelity corrections found by the document audit (forms_src/audit/*.py).

Run from the project root:  python forms_src/fixes.py
Every change below restores wording/options exactly as written in your uploaded .docx forms.
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS = os.path.join(ROOT, 'tse', 'forms')
UP = os.path.join(ROOT, 'forms_src', 'original_uploads')

def load(slug): return json.load(open(os.path.join(FORMS, slug + '.json'), encoding='utf-8'))
def save(slug, d): json.dump(d, open(os.path.join(FORMS, slug + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
def find(d, key):
    for s in d['sections']:
        for i, f in enumerate(s['fields']):
            if f['key'] == key: return s, i, f
    raise KeyError(key)
def section(d, title_part):
    return next(s for s in d['sections'] if title_part.lower() in s['title'].lower())
def slugify(t): return re.sub(r'[^a-z0-9]+', '_', t.lower()).strip('_')[:40]
def consent(key, label, text, required=True):
    return dict(key=key, label=label, type='consent', required=required, text=text, visibility='private')
def doc_lines(name_part):
    path = next(os.path.join(UP, f) for f in os.listdir(UP) if name_part in f)
    return subprocess.run([sys.executable, os.path.join(ROOT, 'forms_src', 'docx2lines.py'), path], capture_output=True, text=True).stdout.splitlines()

# ---------------------------------------------------------------- 1. generic: '| text' pseudo-options
def fix_pipe_help(d):
    for s in d['sections']:
        for f in s['fields']:
            o = f.get('options') or []
            if o and all(isinstance(x, str) and x.startswith('|') for x in o[:1]):
                txt = ', '.join(x.lstrip('| ').strip() for x in o)
                f.pop('options', None)
                if f['type'] in ('consent', 'boolean'):
                    f['type'] = 'consent'; f['text'] = txt
                else:
                    f['help'] = (f.get('help', '') + ' ' + txt).strip()
                    m = re.search(r'max\s*([\d,]+)\s*characters', txt, re.I)
                    if m: f['maxLength'] = int(m.group(1).replace(',', ''))
                    m = re.search(r'\b(PDF|JPG|PNG|DOCX|PPT)\b', txt)
                    if m and f['type'] in ('file', 'files'):
                        f['accept'] = [x.lower() for x in re.findall(r'PDF|JPG|PNG|DOCX|PPTX?|DOC', txt)]
    d['outro'] = [x for x in d.get('outro', []) if not str(x).startswith('|')]
    return d

# ---------------------------------------------------------------- 2. Course Providers — rebuilt from the specification table
def build_course_provider():
    L = doc_lines('Course_Providers')
    i = L.index('CRM / Database Column') + 1
    rows = []
    while i + 4 < len(L) and not L[i].startswith('Recommended Course-Level'):
        rows.append(L[i:i + 5]); i += 5
    TYPE = {'Short answer': 'text', 'Paragraph': 'textarea', 'Dropdown': 'radio', 'Checkboxes': 'checkbox', 'Multiple choice': 'radio', 'File upload': 'file'}
    PUBLIC = {'provider_name', 'brand_name', 'provider_type', 'year_established', 'city_state', 'logo_url', 'provider_description', 'course_name',
              'course_categories', 'course_short_description', 'course_level', 'target_learners', 'age_range', 'school_boards', 'delivery_mode',
              'geographic_availability', 'languages_offered', 'certificate_provided'}
    PRIVATE = {'legal_entity_name', 'registration_document', 'pan_document', 'gst_document', 'declaration_accepted', 'contact_name', 'contact_designation'}
    ROLE = {'provider_name': 'name', 'logo_url': 'logo', 'city_state': 'city', 'business_email': 'email', 'phone_whatsapp': 'phone',
            'website': 'website', 'provider_description': 'about', 'course_short_description': 'headline'}
    SECTIONS = [('Provider Details', 'provider_name', 'contact_designation'), ('Course Details', 'course_name', 'education_alignment'),
                ('Delivery', 'course_duration', 'languages_offered'), ('Assessment & Certification', 'assessment_methods', 'accreditation_affiliation'),
                ('Faculty', 'instructor_count', 'instructor_student_ratio'), ('Schools & Pricing', 'school_programme_options', 'scholarship_availability'),
                ('Documents', 'course_brochure', 'gst_document'), ('Partnership & Declaration', 'partnership_interests', 'declaration_accepted')]
    fields = []
    for label, gtype, req, opts, col in rows:
        f = dict(key=col, label=label, type=TYPE.get(gtype, 'text'), required=(req == 'Yes'))
        if col == 'year_established': f.update(type='year', help='Year between 1900 and 2026')
        elif col in ('website',): f['type'] = 'url'
        elif col == 'business_email': f['type'] = 'email'
        elif col == 'phone_whatsapp': f['type'] = 'tel'
        elif col == 'session_count': f['type'] = 'number'
        elif col == 'declaration_accepted':
            f.update(type='consent', text='I confirm that: the information is accurate; I am the authorised representative; course content and credentials are accurately represented; and I agree to The School Expert™ verification and listing terms.')
        elif ';' in opts:
            items = [x.strip() for x in opts.split(';') if x.strip()]
            if items[-1] == 'Other': items = items[:-1]; f['other'] = True
            f['options'] = items
        elif opts not in ('—', '', 'URL', 'Email', 'Phone', 'Conditional'):
            f['help'] = opts
            m = re.search(r'Max ([\d,]+) characters', opts)
            if m: f['maxLength'] = int(m.group(1).replace(',', ''))
            if f['type'] == 'file': f['accept'] = [x.lower() for x in re.findall(r'PDF|JPG|PNG|DOCX|PPT', opts)]
        if col == 'logo_url': f['accept'] = ['jpg', 'png']
        if gtype == 'Short answer' and req == 'Conditional':
            f['required'] = False; f['showIf'] = {'field': 'certificate_provided', 'in': ['Yes', 'Optional']}
        if col == 'accreditation_affiliation': f['showIf'] = {'field': 'certificate_provided', 'in': ['Yes', 'Optional']}
        if col in ('progress_reporting',): f['showIf'] = {'field': 'assessment_methods', 'notEmpty': True, 'excludes': 'No Formal Assessment'}
        if col in ('school_experience',): f['showIf'] = {'field': 'school_programme_options', 'notEmpty': True}
        if col == 'geographic_availability': f['help'] = 'For in-person delivery, where you serve; for online delivery, choose International / Online.'
        f['visibility'] = 'public' if col in PUBLIC else 'private' if col in PRIVATE else 'detailed'
        if col in ROLE: f['role'] = ROLE[col]
        fields.append(f)
    keys = [f['key'] for f in fields]
    secs = []
    for title, a, b in SECTIONS:
        secs.append(dict(title=title, description='', fields=fields[keys.index(a): keys.index(b) + 1]))
    secs[1]['description'] = 'Describe one course here. After submitting, use “Add another course” on your dashboard — each course gets its own Course ID and public listing; your provider details are copied automatically.'
    d = dict(slug='course-provider', title='K–12 Individual Course Providers — Registration Form', category='learning', label='K-12 Course Providers', entity='organisation',
             intro=['Designed for providers offering individual courses to K–12 students, parents, teachers or schools in India. The structure allows one provider account to register multiple courses, with each course receiving a separate Course ID and public listing.'],
             outro=[], sections=secs, multi_record={'shared_sections': ['Provider Details'], 'record_label': 'course', 'id_prefix': 'TSE-C'},
             internal={'id_label': 'Provider ID / Course ID',
                       'checks': ['Organisation registration verified', 'PAN verified', 'GST verified (if applicable)', 'Credentials verified', 'Course content reviewed', 'Contact details verified'],
                       'fields': [('credential_verification_status', 'Credential Verification Status', ['Pending', 'In progress', 'Verified', 'Not verified']),
                                  ('listing_status', 'Listing Status', ['Draft', 'Pending', 'Active', 'Paused', 'Removed']),
                                  ('lead_status', 'Lead Status', ['New', 'Contacted', 'Course Details Requested', 'Credentials Requested', 'Verification Pending', 'Verified',
                                                                  'Listing Active', 'Premium Prospect', 'Converted', 'Not Interested', 'Rejected', 'Duplicate']),
                                  ('lead_score', 'Lead Score', None), ('assigned_salesperson', 'Assigned Salesperson', None),
                                  ('last_contacted', 'Last Contacted', 'date'), ('next_followup', 'Next Follow-up', 'date')]})
    save('course-provider', d)

# ---------------------------------------------------------------- 3. document-exact corrections
def fix_k12(d):
    _, _, f = find(d, 'boards_curricula_with_professional_experience')
    f['options'] = ['CBSE', 'CISCE – ICSE/ISC', 'NIOS', 'Karnataka State Board', 'Maharashtra State Board', 'Tamil Nadu State Board', 'Kerala State Board',
                    'Telangana State Board', 'Andhra Pradesh State Board', 'Delhi Government School Curriculum', 'Gujarat State Board', 'Rajasthan State Board',
                    'Uttar Pradesh State Board', 'West Bengal State Board']
    f['other'] = True; f['otherLabel'] = 'Other State/UT Board'
    f['help'] = 'Please select the boards/curricula with which you have professional experience.'
    _, _, p = find(d, 'projects')
    p['help'] = 'Please provide details of your three to five most significant projects.'; p['max'] = 5
    sub = [x for x in p['fields'] if x['key'] != 'scope_and_deliverables']
    idx = next(i for i, x in enumerate(sub) if 'role' in x['key'])
    sub[idx + 1:idx + 1] = [dict(key='scope_of_work', label='Scope of Work', type='textarea'), dict(key='key_deliverables', label='Key Deliverables', type='textarea')]
    p['fields'] = sub
    for k, t in [('accuracy', 'I confirm that the information provided in this registration form is accurate and complete to the best of my knowledge.'),
                 ('no_commitment', 'I understand that submission of this form does not automatically constitute empanelment, appointment, certification, or a commitment of work by The School Expert.'),
                 ('review_authorisation', 'I authorize The School Expert to review the information and supporting documents provided for the purpose of assessing my professional profile and suitability for relevant education and curriculum development assignments.')]:
        _, _, c = find(d, k); c.update(type='consent', text=t); c.pop('options', None)
    sec = section(d, 'Declaration')
    sec['fields'].append(dict(key='e_signature', label='Signature (type your full name)', type='text', required=True, visibility='private',
                              help='Your typed name is your electronic signature; the date is recorded automatically.'))
    _, _, m = find(d, 'languages_in_which_you_can_independently_work')
    m['help'] = 'Please indicate languages in which you can independently: develop curriculum/content (Develop), review academic content (Review), conduct training and facilitate workshops (Train/Facilitate).'
    d['internal'] = {'id_label': 'Expert Registration ID',
                     'checks': ['CV verified', 'Qualifications verified', 'Experience verified', 'Portfolio reviewed', 'References checked', 'Interview conducted', 'Sample task/review completed'],
                     'classification': ['Curriculum Specialist', 'Subject Matter Expert', 'Assessment Specialist', 'Pedagogy Specialist', 'Instructional Designer',
                                        'Textbook/Content Specialist', 'Teacher Education Specialist', 'Research Specialist', 'Academic Reviewer', 'Education Consultant', 'Other'],
                     'tags': ['Stage', 'Subject', 'Board', 'State/Region', 'Language', 'Specialization'],
                     'statuses': ['Registered', 'Under Review', 'Verified Expert', 'Empanelled', 'Project-Specific Expert', 'Inactive'],
                     'fields': [('reviewer', 'Reviewer', None), ('review_date', 'Date', 'date')]}
    return d

def fix_publisher(d):
    _, _, f = find(d, 'curriculum_boards')
    f['options'] = ['CBSE', 'CISCE / ICSE / ISC', 'State Boards', 'NIOS', 'IB', 'Cambridge', 'IGCSE', 'Montessori', 'Waldorf / Steiner',
                    'International Curriculum', 'NEP 2020 aligned', 'NCF-SE aligned']
    f['other'] = True
    _, _, r = find(d, 'recognition_credentials')
    if 'ISBN Registration / Publisher Details' not in r['options']: r['options'].insert(0, 'ISBN Registration / Publisher Details')
    return d

def fix_virtual_roundtable(d):
    s, i, f = find(d, 'recording_consent')
    s['fields'][i] = dict(key='recording_consent', label='Recording Consent', type='radio', required=True, visibility='private',
                          options=['I consent to the session being recorded for internal documentation / educational purposes.',
                                   'I do not consent to recording of my participation.'])
    s, i, f = find(d, 'how_did_you_hear_about_the_school_expert_princip')
    f['label'] = 'How did you hear about The School Expert™ Principals Virtual Roundtable?'
    f['options'] = ['The School Expert™', 'LinkedIn', 'WhatsApp', 'Email', 'Referral from another Principal', 'School / Education Network']; f['other'] = True
    s['fields'] = [x for x in s['fields'] if x['key'] != 'whatsapp']
    d['outro'] = ['Thank you for registering for The School Expert™ Principals Virtual Roundtable.',
                  'Your registration will be reviewed and the meeting details will be shared with confirmed participants.']
    return d

def fix_delegate(d):
    d['outro'] = ['The session link and calendar invite will be sent to your registered email before the session.']
    return d

def fix_recreation(d):
    s, i, f = find(d, 'additional_information_you_d_like_us_to_know')
    s['fields'][i] = dict(key=f['key'], label=f['label'], type='textarea', required=False, visibility='private')
    _, _, t = find(d, 'trial_class_fee'); t['showIf'] = {'field': 'is_a_trial_demo_class_available', 'equals': 'Yes – Paid'}; t['help'] = ''
    _, _, q = find(d, 'is_a_trial_demo_class_available'); q.pop('help', None)
    _, _, a = find(d, 'admission_registration_fee'); a['showIf'] = {'field': 'is_there_an_admission_registration_fee', 'equals': 'Yes'}; a['help'] = ''
    _, _, u = find(d, 'upload_supporting_documents'); u['accept'] = ['pdf', 'jpg', 'png']; u['help'] = 'Allowed: PDF, JPG, PNG'
    d['outro'] = ['Thank you for registering with The School Expert™!', 'Your information has been received successfully.',
                  'Our team may contact you if additional information or verification is required.',
                  "We look forward to connecting you with parents, schools and opportunities across India's education ecosystem."]
    return d

def fix_individual_tutor(d):
    s = section(d, 'DECLARATION')
    s['title'] = 'Declaration & Consent'
    s['description'] = ('I confirm that the information provided in this registration form is true and accurate to the best of my knowledge. I understand that '
                        'registration with The School Expert™ does not automatically constitute endorsement, accreditation, certification or approval of my services. '
                        'I authorise The School Expert™ to verify information and documents submitted by me for registration and verification purposes.')
    s['fields'] = [consent('declaration_consent', 'Declaration', 'I agree to the above declaration.'),
                   consent('privacy_consent', 'Privacy Consent', 'I consent to The School Expert™ collecting, storing and using the information submitted through this form for registration, verification, communication, directory listing and partnership-related purposes, subject to its applicable privacy policy.'),
                   consent('profile_listing_consent', 'Profile Listing Consent', "I consent to my professional profile being displayed to parents, students, schools and other authorised users if I am approved for listing in The School Expert™'s tutor directory.", required=False),
                   consent('final_confirmation', 'Final Confirmation', 'I confirm that I am submitting this application voluntarily and that the information provided is accurate.')]
    # "Date of Birth / Age Group": collected as an age group only (data minimisation; tutors are adults)
    first = d['sections'][0]
    if not any(f['key'] == 'age_group' for f in first['fields']):
        pos = next((i for i, f in enumerate(first['fields']) if f['key'].startswith('mobile')), len(first['fields']))
        first['fields'].insert(pos, dict(key='age_group', label='Age Group', type='radio', required=True, visibility='private',
                                         options=['18–24', '25–34', '35–44', '45–54', '55–64', '65+'],
                                         help='Your form asks for “Date of Birth / Age Group”; we collect the age group only, to keep personal data to the minimum.'))
    return d

def fix_online_tutoring(d):
    s = section(d, 'Declaration')
    s['description'] = ('I confirm that the information provided in this registration form is true and accurate to the best of my knowledge. I understand that '
                        'registration with The School Expert™ does not automatically constitute endorsement, accreditation, certification or approval of the services '
                        'offered by the applicant. The School Expert™ reserves the right to verify the information submitted and to accept, reject or request additional '
                        'information as part of its registration and verification process.')
    s['fields'] = [consent('declaration', 'Declaration', 'I agree to the above declaration.'),
                   consent('privacy_consent', 'Privacy Consent', 'I consent to The School Expert™ storing and using the information submitted through this form for registration, verification, communication and partnership-related purposes, subject to its applicable privacy policy.'),
                   consent('final_confirmation', 'Final Confirmation', 'I confirm that I am authorised to submit this registration on behalf of the organisation/provider.')]
    return d

def fix_educational_consultant(d):
    for k, label in [('consent_to_profile_listing', 'Consent to Profile Listing'), ('consent_to_communication', 'Consent to Communication')]:
        s, i, f = find(d, k)
        s['fields'][i] = dict(key=k, label=label, type='radio', required=True, visibility='private', help=f.get('text'), options=['I Agree', 'I Do Not Agree'])
    _, _, c = find(d, 'final_confirmation'); c['required'] = True
    d['outro'] = ['Thank you for registering with The School Expert™.', 'Your registration has been received successfully.',
                  'Our team may review and verify the information provided before your profile is activated or published.',
                  'For queries or collaboration opportunities, contact info@schoolexpert.in.']
    return d

def fix_student_ambassador(d):
    rec = section(d, 'Recognition')
    rec['description'] = ('Student Ambassador recognition: Students selected for the programme will be recognised by The School Expert™ as Student Ambassadors and may '
                          'receive a digital / formal recognition such as an Ambassador badge, certificate or feature, subject to the programme guidelines.')
    rec['fields'] = [dict(key='recognition_preference', label='Recognition preference', type='radio', required=True, visibility='private',
                          options=['I would be happy to be recognised publicly as a Student Ambassador.', 'I would prefer limited / private recognition.'],
                          help='Programme note: Student Ambassadors do not act as employees or official spokespersons of The School Expert™ unless separately authorised. They should not make commitments, promises or statements on behalf of the organisation.')]
    decl = section(d, 'Student Declaration')
    if not any(f['key'] == 'student_e_signature' for f in decl['fields']):
        decl['fields'].append(dict(key='student_e_signature', label='Student signature (type full name)', type='text', required=True, visibility='private',
                                   help='Typed name = electronic signature; the date is recorded automatically.'))
    g = section(d, 'Parent / Guardian')
    g['description'] = 'Because this programme is for students aged 14–18, a parent or legal guardian should review and consent to participation before the student takes part in activities or events.'
    texts = ['I have read and understood the Student Ambassador programme description and consent to the student participating in the voluntary programme.',
             'I understand that specific events or activities may have additional requirements and may require separate consent.',
             'I understand that the student may be invited to provide feedback, volunteer at appropriate events, participate in student discussions, or contribute to student-focused content, subject to applicable consent and safeguarding requirements.',
             'I understand that participation is voluntary and may be discontinued at any time by the student, parent/guardian or The School Expert™.']
    keep = [f for f in g['fields'] if not f['key'].startswith('guardian_decl_') and f['key'] not in ('guardian_e_signature',)]
    gi = next(i for i, f in enumerate(keep) if f['key'] == 'guardian_consent')
    keep[gi:gi] = [consent(f'guardian_decl_{n}', 'Consent declaration', t) for n, t in enumerate(texts)]
    keep.append(dict(key='guardian_e_signature', label='Parent / Guardian signature (type full name)', type='text', required=True, visibility='private',
                     help='Typed name = electronic signature; confirmed by the OTP sent to the parent / guardian mobile.'))
    g['fields'] = keep
    return d

def fix_preschool(d):
    _, _, f = find(d, 'daycare_facilities')
    for s in d['sections']:
        if s['title'] == 'Daycare Facilities':
            for x in s['fields']:
                if x['key'] != 'daycare_facilities': x['showIf'] = {'field': 'daycare_facilities', 'equals': 'Yes'}
    return d

def fix_parent_ambassador(d):
    want = ['Spread awareness about The School Expert™', 'Introduce other parents to our community',
            'Share The School Expert™ through reels, posts, WhatsApp and word-of-mouth', 'Refer schools to The School Expert™ and introduce us to school management',
            'Help parents discover schools, education providers, courses, experts and services', 'Share parent feedback, ideas and local education insights']
    intro = d.get('intro', [])
    if not any('Spread awareness' in x for x in intro):
        intro.append('As a Parent Ambassador you can: ' + '; '.join(want) + '.')
    d['intro'] = intro
    return d

def fix_inclusive_and_school(d):
    _, _, f = find(d, 'co_ed_boys_girls'); f['label'] = 'Co-educational'
    return d

FIXES = {'k12-curriculum-development-expert-registration': fix_k12, 'educational-publisher': fix_publisher,
         'principal-roundtable-virtual': fix_virtual_roundtable, 'principal-roundtable-delegate': fix_delegate,
         'recreation-hobbies-enrichment-provider': fix_recreation, 'individual-online-tutor-registration': fix_individual_tutor,
         'online-tutoring-support-provider-institution-registration': fix_online_tutoring, 'educational-consultant-registration': fix_educational_consultant,
         'student-ambassador': fix_student_ambassador, 'preschool': fix_preschool, 'parent-ambassador': fix_parent_ambassador,
         'school-registration': fix_inclusive_and_school, 'inclusive-school': fix_inclusive_and_school}

if __name__ == '__main__':
    build_course_provider()
    for fn in sorted(os.listdir(FORMS)):
        if not fn.endswith('.json') or fn.startswith('_'): continue
        slug = fn[:-5]; d = fix_pipe_help(load(slug))
        if slug in FIXES: d = FIXES[slug](d)
        save(slug, d); print('fixed', slug)
