"""Safe-community guardrails.

Automatic checks run before anything is published:
 - personal data leakage (phone numbers, emails, Aadhaar-like numbers, addresses of children, student names with marks)
 - abusive language
 - spam / solicitation (links, "DM me", repeated promotions)
 - posting rate limits per user
Content that trips a check is held for moderator review instead of being published.
Users can report anything; 3 open reports auto-hide content until reviewed.
"""
import re
from ..db import db

PHONE = re.compile(r'(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}(?!\d)')
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+')
AADHAAR = re.compile(r'(?<!\d)\d{4}[\s-]?\d{4}[\s-]?\d{4}(?!\d)')
CHILD_PII = re.compile(r'\b(my (son|daughter|child|kid)|student)\b.{0,40}\b(name is|named|roll no|admission no|marks|address|lives at)\b', re.I)
SOLICIT = re.compile(r'(dm me|whatsapp me|call me|contact me on|join my|buy now|discount code|limited offer|earn money|work from home)', re.I)
LINK = re.compile(r'https?://|www\.', re.I)
ABUSE = re.compile(r'\b(idiot|stupid|moron|bastard|bitch|chutiya|madarchod|bhenchod|saala|harami|kutta|fuck|shit)\b', re.I)

def check(text, user_id=None, allow_links=False):
    """Returns (ok, reason). ok=False means hold for review."""
    t = text or ''
    if ABUSE.search(t): return False, 'Possible abusive language'
    if AADHAAR.search(t): return False, 'Looks like an ID number'
    if PHONE.search(t) or EMAIL.search(t): return False, 'Contains contact details — the community never shares personal phone numbers or emails'
    if CHILD_PII.search(t): return False, 'May identify a child — please do not share children\'s personal information'
    if SOLICIT.search(t): return False, 'Looks like promotion or solicitation'
    if not allow_links and len(LINK.findall(t)) > 1: return False, 'Contains multiple links'
    if user_id:
        recent = db.val("SELECT count(*) FROM posts WHERE user_id = %s AND created_at > now() - interval '1 hour'", user_id) or 0
        recent += db.val("SELECT count(*) FROM comments WHERE user_id = %s AND created_at > now() - interval '10 minutes'", user_id) or 0
        if recent > 15: return False, 'Posting too quickly'
    return True, None

def is_banned(user_id):
    return bool(db.val('SELECT 1 FROM community_bans WHERE user_id = %s AND (until IS NULL OR until > now())', user_id))

def auto_hide(target_type, target_id):
    n = db.val("SELECT count(*) FROM content_reports WHERE target_type = %s AND target_id = %s AND status = 'open'", target_type, target_id)
    if n >= 3:
        table = 'posts' if target_type == 'post' else 'comments'
        db.run(f"UPDATE {table} SET status = 'hidden', moderation_reason = 'Auto-hidden after multiple reports' WHERE id = %s AND status = 'published'", target_id)
