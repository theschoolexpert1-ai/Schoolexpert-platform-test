"""Podcasts & webinars, gallery, industry newsletter, NewsWorms, Book Club, Homeschoolers Hub, resources."""
import datetime, secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, current_app, send_from_directory
from ..db import db
from ..lib import payments, consent, notify, crm, moderation, storage
from ..lib.auth import login_required, roles, is_staff
from ..lib.security import limited

bp = Blueprint('content', __name__)

# ---------- podcasts & webinars ----------
@bp.route('/podcasts')
def podcasts():
    kind = request.args.get('kind') if request.args.get('kind') in ('podcast', 'webinar') else None
    rows = db.all(f"SELECT * FROM podcasts WHERE status = 'published' {'AND kind = %s' if kind else ''} ORDER BY published_at DESC NULLS LAST LIMIT 60", *([kind] if kind else []))
    upcoming = db.all("SELECT * FROM events WHERE kind = 'webinar' AND status = 'published' AND starts_at > now() ORDER BY starts_at LIMIT 3")
    return render_template('content/podcasts.html', rows=rows, kind=kind, upcoming=upcoming)

@bp.route('/podcasts/<slug>')
def podcast(slug):
    p = db.one("SELECT * FROM podcasts WHERE slug = %s AND status = 'published'", slug) or abort(404)
    qs = db.all("""SELECT q.*, u.name AS user_name FROM podcast_questions q LEFT JOIN users u ON u.id = q.user_id
                   WHERE q.podcast_id = %s AND q.status IN ('answered','published') ORDER BY q.created_at DESC""", p['id'])
    embed = None
    if p['media_url']:
        u = p['media_url']
        if 'youtube.com/watch?v=' in u: embed = 'https://www.youtube-nocookie.com/embed/' + u.split('v=')[1].split('&')[0]
        elif 'youtu.be/' in u: embed = 'https://www.youtube-nocookie.com/embed/' + u.split('youtu.be/')[1].split('?')[0]
        elif 'open.spotify.com/episode/' in u: embed = u.replace('/episode/', '/embed/episode/')
    more = db.all("SELECT * FROM podcasts WHERE status = 'published' AND id <> %s ORDER BY published_at DESC LIMIT 3", p['id'])
    return render_template('content/podcast.html', p=p, qs=qs, embed=embed, more=more)

@bp.route('/podcasts/<slug>/ask', methods=['POST'])
@login_required
@limited(5, 3600, 'pq')
def podcast_ask(slug):
    p = db.one("SELECT * FROM podcasts WHERE slug = %s", slug) or abort(404)
    q = request.form.get('question', '').strip()[:1000]
    if len(q) < 10: flash('Please write your question in a sentence or two.', 'error'); return redirect(url_for('content.podcast', slug=slug))
    db.insert('podcast_questions', dict(podcast_id=p['id'], user_id=g.user['id'], question=q), returning=None)
    notify.notify_staff('New podcast question', q[:120], '/admin/podcast-questions')
    flash('Thanks! Your question has been sent to our guests — answers appear here and in future episodes.', 'success')
    return redirect(url_for('content.podcast', slug=slug))

# ---------- gallery ----------
@bp.route('/gallery')
def gallery():
    rows = db.all("""SELECT a.*, (SELECT count(*) FROM gallery_photos p WHERE p.album_id = a.id) n,
                     COALESCE(a.cover_url, (SELECT url FROM gallery_photos p WHERE p.album_id = a.id ORDER BY sort, id LIMIT 1)) cover
                     FROM gallery_albums a WHERE a.published ORDER BY a.taken_on DESC NULLS LAST, a.id DESC""")
    return render_template('content/gallery.html', rows=rows)

@bp.route('/gallery/<slug>')
def album(slug):
    a = db.one('SELECT * FROM gallery_albums WHERE slug = %s AND published', slug) or abort(404)
    photos = db.all('SELECT * FROM gallery_photos WHERE album_id = %s ORDER BY sort, id', a['id'])
    return render_template('content/album.html', a=a, photos=photos)

