from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from ..db import db
from ..lib import moderation as M, consent, notify, storage
from ..lib.auth import login_required, roles, is_staff
from ..lib.security import limited, audit

bp = Blueprint('community', __name__)

def _role():
    return g.user['account_type'] if g.user else 'guest'

def _community(slug):
    c = db.one('SELECT * FROM communities WHERE slug = %s', slug) or abort(404)
    return c

def _can_view(c): return is_staff() or _role() in c['view_roles']
def _can_post(c): return bool(g.user) and (is_staff() or _role() in c['post_roles']) and not M.is_banned(g.user['id'])

@bp.route('/community')
def index():
    rows = db.all("""SELECT c.*, (SELECT count(*) FROM posts p WHERE p.community = c.slug AND p.status = 'published') n FROM communities c ORDER BY sort""")
    return render_template('community/index.html', rows=rows, role=_role())

@bp.route('/community/<slug>')
def view(slug):
    c = _community(slug)
    if not _can_view(c):
        return render_template('community/gate.html', c=c, role=_role()), (401 if not g.user else 403)
    q = request.args.get('q', '').strip()
    posts = db.all(f"""SELECT p.*, u.name AS user_name, u.account_type FROM posts p LEFT JOIN users u ON u.id = p.user_id
                       WHERE p.community = %s AND (p.status = 'published' OR p.user_id = %s) {"AND (p.title ILIKE %s OR p.body ILIKE %s)" if q else ''}
                       ORDER BY p.pinned DESC, p.created_at DESC LIMIT 60""", slug, g.user['id'] if g.user else 0, *([f'%{q}%'] * 2 if q else []))
    return render_template('community/view.html', c=c, posts=posts, can_post=_can_post(c), q=q, notice=consent.notice('community'))

@bp.route('/community/<slug>/post', methods=['POST'])
@login_required
@limited(10, 3600, 'post')
def post(slug):
    c = _community(slug)
    if not _can_post(c): abort(403)
    title = request.form.get('title', '').strip()[:160]; body = request.form.get('body', '').strip()[:8000]
    if len(title) < 5 or len(body) < 10:
        flash('Please add a clear title and a few lines of detail.', 'error'); return redirect(url_for('community.view', slug=slug))
    if not request.form.get('guidelines'):
        flash('Please confirm you follow the community guidelines.', 'error'); return redirect(url_for('community.view', slug=slug))
    ok, reason = M.check(title + '\n' + body, g.user['id'])
    att = None
    if request.files.get('attachment') and request.files['attachment'].filename:
        try: att = storage.save(request.files['attachment'], folder='community', kinds=('image', 'doc'))['url']
        except storage.UploadError as e: flash(str(e), 'error'); return redirect(url_for('community.view', slug=slug))
    status = 'pending' if (not ok or c['premoderate']) else 'published'
    pid = db.insert('posts', dict(community=slug, user_id=g.user['id'], title=title, body=body, kind=request.form.get('kind', 'discussion')[:20],
                    attachment_url=att, status=status, moderation_reason=reason))
    consent.record('community', True, user_id=g.user['id'], context=f'post:{pid}')
    if status == 'pending':
        notify.notify_staff('Post held for review', f'{reason or "Pre-moderated community"}: {title}', '/admin/moderation')
        flash(f'Thanks! Your post is waiting for a quick moderator check. Reason: {reason or "this community is pre-moderated"}.', 'warning')
    else:
        flash('Posted.', 'success')
    return redirect(url_for('community.thread', slug=slug, pid=pid))

@bp.route('/community/<slug>/<int:pid>')
def thread(slug, pid):
    c = _community(slug)
    if not _can_view(c): return render_template('community/gate.html', c=c, role=_role()), 403
    p = db.one("""SELECT p.*, u.name AS user_name, u.account_type FROM posts p LEFT JOIN users u ON u.id = p.user_id WHERE p.id = %s AND p.community = %s""", pid, slug) or abort(404)
    if p['status'] != 'published' and not (g.user and (p['user_id'] == g.user['id'] or is_staff())): abort(404)
    comments = db.all("""SELECT cm.*, u.name AS user_name FROM comments cm LEFT JOIN users u ON u.id = cm.user_id
                         WHERE cm.post_id = %s AND (cm.status = 'published' OR cm.user_id = %s) ORDER BY cm.created_at""", pid, g.user['id'] if g.user else 0)
    return render_template('community/thread.html', c=c, p=p, comments=comments, can_post=_can_post(c))

