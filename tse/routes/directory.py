from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from ..db import db
from ..lib import forms as F, listings as L, consent, crm, notify
from ..lib.auth import login_required
from ..lib.security import limited, audit

bp = Blueprint('directory', __name__)

GROUPS = {
  'schools': ('Schools', 'Regular, pre-schools, alternative, inclusive, special and online schools across India. Basic details are free; verified detailed profiles via Ask The School Expert.'),
  'learning': ('Tutors, Courses, Classes & Training', 'Online tutoring institutions and individual tutors, hobby & enrichment classes, course providers, skill development, teacher-training institutes and education consultants.'),
  'vendors': ('Education Partners & Vendors', 'EdTech, publishers, school infrastructure, transport and uniform & stationery vendors — for schools.'),
  'experts': ('Experts', 'Mental-health professionals, behaviour consultants, special educators, career counsellors, curriculum experts and fee-financing partners.'),
}

def _visible_to(cat):
    """Who may browse a category directly (journeys): experts are reached via Ask The School Expert."""
    u = g.user
    t = u['account_type'] if u else 'guest'
    if t in ('admin', 'staff'): return True
    if t == 'organisation': return cat['school_access'] in ('browse', 'detailed_free')
    return cat['parent_access'] == 'browse'

@bp.route('/directory/<grp>')
def group(grp):
    if grp not in GROUPS: abort(404)
    if grp == 'experts' and not (g.user and g.user['account_type'] in ('admin', 'staff')):
        return redirect(url_for('ask.index'))
    cats = db.all("""SELECT c.*, (SELECT count(*) FROM listings l WHERE l.category = c.slug AND l.is_published) n
                     FROM categories c WHERE c.grp = %s AND c.listed ORDER BY c.sort, c.label""", grp)
    q = request.args.get('q', '').strip()[:100]; city = request.args.get('city', '').strip()[:60]
    page = max(1, request.args.get('page', 1, type=int))
    rows, total = L.search(grp=grp, q=q or None, city=city or None, limit=24, offset=(page - 1) * 24)
    cities = [r['city'] for r in db.all("""SELECT DISTINCT l.city FROM listings l JOIN categories c ON c.slug = l.category
                                           WHERE c.grp = %s AND l.is_published AND l.city <> '' ORDER BY 1""", grp)]
    title, sub = GROUPS[grp]
    return render_template('directory/group.html', grp=grp, title=title, sub=sub, cats=cats, rows=rows, total=total, page=page,
                           q=q, city=city, cities=cities, restricted=(grp == 'vendors' and not (g.user and g.user['account_type'] in ('organisation', 'admin', 'staff'))))

@bp.route('/c/<slug>')
def category(slug):
    cat = db.one('SELECT * FROM categories WHERE slug = %s AND listed', slug) or abort(404)
    if cat['grp'] == 'experts' and not (g.user and g.user['account_type'] in ('admin', 'staff')):
        return redirect(url_for('ask.index', topic=slug))
    defn = F.get(slug)
    facets = F.filter_facets(defn)
    args = {k: v for k, v in request.args.items() if k != 'page' and v}
    q = args.get('q'); city = args.get('city'); state = args.get('state'); board = args.get('board'); tag = args.get('tag')
    page = max(1, request.args.get('page', 1, type=int))
    rows, total = L.search(category=slug, q=q, city=city, state=state, board=board, tag=tag, verified_only=bool(args.get('verified')),
                           sort=args.get('sort', 'relevance'), limit=24, offset=(page - 1) * 24)
    cities = [r['city'] for r in db.all("SELECT DISTINCT city FROM listings WHERE category = %s AND is_published AND city <> '' ORDER BY 1", slug)]
    boards = [r['b'] for r in db.all('SELECT DISTINCT unnest(boards) b FROM listings WHERE category = %s AND is_published ORDER BY 1', slug)]
    detailed_count = db.val("SELECT count(*) FROM listings WHERE category = %s AND is_published AND tier IN ('detailed','featured')", slug)
    return render_template('directory/category.html', cat=cat, defn=defn, facets=facets, rows=rows, total=total, page=page, args=args,
                           cities=cities, boards=boards, states=F.INDIAN_STATES, detailed_count=detailed_count, browse_ok=_visible_to(cat))