# ---------- newsletters ----------
def _subscribe(kind, email, paid_until=None):
    tok = secrets.token_urlsafe(20)
    db.run("""INSERT INTO newsletter_subscriptions (kind, email, user_id, status, confirm_token, paid_until) VALUES (%s,%s,%s,%s,%s,%s)
              ON CONFLICT (kind, email) DO UPDATE SET confirm_token = EXCLUDED.confirm_token, paid_until = COALESCE(EXCLUDED.paid_until, newsletter_subscriptions.paid_until),
              status = CASE WHEN newsletter_subscriptions.status = 'active' THEN 'active' ELSE EXCLUDED.status END""",
           kind, email, g.user['id'] if g.user else None, 'active' if paid_until else 'pending', tok, paid_until)
    return tok

@bp.route('/newsletter')
def newsletter():
    rows = db.all("SELECT * FROM newsletters WHERE kind = 'industry' AND published_at IS NOT NULL ORDER BY published_at DESC LIMIT 40")
    return render_template('content/newsletter.html', rows=rows, notice=consent.notice('marketing'))

@bp.route('/newsletter/subscribe', methods=['POST'])
@limited(5, 600, 'nl')
def subscribe():
    kind = request.form.get('kind') if request.form.get('kind') in ('industry', 'newsworms') else 'industry'
    email = request.form.get('email', '').strip().lower()
    if '@' not in email or not request.form.get('consent'):
        flash('Enter your email and accept the notice.', 'error'); return redirect(request.referrer or url_for('content.newsletter'))
    tok = _subscribe(kind, email)
    consent.record('marketing', True, user_id=g.user['id'] if g.user else None, email=email, context=f'newsletter:{kind}')
    link = f"{current_app.config['SITE_URL']}{url_for('content.confirm', token=tok)}"
    notify.email(email, 'Confirm your subscription — The School Expert™', f'Please confirm your subscription: {link}\n\nUnsubscribe any time from the link in every issue.')
    crm.emit('newsletter.subscribed', {'email': email, 'kind': kind})
    if current_app.config['DEV_SHOW_OTP']: flash(f'Development mode: confirm link {link}', 'info')
    flash('Almost done — please confirm from the email we just sent.', 'success')
    return redirect(request.referrer or url_for('content.newsletter'))

@bp.route('/newsletter/confirm/<token>')
def confirm(token):
    n = db.run("UPDATE newsletter_subscriptions SET status = 'active' WHERE confirm_token = %s", token)
    flash('Subscription confirmed. Thank you!' if n else 'This link is invalid.', 'success' if n else 'error')
    return redirect(url_for('content.newsletter'))

@bp.route('/newsletter/unsubscribe/<token>')
def unsubscribe(token):
    db.run("UPDATE newsletter_subscriptions SET status = 'unsubscribed' WHERE confirm_token = %s", token)
    flash('You have been unsubscribed.', 'success'); return redirect(url_for('public.home'))

@bp.route('/newsletter/<slug>')
def issue(slug):
    n = db.one('SELECT * FROM newsletters WHERE slug = %s AND published_at IS NOT NULL', slug) or abort(404)
    locked = n['access'] == 'subscriber' and not _newsworms_active()
    return render_template('content/issue.html', n=n, locked=locked)

def _newsworms_active():
    if not g.user: return False
    if is_staff(): return True
    return bool(db.val("SELECT 1 FROM newsletter_subscriptions WHERE kind = 'newsworms' AND user_id = %s AND status = 'active' AND paid_until >= current_date", g.user['id']))

@bp.route('/newsworms')
def newsworms():
    rows = db.all("SELECT * FROM newsletters WHERE kind = 'newsworms' AND published_at IS NOT NULL ORDER BY published_at DESC LIMIT 40")
    return render_template('content/newsworms.html', rows=rows, active=_newsworms_active(), plan=db.one("SELECT * FROM plans WHERE code = 'newsworms_annual'"))