@bp.route('/community/<slug>/<int:pid>/comment', methods=['POST'])
@login_required
@limited(30, 3600, 'comment')
def comment(slug, pid):
    c = _community(slug)
    if not _can_post(c) or not c['allow_comments']: abort(403)
    p = db.one("SELECT * FROM posts WHERE id = %s AND status = 'published'", pid) or abort(404)
    body = request.form.get('body', '').strip()[:3000]
    if len(body) < 2: return redirect(url_for('community.thread', slug=slug, pid=pid))
    ok, reason = M.check(body, g.user['id'])
    db.insert('comments', dict(post_id=pid, user_id=g.user['id'], body=body, status='published' if ok else 'pending', moderation_reason=reason), returning=None)
    db.run("UPDATE posts SET comment_count = (SELECT count(*) FROM comments WHERE post_id = %s AND status = 'published') WHERE id = %s", pid, pid)
    if ok and p['user_id'] != g.user['id']: notify.notify(p['user_id'], 'New reply to your post', p['title'], f'/community/{slug}/{pid}')
    if not ok: flash(f'Your comment is waiting for moderator review ({reason}).', 'warning')
    return redirect(url_for('community.thread', slug=slug, pid=pid))

@bp.route('/report', methods=['POST'])
@login_required
@limited(20, 3600, 'report')
def report():
    t = request.form.get('type'); tid = request.form.get('id', type=int)
    if t not in ('post', 'comment', 'review', 'book_review', 'corner') or not tid: abort(400)
    db.insert('content_reports', dict(target_type=t, target_id=tid, reporter_id=g.user['id'], reason=request.form.get('reason', 'other')[:60],
              details=request.form.get('details', '')[:1000]), returning=None)
    if t in ('post', 'comment'): M.auto_hide(t, tid)
    notify.notify_staff('Content reported', f'{t} #{tid}: {request.form.get("reason")}', '/admin/moderation')
    flash('Thank you. Our moderators will review this.', 'success')
    return redirect(request.referrer or url_for('community.index'))

# ---------- Parents' Corner (submissions only, no discussion) ----------
@bp.route('/parents-corner')
def corner():
    kind = request.args.get('kind')
    rows = db.all(f"""SELECT * FROM corner_submissions WHERE status = 'published' {'AND kind = %s' if kind else ''} ORDER BY created_at DESC LIMIT 60""", *([kind] if kind else []))
    return render_template('community/corner.html', rows=rows, kind=kind)

@bp.route('/parents-corner/<int:sid>')
def corner_item(sid):
    s = db.one("SELECT * FROM corner_submissions WHERE id = %s AND status = 'published'", sid) or abort(404)
    return render_template('community/corner_item.html', s=s)

@bp.route('/parents-corner/submit', methods=['GET', 'POST'])
@roles('parent')
@limited(5, 3600, 'corner')
def corner_submit():
    if request.method == 'POST':
        f = request.form
        if f.get('kind') not in ('craft_project', 'model_tutorial', 'activity_idea') or len(f.get('title', '')) < 4 or len(f.get('steps', '')) < 20:
            flash('Please choose a type, add a title and describe the steps.', 'error'); return render_template('community/corner_submit.html', f=f)
        media = None
        if request.files.get('media') and request.files['media'].filename:
            try: media = storage.save(request.files['media'], folder='corner', kinds=('image',))['url']
            except storage.UploadError as e: flash(str(e), 'error'); return render_template('community/corner_submit.html', f=f)
        if not f.get('no_child'):
            flash('Please confirm the photo/text does not show or name any child.', 'error'); return render_template('community/corner_submit.html', f=f)
        db.insert('corner_submissions', dict(user_id=g.user['id'], kind=f['kind'], title=f['title'][:160], grade=f.get('grade', '')[:40],
                  materials=f.get('materials', '')[:2000], steps=f['steps'][:8000], media_url=media), returning=None)
        notify.notify_staff("Parents' Corner submission", f['title'], '/admin/moderation')
        flash('Thank you! Your submission will appear after review.', 'success')
        return redirect(url_for('community.corner'))
    return render_template('community/corner_submit.html', f={})
