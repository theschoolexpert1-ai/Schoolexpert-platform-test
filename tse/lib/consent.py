"""DPDP Act 2023 / DPDP Rules 2025 consent management.

- Each purpose has a versioned, plain-language notice (consent_notices).
- Every grant/withdrawal is an append-only record with notice version, method, IP and user agent.
- Withdrawal is one click from the Privacy Centre (as easy as giving consent).
"""
from flask import request
from ..db import db
from .security import client_ip

PURPOSES = {
    'account': 'Creating and operating your account',
    'registration': 'Processing your registration, verification and listing',
    'profile_listing': 'Publishing your professional / organisation profile on the directory',
    'lead_sharing': 'Sharing your contact details with the school or provider you choose to contact',
    'job_application': 'Sharing your CV and profile with the school you apply to',
    'personal_assistance': 'Personal Assistance service (school visits, forms, TC collection)',
    'expert_request': 'Ask The School Expert — matching you with an expert or panel member',
    'marketing': 'Newsletters, offers and updates from The School Expert™',
    'analytics_cookies': 'Analytics and advertising cookies (Google Analytics / Ads)',
    'guardian_student_ambassador': 'Verifiable parental consent for a Student Ambassador (14–18)',
    'community': 'Posting in The School Expert™ communities',
    'ai_cv': 'Using AI to draft your CV from the profile you entered',
}

def notice(purpose, lang='en'):
    return db.one('SELECT * FROM consent_notices WHERE purpose = %s AND lang = %s AND active ORDER BY version DESC LIMIT 1', purpose, lang) \
        or db.one("SELECT * FROM consent_notices WHERE purpose = %s AND lang = 'en' AND active ORDER BY version DESC LIMIT 1", purpose)

def record(purpose, granted=True, user_id=None, email=None, method='checkbox', context=None, guardian=None):
    n = notice(purpose)
    return db.insert('consents', dict(user_id=user_id, email=email, purpose=purpose, notice_version=n['version'] if n else 1,
                     granted=granted, method=method, context=context, ip=client_ip() if request else None,
                     user_agent=(request.headers.get('User-Agent', '')[:300] if request else None), guardian=guardian))

def current(user_id):
    """Latest state per purpose."""
    rows = db.all("""SELECT DISTINCT ON (purpose) purpose, granted, notice_version, created_at, withdrawn_at
                     FROM consents WHERE user_id = %s ORDER BY purpose, id DESC""", user_id)
    return {r['purpose']: r for r in rows}

def has(user_id, purpose):
    r = current(user_id).get(purpose)
    return bool(r and r['granted'] and not r['withdrawn_at'])

def withdraw(user_id, purpose):
    db.run('UPDATE consents SET withdrawn_at = now() WHERE user_id = %s AND purpose = %s AND withdrawn_at IS NULL', user_id, purpose)
    record(purpose, granted=False, user_id=user_id, method='dashboard', context='withdrawn')