@bp.route('/subscribe/<code>', methods=['POST'])
@roles('parent', 'teacher', 'organisation')
def buy_subscription(code):
    p = db.one("SELECT * FROM plans WHERE code = %s AND active AND stream = 'product_subscription'", code) or abort(404)
    o = payments.create_order('subscription', p['name'], p['price_paise'], user_id=g.user['id'], meta={'plan': code},
                              items=[{'title': p['name'], 'qty': 1, 'unit_paise': p['price_paise']}])
    return redirect(url_for('pay.checkout', public_id=o['public_id']))

@payments.fulfiller('subscription')
def _fulfil_sub(order):
    p = db.one('SELECT * FROM plans WHERE code = %s', order['meta']['plan'])
    until = datetime.date.today() + datetime.timedelta(days=365)
    db.insert('subscriptions', dict(user_id=order['user_id'], plan_code=p['code'], ends_at=until, order_id=order['id']), returning=None)
    u = db.one('SELECT email FROM users WHERE id = %s', order['user_id'])
    if p['grants'].get('newsworms'):
        g_user = None
        db.run("""INSERT INTO newsletter_subscriptions (kind, email, user_id, status, paid_until, confirm_token) VALUES ('newsworms', %s, %s, 'active', %s, %s)
                  ON CONFLICT (kind, email) DO UPDATE SET status = 'active', paid_until = EXCLUDED.paid_until, user_id = EXCLUDED.user_id""",
               u['email'], order['user_id'], until, secrets.token_urlsafe(20))
    if p['grants'].get('bookclub'):
        db.run("""INSERT INTO club_memberships (user_id, club) VALUES (%s, 'bookclub') ON CONFLICT (user_id, club) DO UPDATE SET status = 'active'""", order['user_id'])
    notify.notify(order['user_id'], f"{p['name']} is active", 'Thank you for subscribing!', '/dashboard/subscriptions', mail=True)

# ---------- Book club ----------
@bp.route('/bookclub')
def bookclub():
    band = request.args.get('age')
    books = db.all(f"SELECT * FROM books {'WHERE age_band = %s' if band else ''} ORDER BY rating_count DESC, title LIMIT 60", *([band] if band else []))
    sessions = db.all("SELECT * FROM events WHERE kind IN ('storytelling','bookclub') AND status = 'published' AND starts_at > now() ORDER BY starts_at LIMIT 6")
    bands = [r['age_band'] for r in db.all('SELECT DISTINCT age_band FROM books WHERE age_band IS NOT NULL ORDER BY 1')]
    member = g.user and db.val("SELECT 1 FROM club_memberships WHERE user_id = %s AND club = 'bookclub' AND status = 'active'", g.user['id'])
    return render_template('content/bookclub.html', books=books, sessions=sessions, bands=bands, band=band, member=member,
                           plan=db.one("SELECT * FROM plans WHERE code = 'bookclub_annual'"))

@bp.route('/bookclub/join', methods=['POST'])
@roles('parent')
def bookclub_join():
    db.run("""INSERT INTO club_memberships (user_id, club, age_band) VALUES (%s, 'bookclub-free', %s) ON CONFLICT (user_id, club) DO UPDATE SET age_band = EXCLUDED.age_band""",
           g.user['id'], request.form.get('age_band', '')[:20])
    flash('Welcome to The EverHungry Bookworms! You will receive reading lists and session invitations.', 'success')
    return redirect(url_for('content.bookclub'))

@bp.route('/bookclub/<slug>')
def book(slug):
    b = db.one('SELECT * FROM books WHERE slug = %s', slug) or abort(404)
    reviews = db.all("""SELECT r.*, u.name AS user_name FROM book_reviews r LEFT JOIN users u ON u.id = r.user_id
                        WHERE r.book_id = %s AND r.status = 'published' ORDER BY r.created_at DESC""", b['id'])
    mine = g.user and db.one('SELECT * FROM book_reviews WHERE book_id = %s AND user_id = %s', b['id'], g.user['id'])
    product = db.one("SELECT * FROM products WHERE id = %s AND status = 'published'", b['marketplace_product_id']) if b['marketplace_product_id'] else None
    return render_template('content/book.html', b=b, reviews=reviews, mine=mine, product=product)

