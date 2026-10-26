"""Demo data (development / staging only). Every demo record is clearly marked "Demo".
Creates: admin + staff, parent, teacher, verified schools (detailed tier), partners, tutors, experts, jobs, events,
podcasts, newsletters, resources, books, products, community posts."""
import random, datetime, json
from flask import current_app
from . import db
from ..lib import forms as F, listings as L
from ..lib.security import hash_password, encrypt_json

PW = 'DemoPass#2026'
CITIES = [('Bengaluru', 'Karnataka', 'Bengaluru Urban', '5600'), ('Mysuru', 'Karnataka', 'Mysuru', '5700'), ('Chennai', 'Tamil Nadu', 'Chennai', '6000'),
          ('Hyderabad', 'Telangana', 'Hyderabad', '5000'), ('Pune', 'Maharashtra', 'Pune', '4110')]
TODAY = datetime.date.today()
NOW = datetime.datetime.now(datetime.timezone.utc)
START = datetime.datetime.combine(TODAY, datetime.time(5, 0), tzinfo=datetime.timezone.utc)  # 10:30 IST

def user(email, name, t, **kw):
    uid = db.val('SELECT id FROM users WHERE email = %s', email)
    if uid: return uid
    return db.insert('users', dict(email=email, name=name, password_hash=hash_password(PW), account_type=t, is_adult=True,
                     email_verified_at=NOW, phone=kw.pop('phone', '98450' + str(random.randint(10000, 99999))), **kw))

def fill(defn, overrides, rnd):
    """Plausible answers for every field of a form definition."""
    a = {}
    for _, s, f in F.fields(defn):
        k, t = f['key'], f['type']
        if k in overrides: a[k] = overrides[k]; continue
        if t == 'checkbox' and f.get('options'): a[k] = rnd.sample(f['options'], min(len(f['options']), f.get('maxSelect') or 5, rnd.randint(2, 5)))
        elif t == 'state': a[k] = 'Karnataka'
        elif t in ('radio', 'select') and f.get('options'): a[k] = rnd.choice(f['options'])
        elif t == 'yesno': a[k] = rnd.choice(['Yes', 'Yes', 'No'])
        elif t in ('consent', 'boolean'): a[k] = True
        elif t == 'year': a[k] = str(rnd.randint(1965, 2018))
        elif t == 'number': a[k] = str(rnd.randint(20, 1800))
        elif t == 'pincode': a[k] = '5600' + str(rnd.randint(10, 99))
        elif t == 'email': a[k] = 'demo@example.org'
        elif t == 'tel': a[k] = '98450' + str(rnd.randint(10000, 99999))
        elif t == 'url': a[k] = 'https://example.org'
        elif t == 'date': a[k] = '2026-06-01'
        elif t == 'textarea': a[k] = 'Demo content: replace with real information. ' + f['label'] + ' — described in a few sentences for parents and schools.'
        elif t == 'text': a[k] = 'Demo ' + f['label'][:40]
        elif t == 'matrix': a[k] = {f['rows'][0]: [f['columns'][0]]}
        elif t == 'repeat': a[k] = []
    return a

def registration(slug, owner_uid, org_name, overrides, tier_plan=None, rnd=None, panel=False, entity_user=False):
    rnd = rnd or random.Random(slug + org_name)
    defn = F.get(slug)
    org_id = None
    if not entity_user:
        org_id = db.insert('organisations', dict(name=org_name, slug=L.unique_slug('organisations', org_name), category=defn['_meta']['grp'],
                           kind=defn['_meta']['entity'], created_by=owner_uid))
        db.insert('org_members', dict(org_id=org_id, user_id=owner_uid, role='owner'), returning=None)
    ans = fill(defn, overrides, rnd)
    pub, priv = F.split_private(defn, ans)
    rid = db.insert('registrations', dict(form_slug=slug, user_id=owner_uid, org_id=org_id, status='verified', answers=pub, private_enc=encrypt_json(priv),
                    progress=100, submitted_at=NOW, verified_at=NOW, checks={'Identity / organisation verified': True}))
    if tier_plan:
        p = db.one('SELECT * FROM plans WHERE code = %s', tier_plan)
        start = TODAY - datetime.timedelta(days=rnd.randint(20, 200))
        db.insert('subscriptions', dict(org_id=org_id, user_id=None if org_id else owner_uid, plan_code=tier_plan, starts_at=start,
                  ends_at=start + datetime.timedelta(days=365), amount_paise=p['price_paise']), returning=None)
    lid = L.sync(rid)
    if panel and lid: db.run('UPDATE listings SET in_house_panel = true WHERE id = %s', lid)
    return org_id, rid, lid

