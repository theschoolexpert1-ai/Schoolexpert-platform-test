"""AI-assisted CV builder for teachers.

Privacy by design: only professional data (no phone, email, DOB, gender, address) is sent to the AI model, and
only with the teacher's 'ai_cv' consent. Contact details are merged locally when the PDF is rendered.
Without an API key the builder falls back to a deterministic template so the feature always works.
"""
import json, io, re, datetime
import requests
from flask import current_app
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from xml.sax.saxutils import escape

PROFESSIONAL_KEYS = ['professional_headline', 'about_me', 'total_teaching_experience', 'current_employment_status', 'current_designation',
    'current_school_organisation', 'highest_qualification', 'qualifications', 'teaching_qualifications', 'teacher_eligibility_tests_cleared',
    'subjects_you_teach', 'grades_levels_taught', 'boards_curricula_experience', 'languages_you_can_teach_in', 'teaching_methods',
    'work_experience', 'digital_skills', 'additional_responsibilities_handled', 'certifications_trainings', 'awards_recognition',
    'student_outcomes_results', 'publications_workshops_or_talks', 'preferred_roles']

def professional_subset(answers):
    return {k: answers[k] for k in PROFESSIONAL_KEYS if answers.get(k)}

def template_cv(name, a):
    exp = []
    for w in a.get('work_experience') or []:
        bullets = [b.strip(' -•') for b in re.split(r'[\n;]+', w.get('key_responsibilities_achievements', '')) if b.strip()]
        exp.append({'title': w.get('designation', ''), 'org': w.get('school_organisation', ''), 'period': f"{w.get('from_year', '')} – {w.get('to_year_or_present', '') or 'Present'}",
                    'detail': w.get('subjects_grades', ''), 'bullets': bullets[:6]})
    edu = [{'degree': q.get('degree_qualification', ''), 'subject': q.get('subject_specialisation', ''), 'institution': q.get('university_institution', ''), 'year': q.get('year_of_completion', '')}
           for q in a.get('qualifications') or []]
    summary = a.get('about_me') or ''
    if not summary:
        summary = f"{a.get('total_teaching_experience', 'Experienced')} educator teaching {', '.join((a.get('subjects_you_teach') or [])[:3])}."
    return {
        'name': name, 'headline': a.get('professional_headline', ''),
        'summary': summary,
        'skills': (a.get('subjects_you_teach') or []) + (a.get('teaching_methods') or [])[:6] + (a.get('digital_skills') or [])[:6],
        'experience': exp, 'education': edu,
        'certifications': [f"{c.get('certification_training', '')} — {c.get('issuing_body', '')} ({c.get('year', '')})".strip(' —()') for c in a.get('certifications_trainings') or []]
                          + (a.get('teaching_qualifications') or []) + (a.get('teacher_eligibility_tests_cleared') or []),
        'boards': a.get('boards_curricula_experience') or [], 'grades': a.get('grades_levels_taught') or [],
        'languages': a.get('languages_you_can_teach_in') or [],
        'achievements': [x for x in [a.get('awards_recognition'), a.get('student_outcomes_results'), a.get('publications_workshops_or_talks')] if x],
        'generated_by': 'template',
    }

SYSTEM = """You write concise, truthful CVs for Indian K-12 teachers. Use ONLY facts present in the input; never invent employers,
dates, results, certifications or numbers. Improve wording, group skills, and turn responsibilities into strong, specific bullet points
(start with action verbs, mention boards/grades/subjects when given). Indian English spelling. Output strict JSON only."""

def ai_cv(name, answers, target_role=None):
    base = template_cv(name, answers)
    key = current_app.config.get('ANTHROPIC_API_KEY')
    if not key:
        return base
    payload = professional_subset(answers)
    schema = '{"headline": str, "summary": str (60-110 words), "skills": [str], "experience": [{"title","org","period","detail","bullets":[str]}], "education": [{"degree","subject","institution","year"}], "certifications": [str], "achievements": [str]}'
    prompt = f"Teacher profile (JSON):\n{json.dumps(payload, ensure_ascii=False)}\n\nTarget role: {target_role or 'general teaching roles'}\nReturn JSON matching: {schema}"
    try:
        r = requests.post('https://api.anthropic.com/v1/messages', timeout=60, headers={
            'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'},
            json={'model': current_app.config['ANTHROPIC_MODEL'], 'max_tokens': 2000, 'system': SYSTEM,
                  'messages': [{'role': 'user', 'content': prompt}]})
        r.raise_for_status()
        text = ''.join(b.get('text', '') for b in r.json().get('content', []))
        data = json.loads(text[text.index('{'): text.rindex('}') + 1])
        base.update({k: v for k, v in data.items() if k in base and v})
        base['generated_by'] = 'ai'
    except Exception as e:
        current_app.logger.warning('AI CV generation failed, using template: %s', e)
    return base