@bp.route('/bookclub/<slug>/review', methods=['POST'])
@roles('parent', 'teacher')
@limited(10, 3600, 'bookrev')
def book_review(slug):
    b = db.one('SELECT * FROM books WHERE slug = %s', slug) or abort(404)
    rating = request.form.get('rating', type=int)
    if not rating or not 1 <= rating <= 5: abort(400)
    body = request.form.get('body', '')[:3000]
    ok, reason = moderation.check(body, g.user['id'])
    db.run("""INSERT INTO book_reviews (book_id, user_id, rating, body, status) VALUES (%s,%s,%s,%s,%s)
              ON CONFLICT (book_id, user_id) DO UPDATE SET rating = EXCLUDED.rating, body = EXCLUDED.body, status = EXCLUDED.status""",
           b['id'], g.user['id'], rating, body, 'published' if ok else 'pending')
    db.run("""UPDATE books SET rating_avg = COALESCE((SELECT avg(rating) FROM book_reviews WHERE book_id = %s AND status = 'published'),0),
              rating_count = (SELECT count(*) FROM book_reviews WHERE book_id = %s AND status = 'published') WHERE id = %s""", b['id'], b['id'], b['id'])
    flash('Thank you for your review!' if ok else 'Thanks — your review will appear after moderation.', 'success')
    return redirect(url_for('content.book', slug=slug))

# ---------- Homeschoolers Hub ----------
@bp.route('/homeschoolers-hub')
def homeschool():
    meetups = db.all("SELECT * FROM events WHERE kind = 'homeschool_meetup' AND status = 'published' AND starts_at > now() ORDER BY starts_at LIMIT 12")
    resources = db.all("SELECT * FROM resources WHERE kind = 'homeschool' AND published ORDER BY created_at DESC LIMIT 24")
    apps = db.all("SELECT * FROM resources WHERE kind = 'learning_app' AND published ORDER BY is_free DESC, title LIMIT 24")
    posts = db.all("SELECT * FROM posts WHERE community = 'homeschoolers' AND status = 'published' ORDER BY created_at DESC LIMIT 5")
    alt_schools = db.all("""SELECT l.*, c.label AS category_label FROM listings l JOIN categories c ON c.slug = l.category WHERE l.is_published
                            AND l.category = 'alternative-school' AND 'Homeschool Support Centre' = ANY(l.tags) LIMIT 6""")
    return render_template('content/homeschool.html', meetups=meetups, resources=resources, apps=apps, posts=posts, alt_schools=alt_schools)

# ---------- resources & downloads ----------
@bp.route('/resources')
def resources():
    kind = request.args.get('kind'); grade = request.args.get('grade')
    where = ['published', "kind IN ('worksheet','kids_newspaper','guide','teacher_resource')"]; args = []
    if kind: where.append('kind = %s'); args.append(kind)
    if grade: where.append('grade = %s'); args.append(grade)
    rows = db.all(f"SELECT * FROM resources WHERE {' AND '.join(where)} ORDER BY grade NULLS LAST, title LIMIT 200", *args)
    grades = [r['grade'] for r in db.all("SELECT DISTINCT grade FROM resources WHERE grade IS NOT NULL AND published ORDER BY 1")]
    return render_template('content/resources.html', rows=rows, kind=kind, grade=grade, grades=grades)

@bp.route('/resources/<slug>/download')
def download(slug):
    r = db.one('SELECT * FROM resources WHERE slug = %s AND published', slug) or abort(404)
    if not r['is_free'] and not (g.user and (is_staff() or _newsworms_active())):
        flash('This download is for subscribers.', 'info'); return redirect(url_for('content.newsworms'))
    db.run('UPDATE resources SET downloads = downloads + 1 WHERE id = %s', r['id'])
    return redirect(r['file_url'] or r['external_url'] or url_for('content.resources'))