def run():
    if db.val("SELECT 1 FROM users WHERE email = 'admin@demo.schoolexpert.in'"):
        print('demo data already present'); return
    rnd = random.Random(42)
    admin = user('admin@demo.schoolexpert.in', 'Demo Admin', 'admin', staff_role='admin')
    user('support@demo.schoolexpert.in', 'Demo Support', 'staff', staff_role='support')
    parent = user('parent@demo.schoolexpert.in', 'Asha Rao (Demo Parent)', 'parent', city='Bengaluru', state='Karnataka')
    teacher = user('teacher@demo.schoolexpert.in', 'Meera Iyer (Demo Teacher)', 'teacher', city='Bengaluru', state='Karnataka')

    # School - Basic / Plus / Pro (one school left unpaid to demonstrate the "activate your plan" journey)
    schools = [('Greenwood Valley School (Demo)', 'school-registration', 'school_founding'), ('Lakeside Public School (Demo)', 'school-registration', 'school_plus'),
               ('Sunrise International Academy (Demo)', 'school-registration', 'school_pro'), ('Little Sprouts Montessori (Demo)', 'preschool', 'school_plus'),
               ('Banyan Learning Community (Demo)', 'alternative-school', 'school_basic'), ('Harmony Inclusive School (Demo)', 'inclusive-school', 'school_plus'),
               ('Pathways Special School (Demo)', 'special-school', 'school_basic'), ('Riverdale Vidyalaya (Demo)', 'school-registration', None),
               ('Cedar Heights School (Demo)', 'school-registration', 'school_basic'), ('Horizon Online School (Demo)', 'online-school-registration', 'school_plus')]
    FEES = ['₹45,000 – ₹65,000', '₹85,000 – ₹1,20,000', '₹1.2 lakh – ₹1.8 lakh', '₹2,00,000 – ₹2,80,000', '₹3.5L – ₹5L']
    school_orgs = []
    for i, (name, slug, plan) in enumerate(schools):
        city, state, dist, pin = CITIES[i % 3] if i < 8 else CITIES[i % 5]
        owner = user(f'school{i}@demo.schoolexpert.in', f'{name.split(" (")[0]} Admin', 'organisation')
        defn = F.get(slug)
        ov = {}
        for role, val in (('name', name), ('city', city), ('state', state), ('headline', rnd.choice(['Learning with joy', 'Rooted in values, ready for the world', 'Every child, every day']))):
            f = F.field_by_role(defn, role)
            if f: ov[f['key']] = val
        ov.update({'district': dist, 'pin_code': pin + str(rnd.randint(10, 99)), 'affiliated_boards': rnd.sample(['CBSE', 'ICSE', 'State Board', 'IB', 'IGCSE'], 2)})
        if slug == 'school-registration':
            ov.update({'annual_fee_range_per_annum': FEES[i % len(FEES)], 'student_teacher_ratio': f"1:{rnd.choice([12, 15, 18, 22, 25, 30])}",
                       'transport_available': rnd.choice(['Yes', 'Yes', 'No']), 'hostel_available': rnd.choice(['No', 'No', 'Yes']),
                       'grades_offered': ['Nursery', 'LKG', 'UKG', 'Grade 1–5', 'Grade 6–8'] + (['Grade 9–10', 'Grade 11–12'] if i % 2 == 0 else ['Grade 9–10']),
                       'co_ed_boys_girls': 'Co-ed', 'medium_of_instruction': ['English']})
        if slug == 'alternative-school':
            ov['type_of_institution'] = ['Alternative School', 'Homeschool Support Centre', 'Learning Community']
        org_id, rid, lid = registration(slug, owner, name, ov, plan, rnd)
        db.run('UPDATE listings SET rating_avg = %s, rating_count = %s, view_count = %s WHERE id = %s', round(rnd.uniform(3.8, 4.9), 2), rnd.randint(3, 40), rnd.randint(50, 900), lid)
        if plan:   # 30 days of illustrative dashboard analytics
            for d in range(30):
                db.run('INSERT INTO listing_stats (listing_id, day, views, unlocks, leads, match_appearances) VALUES (%s, current_date - %s::int, %s, %s, %s, %s) ON CONFLICT DO NOTHING',
                       lid, d, rnd.randint(5, 60), rnd.randint(0, 3), rnd.randint(0, 2), rnd.randint(0, 9))
        school_orgs.append((org_id, lid, owner, name, city, state))
    db.run("UPDATE organisations SET founding_partner = true, founding_partner_since = current_date, renewal_waived_until = current_date + 1095 WHERE id = %s", school_orgs[0][0])

    partners = [('BrightBoard EdTech (Demo)', 'edtech-company', 'vendor_plus'), ('Vidya Books Publishers (Demo)', 'educational-publisher', 'vendor_pro'),
                ('SafeRide School Transport (Demo)', 'transport-logistics', 'vendor_basic'), ('NeatFit Uniforms & Stationery (Demo)', 'uniform-vendor', 'vendor_plus'),
                ('BuildRight School Infrastructure (Demo)', 'infrastructure-vendor', None)]
    partner_orgs = []
    for i, (name, slug, plan) in enumerate(partners):
        owner = user(f'partner{i}@demo.schoolexpert.in', name.split(' (')[0] + ' Team', 'organisation')
        defn = F.get(slug); ov = {}
        for role, val in (('name', name), ('city', 'Bengaluru'), ('state', 'Karnataka')):
            f = F.field_by_role(defn, role)
            if f: ov[f['key']] = val
        org_id, rid, lid = registration(slug, owner, name, ov, plan, rnd)
        partner_orgs.append(org_id)

    providers = [('Curio Online Tutoring (Demo)', 'online-tutoring-support-provider-institution-registration', 'vendor_basic', False),
                 ('Ravi Kumar — Maths Tutor (Demo)', 'individual-online-tutor-registration', 'vendor_plus', False),
                 ('Rhythm & Brush Arts Academy (Demo)', 'recreation-hobbies-enrichment-provider', 'vendor_basic', False),
                 ('Shiksha Teacher Training Institute (Demo)', 'teacher-training-institute-registration', 'vendor_basic', False),
                 ('Anil Mehta — Education Consultant (Demo)', 'educational-consultant-registration', 'vendor_plus', False),
                 ('MindBloom Child Psychology Clinic (Demo)', 'mental-health', 'vendor_basic', True),
                 ('Steps Behaviour Therapy Centre (Demo)', 'behaviour-consultant', 'vendor_basic', True),
                 ('Kavya Nair — Special Educator (Demo)', 'special-educator-registration', 'vendor_plus', True),
                 ('NextStep Career Guidance (Demo)', 'career-guidance', 'vendor_basic', False),
                 ('EduFin Fee Financing (Demo)', 'fee-financing', None, False),
                 ('CodeSprout STEM Courses (Demo)', 'course-provider', 'vendor_basic', False)]
    for i, (name, slug, plan, panel) in enumerate(providers):
        owner = user(f'provider{i}@demo.schoolexpert.in', name.split(' (')[0], 'organisation')
        defn = F.get(slug); ov = {}
        for role, val in (('name', name), ('city', rnd.choice(['Bengaluru', 'Chennai', 'Mysuru'])), ('state', 'Karnataka')):
            f = F.field_by_role(defn, role)
            if f: ov[f['key']] = val
        if slug == 'recreation-hobbies-enrichment-provider': ov.update(organisation_academy_centre_name=name, what_type_of_provider_are_you='Academy / Institute')
        registration(slug, owner, name, ov, plan, rnd, panel=panel)

    # teacher profile
    tdefn = F.get('teacher-registration')
    tans = fill(tdefn, {'full_name': 'Meera Iyer (Demo Teacher)', 'current_city': 'Bengaluru', 'state': 'Karnataka', 'professional_headline': 'CBSE Mathematics Teacher, Grades 6–10',
                        'about_me': 'Mathematics teacher with nine years of experience in CBSE schools. I make abstract ideas concrete through activities, puzzles and real-life problems, and I mentor students for Olympiads.',
                        'total_teaching_experience': '5–10 years', 'subjects_you_teach': ['Mathematics', 'Physics'], 'grades_levels_taught': ['Middle (6–8)', 'Secondary (9–10)'],
                        'boards_curricula_experience': ['CBSE'], 'profile_visibility': 'Visible on the public teacher directory (name, headline, subjects, city)',
                        'qualifications': [{'degree_qualification': 'M.Sc.', 'subject_specialisation': 'Mathematics', 'university_institution': 'Bangalore University', 'year_of_completion': '2014'},
                                           {'degree_qualification': 'B.Ed.', 'subject_specialisation': 'Mathematics & Science', 'university_institution': 'RV Teachers College', 'year_of_completion': '2015'}],
                        'work_experience': [{'school_organisation': 'Lakeside Public School (Demo)', 'designation': 'TGT Mathematics', 'board': 'CBSE', 'from_year': '2019', 'to_year_or_present': 'Present', 'subjects_grades': 'Mathematics, Grades 6–10', 'key_responsibilities_achievements': 'Class teacher for Grade 8; coordinated the maths lab; 12 students qualified for the regional Olympiad'},
                                            {'school_organisation': 'Sunrise International Academy (Demo)', 'designation': 'Mathematics Teacher', 'board': 'CBSE', 'from_year': '2015', 'to_year_or_present': '2019', 'subjects_grades': 'Mathematics, Grades 6–8', 'key_responsibilities_achievements': 'Introduced activity-based fractions unit; ran the puzzle club'}],
                        'certifications_trainings': [{'certification_training': 'CTET Paper II', 'issuing_body': 'CBSE', 'year': '2015'}]}, rnd)
    pub, priv = F.split_private(tdefn, tans)
    trid = db.insert('registrations', dict(form_slug='teacher-registration', user_id=teacher, status='under_review', answers=pub, private_enc=encrypt_json(priv), progress=100, submitted_at=NOW))
    db.insert('teacher_profiles', dict(user_id=teacher, registration_id=trid, slug='meera-iyer-demo', headline=tans['professional_headline'], visibility='public'), returning=None)

    # jobs
    roles = [('TGT Mathematics (CBSE)', ['Mathematics'], ['Grade 6–8', 'Grade 9–10']), ('PRT English', ['English'], ['Grade 1–5']), ('PGT Physics', ['Physics'], ['Grade 11–12']),
             ('Special Educator', ['Special Education'], ['All grades']), ('Pre-primary Teacher', ['Early Years'], ['Nursery', 'LKG', 'UKG']), ('Computer Science Teacher', ['Computer Science', 'Coding / AI'], ['Grade 6–10'])]
    for i, (title, subj, grades) in enumerate(roles):
        org_id, lid, owner, sname, city, state = school_orgs[i % 4]
        db.insert('jobs', dict(org_id=org_id, listing_id=lid, slug=L.unique_slug('jobs', f'{title} {sname}'), title=title, role=title.split(' (')[0], subjects=subj, grades=grades,
                  board='CBSE', employment_type='Full-time', experience='2+ years', qualifications='Graduate/Postgraduate + B.Ed.; CTET preferred', city=city, state=state,
                  salary_min=28000 + i * 3000, salary_max=40000 + i * 4000, show_salary=i % 2 == 0, status='published', published_at=NOW - datetime.timedelta(days=i),
                  featured_until=TODAY + datetime.timedelta(days=20) if i == 0 else None, created_by=owner,
                  description=f'{sname} is looking for a passionate {title}. You will plan engaging lessons, assess learning continuously, communicate with parents and contribute to school activities.\n\nWhat we offer: a supportive team, professional development, and modern classrooms. (Demo job — replace with real vacancy.)'), returning=None)

    # events
    def ev(title, kind, days, price, mode='online', city=None, form=None, cap=None, approval=False, summary='', member=None, audience=None):
        return db.insert('events', dict(slug=L.unique_slug('events', title), title=title, kind=kind, starts_at=START + datetime.timedelta(days=days),
                         ends_at=START + datetime.timedelta(days=days, hours=1, minutes=30), price_paise=price, member_price_paise=member, mode=mode, city=city, form_slug=form, capacity=cap,
                         passes_require_approval=approval, summary=summary, audience=audience or [],
                         body='**Demo event.** Agenda, speakers and joining instructions go here.\n\n- Welcome and introductions\n- Moderated discussion\n- Q&A and networking'))
    ev('Principals Virtual Roundtable: AI in the Classroom (Demo)', 'roundtable', 12, 59900, form='principal-roundtable-virtual', cap=30, summary='An exclusive online forum for Principals, Heads of School and senior leaders to discuss challenges and share practical solutions.')
    ev('Principal Roundtables India — Delegate Session (Demo)', 'roundtable', 26, 0, form='principal-roundtable-delegate', cap=25, approval=True, summary='A candid virtual conversation with fellow Principals.')
    ev('School Leadership Summit 2026 (Demo)', 'conference', 40, 249900, mode='offline', city='Bengaluru', cap=300, approval=True, summary='A full-day summit for school owners, principals and education partners. Schools can request passes.', audience=['schools'])
    ev('Workshop: Formative Assessment that Works (Demo)', 'workshop', 8, 49900, cap=60, summary='Hands-on workshop for teachers.', audience=['teachers'])
    ev('Webinar: Choosing the Right Board for Your Child (Demo)', 'webinar', 5, 0, summary='Free webinar for parents.')
    ev('Homeschoolers Meetup — Cubbon Park (Demo)', 'homeschool_meetup', 9, 29900, mode='offline', city='Bengaluru', cap=40, summary='Nature walk, games and a sharing circle for homeschooling families.')
    ev('Homeschoolers Meetup — Chennai (Demo)', 'homeschool_meetup', 16, 29900, mode='offline', city='Chennai', cap=40, summary='Science activities and a parents\' circle.')
    ev('Storytelling Session: Tales from the Panchatantra (Demo)', 'storytelling', 4, 19900, cap=50, member=9900, summary='Live online storytelling for ages 5–8. Booked by parents; we do not collect children\'s details.')
    ev('Storytelling Session: Space Adventures (Demo)', 'storytelling', 11, 19900, cap=50, member=9900, summary='Live online storytelling for ages 7–10.')

    pods = [('How NEP 2020 is changing classrooms (Demo)', 'podcast', 'Dr. Anita Sharma', 'Principal (fictional guest)'), ('Raising readers in a screen-first world (Demo)', 'podcast', 'Ravi Menon', 'Children\'s author (fictional guest)'),
            ('Inclusive classrooms: practical first steps (Demo)', 'webinar', 'Kavya Nair', 'Special educator (fictional guest)'), ('Career choices after Class 10 (Demo)', 'webinar', 'NextStep Career Guidance', 'Counsellors (fictional)')]
    for i, (t, k, gname, gt) in enumerate(pods):
        db.insert('podcasts', dict(slug=L.unique_slug('podcasts', t), kind=k, title=t, guest=gname, guest_title=gt, summary='A demo episode description. Replace with your episode notes.',
                  media_url=None, published_at=NOW - datetime.timedelta(days=7 * i + 2), duration_min=35 + i * 5, tags=['NEP', 'Parents']), returning=None)

    for i in range(3):
        db.insert('newsletters', dict(kind='industry', slug=f'industry-issue-{i + 1}-demo', title=f'The School Expert Industry Newsletter — Issue {i + 1} (Demo)', issue_no=i + 1,
                  summary='Policy updates, partner spotlights and opportunities for school leaders.', body='## In this issue\n\n- Policy roundup\n- Partner spotlight\n- Upcoming roundtables\n\n*Demo content.*',
                  published_at=NOW - datetime.timedelta(days=30 * i)), returning=None)
    for i, (band, access) in enumerate([('6-9', 'free'), ('10-13', 'subscriber'), ('6-9', 'subscriber')]):
        db.insert('newsletters', dict(kind='newsworms', slug=f'newsworms-{i + 1}-demo', title=f'NewsWorms Edition {i + 1} (Demo)', issue_no=i + 1, age_band=band, access=access,
                  summary='Why do monsoons arrive? Meet a young inventor. Puzzle page!', body='## Big story\n\nA child-friendly explainer goes here.\n\n## Try this at home\n\nA simple science activity.\n\n*Demo content.*',
                  published_at=NOW - datetime.timedelta(days=14 * i)), returning=None)

    for g in ['Grade 1', 'Grade 2', 'Grade 3', 'Grade 4', 'Grade 5']:
        for subj in ['Mathematics', 'English', 'EVS']:
            db.insert('resources', dict(slug=L.slugify(f'{g} {subj} worksheet demo'), kind='worksheet', title=f'{g} {subj} practice worksheet (Demo)', grade=g, subject=subj,
                      summary='Printable worksheet (demo placeholder file).', external_url='/resources', is_free=True), returning=None)
    for t, plat, free in [('Khan Academy Kids', 'Android / iOS', True), ('DIKSHA', 'Android / iOS / Web', True), ('Duolingo ABC', 'iOS', True), ('Demo Premium Phonics App', 'Android', False)]:
        db.insert('resources', dict(slug=L.slugify(t + ' app'), kind='learning_app', title=t, platform=plat, is_free=free, summary='Learning app for young learners.', external_url='https://example.org'), returning=None)
    for t in ['Getting started with homeschooling in India (Demo guide)', 'NIOS: what homeschooling families should know (Demo)', 'Weekly rhythm planner (Demo)']:
        db.insert('resources', dict(slug=L.slugify(t), kind='homeschool', title=t, summary='Demo resource.', external_url='/homeschoolers-hub'), returning=None)

    for t, a, band in [('The Magic Banyan Tree (Demo)', 'Fictional Author', '3-5'), ('Robots of Ranganathittu (Demo)', 'Fictional Author', '6-8'), ('The Monsoon Detectives (Demo)', 'Fictional Author', '9-12'), ('Letters to a Young Coder (Demo)', 'Fictional Author', '13+')]:
        bid = db.insert('books', dict(slug=L.slugify(t), title=t, author=a, age_band=band, language='English', summary='A demo book entry for the reading list.'))
        db.insert('book_reviews', dict(book_id=bid, user_id=parent, rating=random.randint(4, 5), body='Our family loved reading this together. (Demo review)', status='published'), returning=None)
        db.run('UPDATE books SET rating_avg = 4.5, rating_count = 1 WHERE id = %s', bid)

    prods = [('The School Expert™ Admissions Planner (Demo)', 'The School Expert™ Products', 49900, None, True, True), ('Junior Science Kit (Demo)', 'STEM & Robotics Kits', 129900, partner_orgs[0], False, False),
             ('Ergonomic School Bag (Demo)', 'School Bags', 149900, partner_orgs[3], False, False), ('Black School Shoes (Demo)', 'Shoes', 89900, partner_orgs[3], False, False),
             ('Art & Craft Mega Box (Demo)', 'Art & Craft', 69900, partner_orgs[3], False, False), ('Grade 5 Workbook Set (Demo)', 'Books', 59900, partner_orgs[1], False, False),
             ('Geometry Box (Demo)', 'Stationery', 19900, partner_orgs[3], False, False), ('Phonics Flash Cards (Demo)', 'Learning Materials', 34900, partner_orgs[1], False, False)]
    for t, cat, price, seller, tse, digital in prods:
        db.insert('products', dict(slug=L.slugify(t), title=t, category=cat, price_paise=price, mrp_paise=int(price * 1.2), seller_org_id=seller, is_tse=tse, is_digital=digital,
                  stock=200, status='published', summary='Demo product description.', description='Demo product. Replace with real specifications.',
                  bulk_tiers=[{'min_qty': 25, 'price_paise': int(price * 0.9)}, {'min_qty': 100, 'price_paise': int(price * 0.8)}]), returning=None)

    for comm, uid, title, body in [('teachers', teacher, 'Activity ideas for teaching fractions in Grade 5?', 'I am planning a fractions unit and would love hands-on ideas that worked in your classrooms.'),
                                   ('teachers', teacher, 'Resource: free exit-ticket templates', 'Sharing three exit-ticket formats I use for quick formative checks.'),
                                   ('parents', parent, 'How did you decide between CBSE and ICSE?', 'We are choosing a school for Grade 1. What mattered most for your family?'),
                                   ('homeschoolers', parent, 'Weekly rhythm that works for us', 'Mornings for reading and maths, afternoons for projects and outdoors.')]:
        db.insert('posts', dict(community=comm, user_id=uid, title=title + ' (Demo)', body=body, status='published'), returning=None)
    db.insert('corner_submissions', dict(user_id=parent, kind='model_tutorial', title='Solar system model with paper balls (Demo)', grade='Grade 4–6',
              materials='Newspaper, glue, poster colours, thermocol sheet', steps='1. Make paper balls of different sizes.\n2. Paint each planet.\n3. Arrange on the sheet in order.\n4. Label each planet.', status='published'), returning=None)
    db.insert('gallery_albums', dict(slug='leadership-summit-2025-demo', title='School Leadership Summit 2025 (Demo)', description='Photos will appear here.', taken_on=TODAY - datetime.timedelta(days=120)), returning=None)
    db.insert('referral_codes', dict(code='ASHA10', user_id=parent, kind='ambassador', commission_pct=10), returning=None)
    from ..lib import hub
    db.run("UPDATE events SET cpd_hours = 2, facilitator = 'The School Expert Academy', category = 'Assessment' WHERE title = 'Workshop: Formative Assessment that Works (Demo)'")
    hub.seed_demo(teacher, user, START)
    seed_reviews()
    print('demo data created — password for all demo accounts:', PW)