@bp.route('/l/<slug>')
def listing(slug):
    l = db.one("""SELECT l.*, c.label AS category_label, c.grp, c.entity FROM listings l JOIN categories c ON c.slug = l.category WHERE l.slug = %s""", slug) or abort(404)
    owner = g.user and ((l['org_id'] and any(o['id'] == l['org_id'] for o in g.orgs)) or l['user_id'] == g.user['id'])
    if not l['is_published'] and not owner and not (g.user and g.user['account_type'] in ('admin', 'staff')): abort(404)
    with db.elevated():   # trusted projection: only fields the viewer is entitled to are rendered below
        reg = db.one('SELECT id, answers, files FROM registrations WHERE id = %s', l['registration_id'])
    defn = F.get(l['category'])
    answers = reg['answers'] if reg else {}
    files = reg['files'] if reg else {}
    can_detail = L.can_view_detailed(g.user, l)
    # entitled viewers see public + detailed fields together, section by section (detailed rows marked); others see public only
    public_secs = F.profile_sections(defn, answers, files, ('public', 'detailed') if can_detail else ('public',))
    detail_secs = []
    teaser = F.profile_sections(defn, answers, files, ('detailed',))[:2] if not can_detail else []
    contact = {}
    if can_detail:
        for role in ('phone', 'whatsapp', 'email', 'website'):
            f = F.field_by_role(defn, role)
            if f and f.get('visibility') != 'private' and answers.get(f['key']): contact[role] = answers[f['key']]
    media = db.all('SELECT * FROM listing_media WHERE listing_id = %s ORDER BY sort, id', l['id'])
    reviews = db.all("""SELECT r.*, u.name AS user_name FROM reviews r LEFT JOIN users u ON u.id = r.user_id
                        WHERE r.listing_id = %s AND r.status = 'published' ORDER BY r.created_at DESC LIMIT 20""", l['id'])
    jobs = db.all("SELECT * FROM jobs WHERE org_id = %s AND status = 'published' ORDER BY published_at DESC", l['org_id']) if l['org_id'] else []
    unlocked = g.user and db.val('SELECT 1 FROM unlocks WHERE user_id = %s AND listing_id = %s', g.user['id'], l['id'])
    can_review = bool(unlocked) and g.user['account_type'] == 'parent' and not db.val('SELECT 1 FROM reviews WHERE listing_id = %s AND user_id = %s', l['id'], g.user['id'])
    pack = None
    if g.user and g.user['account_type'] == 'parent' and not unlocked:
        pack = db.one("""SELECT * FROM unlock_packs WHERE user_id = %s AND used < quota AND expires_at > now()
                         AND lower(city) = lower(%s) ORDER BY expires_at LIMIT 1""", g.user['id'], l['city'] or '')
    org = db.one('SELECT founding_partner FROM organisations WHERE id = %s', l['org_id']) if l['org_id'] else None
    campuses = db.all('SELECT slug, name, city FROM listings WHERE org_id = %s AND id <> %s AND is_published', l['org_id'], l['id']) if l['org_id'] and l['grp'] == 'schools' else []
    from ..lib import entitlements as E
    lent = E.for_org(l['org_id']) if l['org_id'] else dict(E.NONE)
    if not owner:
        db.run('UPDATE listings SET view_count = view_count + 1 WHERE id = %s', l['id']); E.bump_stat(l['id'], 'views')
    return render_template('directory/listing.html', l=l, defn=defn, public_secs=public_secs, detail_secs=detail_secs, teaser=teaser,
                           can_detail=can_detail, contact=contact, media=media, reviews=reviews, jobs=jobs, unlocked=unlocked, can_review=can_review,
                           pack=pack, owner=owner, org=org, campuses=campuses, n_lead=consent.notice('lead_sharing'), lent=lent,
                           tier_name=E.tier_label(lent['level']))

