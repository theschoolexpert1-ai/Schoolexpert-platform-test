"""Entitlements: payment decides access & visibility.

Plans are data (table `plans`, column `grants`). Every feature gate, limit and visibility rule in the app reads from
here, so new tiers/features are added by editing plan grants — not code.

Families & ladders
  school : School - Basic (1) -> School - Plus (2) -> School - Pro (3)
  vendor : Vendor - Basic (1) -> Vendor - Plus (2) -> Vendor - Pro (3)     (all non-school organisations)
Upgrades go one step at a time (Basic -> Plus -> Pro), paying the difference less unused credit.
"""
import datetime, functools
from flask import g, redirect, url_for, flash, render_template
from ..db import db

# Defaults when an organisation has no active paid plan: nothing is published, no dashboard.
NONE = dict(level=0, published=False, dashboard=False, tier='basic', leads=False, detailed_profile=False, jobs_limit=0,
            photos_limit=0, products_limit=0, commission_pct=20, directory_access=False, teacher_search=False, featured=False,
            featured_jobs=0, analytics='none', review_reply=False, campuses_limit=1, ad_credit_days=0, newsletter_feature=False,
            podcast_feature=False, webinar_partner=False, account_manager=False, priority_support=False, event_discount_pct=0,
            ai_match=False, rank=0, virtual_tour=False, lead_alerts=False)

FEATURE_LABELS = {
    'published': 'Verified listing on the directory', 'detailed_profile': 'Detailed profile (fees, facilities, contacts) for entitled viewers',
    'leads': 'Verified leads & enquiries', 'jobs_limit': 'Active job posts', 'photos_limit': 'Photos & videos', 'products_limit': 'Marketplace products',
    'commission_pct': 'Marketplace commission', 'directory_access': 'See detailed profiles of schools & partners', 'teacher_search': 'Teacher directory (recruitment)',
    'featured': 'Featured placement (top of city & category)', 'featured_jobs': 'Featured jobs per month', 'analytics': 'Analytics',
    'review_reply': 'Reply to verified reviews', 'campuses_limit': 'Campuses / branches', 'ad_credit_days': 'Sponsored banner days included',
    'newsletter_feature': 'Feature in the newsletter', 'podcast_feature': 'Podcast / webinar feature', 'webinar_partner': 'Webinar partner slot',
    'account_manager': 'Dedicated account manager', 'priority_support': 'Priority support', 'event_discount_pct': 'Event pass discount',
    'ai_match': 'Full profile used in AI School Match', 'virtual_tour': 'Virtual tour', 'lead_alerts': 'Instant WhatsApp/email lead alerts',
}

def family_for(category_grp):
    return 'school' if category_grp == 'schools' else 'vendor'

def org_family(org):
    return family_for(org['category'])

def active_subscription(org_id, family=None):
    """Highest-level active tier subscription (school/vendor family) for an organisation."""
    if not org_id: return None
    rows = db.all("""SELECT s.*, p.name, p.family, p.level, p.price_paise, p.grants, p.interval, p.badge FROM subscriptions s JOIN plans p ON p.code = s.plan_code
                     WHERE s.org_id = %s AND s.status = 'active' AND (s.ends_at IS NULL OR s.ends_at >= current_date)
                       AND p.family IN ('school','vendor') ORDER BY p.level DESC, s.id DESC""", org_id)
    if family: rows = [r for r in rows if r['family'] == family]
    return rows[0] if rows else None

def for_org(org_id):
    """Merged entitlements: tier plan + active add-ons."""
    e = dict(NONE)
    sub = active_subscription(org_id)
    if sub:
        e.update(sub['grants']); e['plan_code'] = sub['plan_code']; e['plan_name'] = sub['name']; e['family'] = sub['family']
        e['level'] = sub['level']; e['ends_at'] = sub['ends_at']; e['subscription_id'] = sub['id']; e['badge'] = sub['badge']
    for a in db.all("""SELECT p.grants FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.org_id = %s AND s.status = 'active'
                       AND (s.ends_at IS NULL OR s.ends_at >= current_date) AND p.family = 'addon'""", org_id or 0):
        for k, v in a['grants'].items():
            if isinstance(v, bool) and v: e[k] = True
    return e

def current():
    """Entitlements for the active organisation of the logged-in user (cached per request)."""
    if not getattr(g, 'org', None): return dict(NONE)
    if not hasattr(g, '_ent'): g._ent = for_org(g.org['id'])
    return g._ent

def limit_ok(key, used):
    lim = current().get(key)
    return lim is None or used < lim

def next_plan(org_id):
    """The single next step on the ladder (Basic->Plus, Plus->Pro), or the entry plan if none."""
    org = db.one('SELECT * FROM organisations WHERE id = %s', org_id)
    fam = org_family(org)
    sub = active_subscription(org_id)
    lvl = sub['level'] if sub else 0
    return db.one("SELECT * FROM plans WHERE family = %s AND level = %s AND active AND stream <> 'founding_partner' ORDER BY sort LIMIT 1", fam, lvl + 1), sub