REVIEWS = [(5, 'Caring teachers', 'Teachers know every child by name and share progress regularly. Admissions were transparent.'),
           (4, 'Good balance', 'Strong academics with plenty of sport and arts. Transport could be more punctual.'),
           (4, 'Happy so far', 'Clean campus, responsive office, and the counsellor helped our child settle in quickly.'),
           (5, 'Great communication', 'Weekly updates and approachable leadership. Fee structure was explained clearly.'),
           (3, 'Mostly good', 'Good teaching, but class sizes in the higher grades feel large.')]

def seed_reviews():
    """Verified reviews come only from parents who unlocked the school — demo parents are created and given unlocks."""
    from ..routes.directory import recompute_rating
    reviewers = []
    for i in range(5):
        email = f'reviewer{i}@demo.schoolexpert.in'
        uid = db.val('SELECT id FROM users WHERE email = %s', email) or user(email, f'Demo Parent Reviewer {i + 1}', 'parent')
        reviewers.append(uid)
    for l in db.all("""SELECT l.id FROM listings l JOIN categories c ON c.slug = l.category WHERE c.grp = 'schools' AND l.is_published"""):
        rnd = random.Random(l['id'])
        for uid in rnd.sample(reviewers, rnd.randint(2, 5)):
            rating, title, body = rnd.choice(REVIEWS)
            db.run('INSERT INTO unlocks (user_id, listing_id) VALUES (%s,%s) ON CONFLICT DO NOTHING', uid, l['id'])
            db.run("""INSERT INTO reviews (listing_id, user_id, rating, title, body, verified, status) VALUES (%s,%s,%s,%s,%s,true,'published')
                      ON CONFLICT (listing_id, user_id) DO NOTHING""", l['id'], uid, rating, title, body)
        recompute_rating(l['id'])