def render_pdf(cv, contact):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"{cv['name']} — CV", author=cv['name'])
    ss = getSampleStyleSheet()
    navy = colors.HexColor('#0B2A6B'); red = colors.HexColor('#B3121B'); grey = colors.HexColor('#4A5568')
    H = ParagraphStyle('H', parent=ss['Title'], fontName='Helvetica-Bold', fontSize=20, textColor=navy, alignment=0, spaceAfter=2)
    sub = ParagraphStyle('sub', parent=ss['Normal'], fontSize=10.5, textColor=red, spaceAfter=4)
    small = ParagraphStyle('small', parent=ss['Normal'], fontSize=9, textColor=grey)
    h2 = ParagraphStyle('h2', parent=ss['Heading2'], fontName='Helvetica-Bold', fontSize=11.5, textColor=navy, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle('body', parent=ss['Normal'], fontSize=9.6, leading=13)
    bullet = ParagraphStyle('b', parent=body, leftIndent=10, bulletIndent=2)
    e = lambda s: escape(str(s or ''))
    st = [Paragraph(e(cv['name']), H)]
    if cv.get('headline'): st.append(Paragraph(e(cv['headline']), sub))
    st.append(Paragraph(' · '.join(e(x) for x in contact if x), small))
    st.append(HRFlowable(width='100%', color=navy, thickness=1, spaceBefore=6, spaceAfter=4))
    if cv.get('summary'): st += [Paragraph('Profile', h2), Paragraph(e(cv['summary']), body)]
    facts = []
    if cv.get('boards'): facts.append(['Boards', ', '.join(cv['boards'])])
    if cv.get('grades'): facts.append(['Grades', ', '.join(cv['grades'])])
    if cv.get('languages'): facts.append(['Languages', ', '.join(cv['languages'])])
    if facts:
        t = Table([[Paragraph(f'<b>{e(a)}</b>', body), Paragraph(e(b), body)] for a, b in facts], colWidths=[28 * mm, None])
        t.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('BOTTOMPADDING', (0, 0), (-1, -1), 2)]))
        st += [Spacer(1, 4), t]
    if cv.get('skills'): st += [Paragraph('Key Skills', h2), Paragraph(e(' • '.join(dict.fromkeys(cv['skills']))), body)]
    if cv.get('experience'):
        st.append(Paragraph('Experience', h2))
        for x in cv['experience']:
            st.append(Paragraph(f"<b>{e(x.get('title'))}</b> — {e(x.get('org'))} <font color='#4A5568'>({e(x.get('period'))})</font>", body))
            if x.get('detail'): st.append(Paragraph(e(x['detail']), small))
            for b in x.get('bullets') or []: st.append(Paragraph(e(b), bullet, bulletText='•'))
            st.append(Spacer(1, 4))
    if cv.get('education'):
        st.append(Paragraph('Education', h2))
        for x in cv['education']:
            st.append(Paragraph(f"<b>{e(x.get('degree'))}</b>{', ' + e(x.get('subject')) if x.get('subject') else ''} — {e(x.get('institution'))} {('(' + e(x.get('year')) + ')') if x.get('year') else ''}", body))
    if cv.get('certifications'):
        st.append(Paragraph('Certifications & Eligibility', h2))
        for c in cv['certifications']: st.append(Paragraph(e(c), bullet, bulletText='•'))
    if cv.get('achievements'):
        st.append(Paragraph('Achievements', h2))
        for c in cv['achievements']: st.append(Paragraph(e(c), bullet, bulletText='•'))
    st += [Spacer(1, 10), Paragraph(f"CV generated on The School Expert™ · {datetime.date.today().strftime('%d %b %Y')}", small)]
    doc.build(st)
    return buf.getvalue()