def upgrade_quote(org_id):
    """Price to move to the next tier: new price minus unused value of the current annual plan."""
    nxt, sub = next_plan(org_id)
    if not nxt: return None
    if not sub: return dict(plan=nxt, credit=0, price=nxt['price_paise'], current=None)
    paid = sub['amount_paise'] if sub['amount_paise'] is not None else sub['price_paise']
    credit = 0
    if sub['ends_at'] and sub['interval'] == 'annual':
        days_left = max(0, (sub['ends_at'] - datetime.date.today()).days)
        credit = int(paid * min(days_left, 365) / 365)
    return dict(plan=nxt, credit=credit, price=max(0, nxt['price_paise'] - credit), current=sub)

def renewal_quote(org_id):
    org = db.one('SELECT * FROM organisations WHERE id = %s', org_id)
    sub = db.one("""SELECT s.*, p.price_paise, p.name FROM subscriptions s JOIN plans p ON p.code = s.plan_code WHERE s.org_id = %s
                    AND p.family IN ('school','vendor') AND s.status IN ('active','expired') ORDER BY p.level DESC, s.id DESC LIMIT 1""", org_id)
    if not sub: return None
    waived = org['renewal_waived_until'] and org['renewal_waived_until'] >= datetime.date.today()
    return dict(sub=sub, price=0 if waived else sub['price_paise'], waived=bool(waived))

def requires(feature, message=None):
    """Decorator for organisation features; shows an upgrade prompt instead of a dead end."""
    def deco(fn):
        @functools.wraps(fn)
        def w(*a, **kw):
            e = current()
            if not e.get(feature):
                q = upgrade_quote(g.org['id']) if getattr(g, 'org', None) else None
                return render_template('dashboard/upsell.html', feature=FEATURE_LABELS.get(feature, feature), message=message, quote=q, ent=e), 402
            return fn(*a, **kw)
        return w
    return deco

def bump_stat(listing_id, field):
    if not listing_id: return
    db.run(f"""INSERT INTO listing_stats (listing_id, day, {field}) VALUES (%s, current_date, 1)
               ON CONFLICT (listing_id, day) DO UPDATE SET {field} = listing_stats.{field} + 1""", listing_id)

def tier_label(level):
    return {0: 'Not active', 1: 'Basic', 2: 'Plus', 3: 'Pro'}.get(level or 0, '')

COMPARE_ROWS = [('published', 'bool'), ('detailed_profile', 'bool'), ('leads', 'bool'), ('lead_alerts', 'bool'), ('jobs_limit', 'n'), ('photos_limit', 'n'),
                ('products_limit', 'n'), ('commission_pct', 'pct'), ('directory_access', 'bool'), ('review_reply', 'bool'), ('ai_match', 'bool'),
                ('analytics', 'text'), ('featured', 'bool'), ('teacher_search', 'bool'), ('featured_jobs', 'n0'), ('campuses_limit', 'n'),
                ('virtual_tour', 'bool'), ('ad_credit_days', 'days'), ('newsletter_feature', 'bool'), ('podcast_feature', 'bool'),
                ('webinar_partner', 'bool'), ('event_discount_pct', 'off'), ('account_manager', 'bool'), ('priority_support', 'bool')]
SCHOOL_ONLY = {'teacher_search', 'featured_jobs', 'campuses_limit', 'virtual_tour'}
VENDOR_ONLY = {'products_limit', 'commission_pct', 'webinar_partner'}

def comparison(tiers):
    """Rows for the Basic/Plus/Pro comparison table: [(label, [(display, included_bool), ...]), ...]."""
    fam = tiers[0]['family'] if tiers else 'school'
    out = []
    for key, kind in COMPARE_ROWS:
        if fam == 'school' and key in VENDOR_ONLY: continue
        if fam == 'vendor' and key in SCHOOL_ONLY: continue
        cells = []
        for p in tiers:
            gr = p['grants']; v = gr.get(key, NONE.get(key)); present = key in gr
            if kind == 'bool': cells.append(('✓' if v else '—', bool(v)))
            elif kind == 'n': cells.append(('Unlimited' if (present and v is None) else (str(v) if v else '—'), bool(v) or (present and v is None)))
            elif kind == 'n0': cells.append((str(v) if v else '—', bool(v)))
            elif kind == 'pct': cells.append((f'{v}%' if v is not None else '—', True))
            elif kind == 'off': cells.append((f'{v}% off' if v else '—', bool(v)))
            elif kind == 'days': cells.append((f'{v} days' if v else '—', bool(v)))
            else: cells.append(((v or '—').capitalize() if v != 'none' else '—', v not in (None, 'none')))
        if any(c[1] for c in cells): out.append((FEATURE_LABELS.get(key, key), cells))
    return out