@bp.route('/l/<slug>/unlock', methods=['POST'])
@login_required
def unlock(slug):
    l = db.one('SELECT * FROM listings WHERE slug = %s AND is_published', slug) or abort(404)
    if l['tier'] not in ('detailed', 'featured'):
        flash('This school has not published a detailed profile yet. Ask The School Expert and we will try to help.', 'info')
        return redirect(url_for('directory.listing', slug=slug))
    with db.transaction():
        pack = db.one("""SELECT * FROM unlock_packs WHERE user_id = %s AND used < quota AND expires_at > now()
                         AND lower(city) = lower(%s) ORDER BY expires_at LIMIT 1 FOR UPDATE""", g.user['id'], l['city'] or '')
        if not pack:
            flash('Buy an Ask The School Expert pack for this locality to unlock detailed views.', 'info')
            return redirect(url_for('ask.schools', city=l['city']))
        if not db.val('SELECT 1 FROM unlocks WHERE user_id = %s AND listing_id = %s', g.user['id'], l['id']):
            db.insert('unlocks', dict(user_id=g.user['id'], listing_id=l['id'], pack_id=pack['id']), returning=None)
            db.run('UPDATE unlock_packs SET used = used + 1 WHERE id = %s', pack['id'])
            from ..lib import entitlements as E; E.bump_stat(l['id'], 'unlocks')
    audit('listing.unlocked', 'listing', l['id'])
    flash(f"Unlocked! You have {pack['quota'] - pack['used'] - 1} detailed views left in {pack['city']}.", 'success')
    return redirect(url_for('directory.listing', slug=slug))

@bp.route('/l/<slug>/contact', methods=['POST'])
@login_required
@limited(10, 3600, 'lead')
def contact(slug):
    l = db.one('SELECT * FROM listings WHERE slug = %s AND is_published', slug) or abort(404)
    from ..lib import entitlements as E
    if not L.can_view_detailed(g.user, l) or not E.for_org(l['org_id']).get('leads'):
        abort(403)
    if not request.form.get('consent'):
        flash('Please agree to share your details with this organisation.', 'error'); return redirect(url_for('directory.listing', slug=slug))
    cid = consent.record('lead_sharing', True, user_id=g.user['id'], context=f'listing:{l["id"]}')
    lid = db.insert('leads', dict(listing_id=l['id'], org_id=l['org_id'], source='unlock_contact' if g.user['account_type'] == 'parent' else 'enquiry',
                    user_id=g.user['id'], name=g.user['name'], email=g.user['email'], phone=request.form.get('phone') or g.user['phone'],
                    message=request.form.get('message', '')[:2000], verified=bool(g.user['email_verified_at']), consent_id=cid))
    E.bump_stat(l['id'], 'leads')
    crm.emit('lead.created', {'lead_id': lid, 'listing': l['name'], 'org_id': l['org_id'], 'name': g.user['name'], 'email': g.user['email'],
             'phone': request.form.get('phone') or g.user['phone'], 'city': l['city'], 'source': 'directory'})
    if l['org_id']: notify.notify_org(l['org_id'], 'New verified enquiry', f"{g.user['name']} contacted {l['name']}.", '/dashboard/leads')
    elif l['user_id']: notify.notify(l['user_id'], 'New enquiry', f"{g.user['name']} contacted you.", '/dashboard/leads', mail=True)
    flash('Your enquiry has been sent. The organisation will contact you directly.', 'success')
    return redirect(url_for('directory.listing', slug=slug))

@bp.route('/l/<slug>/review', methods=['POST'])
@login_required
def review(slug):
    l = db.one('SELECT * FROM listings WHERE slug = %s AND is_published', slug) or abort(404)
    if g.user['account_type'] != 'parent' or not db.val('SELECT 1 FROM unlocks WHERE user_id = %s AND listing_id = %s', g.user['id'], l['id']):
        flash('Only parents who have unlocked this school can leave a verified review.', 'error'); return redirect(url_for('directory.listing', slug=slug))
    rating = request.form.get('rating', type=int)
    if not rating or not 1 <= rating <= 5: abort(400)
    from ..lib import moderation
    ok, reason = moderation.check(request.form.get('body', ''))
    db.run("""INSERT INTO reviews (listing_id, user_id, rating, title, body, verified, status) VALUES (%s,%s,%s,%s,%s,true,%s)
              ON CONFLICT (listing_id, user_id) DO NOTHING""", l['id'], g.user['id'], rating, request.form.get('title', '')[:120],
           request.form.get('body', '')[:3000], 'published' if ok else 'pending')
    recompute_rating(l['id'])
    flash('Thank you for your verified review.' if ok else 'Thank you — your review will appear after a quick moderation check.', 'success')
    return redirect(url_for('directory.listing', slug=slug))

def recompute_rating(lid):
    db.run("""UPDATE listings SET rating_avg = COALESCE((SELECT avg(rating) FROM reviews WHERE listing_id = %s AND status = 'published'), 0),
              rating_count = (SELECT count(*) FROM reviews WHERE listing_id = %s AND status = 'published') WHERE id = %s""", lid, lid, lid)

@bp.route('/l/<slug>/claim-media')
def _noop(slug):
    abort(404)
