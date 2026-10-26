"""Round 2 of your form documents (13 Oct 2026).

  * TeacherAmbassadors.docx            -> new form `teacher-ambassador` (new category, teacher account)
  * School_Registration_Form_Expanded  -> "School Category" question removed, as in your updated document
  * Student / Parent Ambassador forms  -> byte-identical to the earlier uploads, no change

Run from the project root:  python forms_src/build_v2.py
"""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS = os.path.join(ROOT, 'tse', 'forms')
def save(slug, d): json.dump(d, open(os.path.join(FORMS, slug + '.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
def load(slug): return json.load(open(os.path.join(FORMS, slug + '.json'), encoding='utf-8'))

def F(key, label, type, required=False, options=None, other=False, vis='detailed', **kw):
    f = dict(key=key, label=label, type=type, required=required, visibility=vis)
    if options: f['options'] = options
    if other: f['other'] = True
    f.update(kw); return f

def teacher_ambassador():
    S = lambda title, fields, description='': dict(title=title, description=description, fields=fields)
    d = dict(slug='teacher-ambassador', title='Teacher Ambassador Registration', category='ambassadors', label='Teacher Ambassadors',
             entity='individual', account='teacher',
             intro=['BE THE VOICE OF TEACHERS. BE PART OF THE CHANGE.',
                    'Teachers are among the most important voices in a child’s educational journey.',
                    'The School Expert™ is building a community that brings together teachers, parents, schools, education experts and organisations to create a stronger ecosystem around every child.',
                    'As a Teacher Ambassador, you can help us connect educators, share experiences, amplify teacher voices and create meaningful conversations around education.',
                    'We are looking for passionate educators who would like to contribute their time, experience, ideas and voice to the community.',
                    'Registration is free.',
                    'Please complete this form to express your interest in becoming a The School Expert™ Teacher Ambassador.'],
             outro=['YOU\'RE IN!', 'Thank you for expressing your interest in becoming a Teacher Ambassador for The School Expert™.',
                    'We believe teachers should not just participate in conversations about education — teachers should help lead them.',
                    'Our team will review your registration and get in touch with you regarding the next steps.', 'Welcome to the movement.',
                    'The School Expert™', 'Made in India. For India. By Indians.', 'It takes a village to raise a child.',
                    'It takes an entire country to raise The School Expert™ for our children.'],
             sections=[
        S('About You', [
            F('full_name', 'Full Name', 'text', True, vis='private', role='name'),
            F('email_address', 'Email Address', 'email', True, vis='private', role='email'),
            F('mobile_whatsapp_number', 'Mobile / WhatsApp Number', 'tel', True, vis='private', role='phone'),
            F('city', 'City', 'text', True, vis='private', role='city'),
            F('state', 'State', 'state', True, vis='private', role='state'),
            F('name_of_school_institution', 'Name of School / Institution', 'text', True, vis='private'),
            F('current_designation', 'Current Designation', 'radio', False, ['Teacher', 'Senior Teacher', 'Coordinator', 'Academic Coordinator', 'Head of Department',
              'Vice Principal', 'Principal', 'Special Educator', 'Counsellor'], other=True, vis='private')]),
        S('Your Teaching Experience', [
            F('years_of_experience_in_education', 'Years of experience in education', 'radio', False,
              ['Less than 2 years', '2–5 years', '6–10 years', '11–15 years', '16–20 years', 'More than 20 years'], vis='private'),
            F('curriculum_board_you_work_with', 'Curriculum / Board you work with', 'radio', False,
              ['CBSE', 'ICSE / CISCE', 'IB', 'Cambridge', 'State Board', 'NIOS', 'Montessori', 'Alternative / Progressive'], other=True, vis='private'),
            F('classes_age_groups_you_work_with', 'Classes / age groups you work with', 'checkbox', False,
              ['Early Years', 'Primary', 'Middle School', 'Secondary', 'Senior Secondary', 'Special Education'], other=True, vis='private'),
            F('subjects_areas_of_expertise', 'Subjects / areas of expertise', 'checkbox', False,
              ['English', 'Mathematics', 'Science', 'Social Science', 'Languages', 'Computer Science / Technology', 'Art & Design', 'Music',
               'Sports / Physical Education', 'Life Skills', 'Special Education'], other=True, vis='private')]),
        S('Why Do You Want to Be a Teacher Ambassador?', [
            F('what_motivates_you', 'What motivates you to become a Teacher Ambassador for The School Expert™?', 'textarea', True, vis='private'),
            F('what_teachers_need_most', 'What do you believe teachers need most today?', 'textarea', False, vis='private'),
            F('change_in_education', 'What change would you like to see in education?', 'textarea', False, vis='private'),
            F('contribute_to_community', 'What would you like to contribute to The School Expert™ Community?', 'checkbox', False,
              ['My teaching experience', 'Ideas and best practices', 'Teacher perspectives', 'Educational content', 'Workshops',
               'Webinars / panel discussions', 'Mentoring', 'Research / surveys', 'Community building', 'Connecting educators', 'Connecting schools'],
              other=True, vis='private')]),
        S('How Would You Like to Engage?', [
            F('activities_interested_in', 'As a Teacher Ambassador, which activities would you be interested in?', 'checkbox', False,
              ['CONNECT – Introduce other teachers to The School Expert Community', 'CONTRIBUTE – Share articles, teaching ideas, resources and experiences',
               'CONVERSE – Participate in discussions, webinars and panel conversations', 'COLLABORATE – Work with schools, educators and education organisations',
               'MENTOR – Support fellow teachers and educators', 'CREATE – Help create educational content for parents, teachers and students',
               'SPEAK – Participate as a speaker or subject expert', 'RESEARCH – Participate in education surveys and research initiatives',
               'ADVOCATE – Represent and amplify the voice of teachers', 'LEAD – Help build the Teacher Ambassador network in my city / region'], vis='private')],
          'This is the most important section of the form.'),
        S('Your Availability', [
            F('time_you_can_contribute', 'How much time could you comfortably contribute?', 'radio', False,
              ['1–2 hours per month', '2–5 hours per month', '5–10 hours per month', '10+ hours per month', 'Depends on the activity'], vis='private'),
            F('preferred_participation', 'How would you prefer to participate?', 'checkbox', False, ['Online', 'Offline', 'Both online and offline'], vis='private'),
            F('participation_frequency', 'How frequently would you like to participate?', 'radio', False,
              ['Occasionally', 'Once a month', '2–3 times a month', 'Weekly', 'As opportunities arise'], vis='private')]),
        S('Your Strengths', [
            F('strongest_areas', 'What are your strongest areas?', 'checkbox', False,
              ['Public Speaking', 'Writing', 'Teaching / Training', 'Mentoring', 'Community Building', 'Event Management', 'Social Media / Content Creation',
               'Research', 'Leadership', 'Technology / EdTech', 'Networking'], other=True, vis='private'),
            F('passionate_about', 'Please tell us something you are particularly passionate about in education.', 'textarea', False, vis='private'),
            F('previous_communities', 'Have you previously participated in any teacher communities, educational initiatives or professional networks?', 'yesno', False, vis='private'),
            F('previous_communities_details', 'If yes, please tell us about it.', 'textarea', False, vis='private',
              showIf={'field': 'previous_communities', 'equals': 'Yes'})]),
        S('Your Digital Presence', [
            F('linkedin_profile', 'LinkedIn Profile', 'url', False, vis='private'),
            F('instagram_profile', 'Instagram / Professional Social Media Profile', 'url', False, vis='private'),
            F('website_blog_portfolio', 'Website / Blog / Portfolio', 'url', False, vis='private'),
            F('comfortable_being_featured', 'Would you be comfortable being featured as a Teacher Ambassador on The School Expert™ platforms?', 'radio', False,
              ['Yes', 'No', "I'd like to know more"], vis='private')]),
        S('Ambassador Commitment', [
            F('what_ambassador_means', 'What does being a Teacher Ambassador mean to you?', 'textarea', True, vis='private'),
            F('represent_values', 'Are you willing to represent the values and vision of The School Expert™ in your interactions with teachers, schools, parents and other stakeholders?', 'yesno', False, vis='private'),
            F('introduce_educators', 'Would you be willing to introduce other educators to The School Expert Community?', 'radio', False,
              ['Yes', 'Maybe', 'Not at this time'], vis='private')]),
        S('Consent', [
            dict(key='communication_consent', label='Communication Consent', type='consent', required=False, visibility='private',
                 text='I agree to be contacted by The School Expert™ regarding Teacher Ambassador activities, community initiatives, events, opportunities, surveys and collaborations.'),
            dict(key='ambassador_declaration', label='Ambassador Declaration', type='consent', required=True, visibility='private',
                 text='I confirm that the information I have provided is accurate, and I agree to follow The School Expert™ Teacher Ambassador guidelines.',
                 pending_wording=True)]),
    ])
    save('teacher-ambassador', d)

def school_registration_v2():
    d = load('school-registration')
    for s in d['sections']:
        s['fields'] = [f for f in s['fields'] if f['key'] != 'school_category']
    save('school-registration', d)

def index():
    idx = json.load(open(os.path.join(FORMS, '_index.json'), encoding='utf-8'))
    if not any(x['slug'] == 'teacher-ambassador' for x in idx):
        idx.append(dict(slug='teacher-ambassador', title='Teacher Ambassador Registration', category='ambassadors', label='Teacher Ambassadors',
                        entity='individual', fields=32, provisional=False))
    json.dump(idx, open(os.path.join(FORMS, '_index.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

if __name__ == '__main__':
    teacher_ambassador(); school_registration_v2(); index(); print('done')
