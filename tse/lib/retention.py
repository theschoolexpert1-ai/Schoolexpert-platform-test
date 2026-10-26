"""Daily housekeeping implementing the retention schedule (see docs/DPDP-COMPLIANCE.md)."""
from ..db import db

def run():
    out = {}
    # sessions & one-time tokens
    out['sessions'] = db.run('DELETE FROM sessions WHERE expires_at < now()')
    out['tokens'] = db.run("DELETE FROM tokens WHERE expires_at < now() - interval '7 days'")
    # abandoned registration drafts: 12 months without activity -> erased (purpose no longer served)
    out['stale_drafts'] = db.run("DELETE FROM registrations WHERE status = 'draft' AND updated_at < now() - interval '12 months'")
    # rejected registrations: keep 1 year for dispute handling, then erase personal data
    out['rejected'] = db.run("""UPDATE registrations SET answers = '{}'::jsonb, private_enc = NULL, files = '{}'::jsonb
                                WHERE status = 'rejected' AND updated_at < now() - interval '12 months' AND answers <> '{}'::jsonb""")
    # contact messages older than 2 years
    out['contact'] = db.run("DELETE FROM contact_messages WHERE created_at < now() - interval '24 months'")
    # processing / audit logs: DPDP Rules require at least 1 year; we keep 2 years then purge
    out['rate_events'] = db.run("DELETE FROM rate_events WHERE at < now() - interval '1 day'")
    out['sessions'] = db.run('DELETE FROM sessions WHERE expires_at < now()')
    with db.transaction():   # the audit log is append-only; only this scheduled purge may delete, inside one transaction
        db.run("SELECT set_config('app.retention', 'on', true)")
        out['audit'] = db.run("DELETE FROM audit_log WHERE created_at < now() - interval '24 months'")
    out['outbox'] = db.run("DELETE FROM outbox WHERE status IN ('sent','skipped') AND created_at < now() - interval '90 days'")
    # accounts pending deletion for >30 days -> anonymise (orders kept for tax law: 8 years under CGST s.36)
    for u in db.all("SELECT id FROM users WHERE status = 'pending_deletion' AND deleted_at < now() - interval '30 days'"):
        anonymise_user(u['id'])
    out['anonymised'] = 'done'
    # expiries
    out['subs_expired'] = db.run("UPDATE subscriptions SET status = 'expired' WHERE status = 'active' AND ends_at < current_date")
    db.run("UPDATE listings SET tier = 'basic' WHERE tier <> 'basic' AND tier_until < current_date")
    out['jobs_closed'] = db.run("UPDATE jobs SET status = 'closed' WHERE status = 'published' AND closes_on < current_date")
    return out

def anonymise_user(uid):
    with db.transaction():
        db.run("""UPDATE users SET email = 'deleted-' || id || '@invalid', name = 'Deleted user', phone = NULL, password_hash = 'x',
                  city = NULL, state = NULL, pincode = NULL, avatar_url = NULL, nominee = NULL, prefs = '{}'::jsonb, status = 'deleted' WHERE id = %s""", uid)
        db.run('DELETE FROM teacher_profiles WHERE user_id = %s', uid)
        for t, cond in [('hub_members', 'user_id = %s'), ('lesson_plans', 'user_id = %s'), ('tutorial_saves', 'user_id = %s'), ('lesson_progress', 'user_id = %s'),
                        ('course_enrolments', 'user_id = %s'), ('connections', 'requester_id = %s OR addressee_id = %s'),
                        ('mentorships', 'mentee_id = %s OR mentor_id = %s'), ('direct_messages', 'sender_id = %s OR recipient_id = %s')]:
            db.run(f'DELETE FROM {t} WHERE {cond}', *([uid] * cond.count('%s')))     # Teachers Hub data
        db.run('DELETE FROM addresses WHERE user_id = %s', uid)
        db.run('DELETE FROM cart_items WHERE user_id = %s', uid)
        db.run("UPDATE registrations SET answers = '{}'::jsonb, private_enc = NULL, files = '{}'::jsonb, status = 'withdrawn' WHERE user_id = %s AND org_id IS NULL", uid)
        db.run('DELETE FROM listings WHERE user_id = %s', uid)
        db.run("UPDATE posts SET body = '[removed at user request]', title = '[removed]' WHERE user_id = %s", uid)
        db.run("UPDATE comments SET body = '[removed at user request]' WHERE user_id = %s", uid)
        db.run("UPDATE leads SET name = NULL, email = NULL, phone = NULL, message = NULL WHERE user_id = %s", uid)
        db.run('DELETE FROM newsletter_subscriptions WHERE user_id = %s', uid)
        db.run('DELETE FROM sessions WHERE user_id = %s', uid)
