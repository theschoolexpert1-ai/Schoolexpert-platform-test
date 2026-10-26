from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort
from ..db import db
from ..lib import payments, notify
from ..lib.auth import login_required, is_staff

bp = Blueprint('marketplace', __name__)

CATEGORIES = ['The School Expert™ Products', 'Books', 'Learning Materials', 'Stationery', 'Art & Craft', 'School Bags', 'Shoes', 'Uniforms', 'STEM & Robotics Kits', 'Classroom Supplies', 'Digital Downloads']
FREE_SHIPPING_PAISE = 99900; SHIPPING_PAISE = 7900

def unit_price(p, qty):
    price = p['price_paise']
    for t in sorted(p['bulk_tiers'] or [], key=lambda t: t['min_qty']):
        if qty >= t['min_qty']: price = t['price_paise']
    return price

@bp.route('/marketplace')
def index():
    a = request.args; where = ["p.status = 'published'"]; args = []
    if a.get('cat'): where.append('p.category = %s'); args.append(a['cat'])
    if a.get('q'): where.append('(p.title ILIKE %s OR p.summary ILIKE %s)'); args += [f"%{a['q']}%"] * 2
    if a.get('seller') == 'tse': where.append('p.is_tse')
    order = {'price_asc': 'p.price_paise', 'price_desc': 'p.price_paise DESC', 'new': 'p.created_at DESC'}.get(a.get('sort'), 'p.is_tse DESC, p.created_at DESC')
    rows = db.all(f"""SELECT p.*, o.name AS seller_name FROM products p LEFT JOIN organisations o ON o.id = p.seller_org_id
                      WHERE {' AND '.join(where)} ORDER BY {order} LIMIT 120""", *args)
    counts = {r['category']: r['n'] for r in db.all("SELECT category, count(*) n FROM products WHERE status = 'published' GROUP BY category")}
    return render_template('marketplace/index.html', rows=rows, cats=CATEGORIES, counts=counts, a=a)

@bp.route('/marketplace/p/<slug>')
def product(slug):
    p = db.one("""SELECT p.*, o.name AS seller_name, l.slug AS seller_slug FROM products p LEFT JOIN organisations o ON o.id = p.seller_org_id
                  LEFT JOIN listings l ON l.org_id = o.id WHERE p.slug = %s""", slug) or abort(404)
    if p['status'] != 'published' and not is_staff() and not (g.org and g.org['id'] == p['seller_org_id']): abort(404)
    related = db.all("SELECT * FROM products WHERE status = 'published' AND category = %s AND id <> %s LIMIT 4", p['category'], p['id'])
    return render_template('marketplace/product.html', p=p, related=related)

@bp.route('/cart')
@login_required
def cart():
    items = db.all("""SELECT c.*, p.title, p.slug, p.price_paise, p.mrp_paise, p.bulk_tiers, p.stock, p.images, p.status, p.is_digital
                      FROM cart_items c JOIN products p ON p.id = c.product_id WHERE c.user_id = %s ORDER BY c.id""", g.user['id'])
    total = 0
    for it in items:
        it['unit'] = unit_price(it, it['qty']); it['line'] = it['unit'] * it['qty']; total += it['line']
    physical = any(not it['is_digital'] for it in items)
    shipping = 0 if (not physical or total >= FREE_SHIPPING_PAISE) else SHIPPING_PAISE
    addresses = db.all('SELECT * FROM addresses WHERE user_id = %s ORDER BY is_default DESC, id DESC', g.user['id'])
    return render_template('marketplace/cart.html', items=items, total=total, shipping=shipping, addresses=addresses, physical=physical)

@bp.route('/cart/add', methods=['POST'])
@login_required
def add():
    p = db.one("SELECT * FROM products WHERE id = %s AND status = 'published'", request.form.get('product_id', type=int)) or abort(404)
    qty = max(1, min(5000, request.form.get('qty', 1, type=int)))
    if not p['is_digital'] and p['stock'] < qty:
        flash(f"Only {p['stock']} in stock.", 'error'); return redirect(url_for('marketplace.product', slug=p['slug']))
    db.run("""INSERT INTO cart_items (user_id, product_id, qty) VALUES (%s,%s,%s)
              ON CONFLICT (user_id, product_id) DO UPDATE SET qty = LEAST(cart_items.qty + EXCLUDED.qty, 5000)""", g.user['id'], p['id'], qty)
    flash(f"Added {p['title']} to your cart.", 'success')
    return redirect(request.form.get('next') or url_for('marketplace.cart'))

@bp.route('/cart/update', methods=['POST'])
@login_required
def update():
    for k, v in request.form.items():
        if k.startswith('qty_'):
            cid = int(k[4:]); q = int(v or 0)
            if q <= 0: db.run('DELETE FROM cart_items WHERE id = %s AND user_id = %s', cid, g.user['id'])
            else: db.run('UPDATE cart_items SET qty = %s WHERE id = %s AND user_id = %s', min(q, 5000), cid, g.user['id'])
    return redirect(url_for('marketplace.cart'))

@bp.route('/cart/checkout', methods=['POST'])
@login_required
def checkout():
    f = request.form
    items = db.all("""SELECT c.*, p.title, p.price_paise, p.bulk_tiers, p.stock, p.seller_org_id, p.gst_rate, p.is_digital, p.status
                      FROM cart_items c JOIN products p ON p.id = c.product_id WHERE c.user_id = %s""", g.user['id'])
    if not items: return redirect(url_for('marketplace.index'))
    if any(i['status'] != 'published' for i in items): flash('Some items are no longer available.', 'error'); return redirect(url_for('marketplace.cart'))
    physical = any(not i['is_digital'] for i in items)
    address = None
    if physical:
        aid = f.get('address_id', type=int)
        if aid:
            a = db.one('SELECT * FROM addresses WHERE id = %s AND user_id = %s', aid, g.user['id']) or abort(400)
        else:
            need = ['name', 'phone', 'line1', 'city', 'state', 'pincode']
            if any(not f.get(k) for k in need):
                flash('Please add a delivery address with your phone number.', 'error'); return redirect(url_for('marketplace.cart'))
            aid = db.insert('addresses', dict(user_id=g.user['id'], org_id=g.org['id'] if g.org else None, label='School' if g.org else 'Home',
                            **{k: f.get(k, '')[:200] for k in need + ['line2']}))
            a = db.one('SELECT * FROM addresses WHERE id = %s', aid)
        address = {k: a[k] for k in ('name', 'phone', 'line1', 'line2', 'city', 'state', 'pincode')}
    total = 0; lines = []
    for i in items:
        if not i['is_digital'] and i['stock'] < i['qty']:
            flash(f"{i['title']}: only {i['stock']} in stock.", 'error'); return redirect(url_for('marketplace.cart'))
        u = unit_price(i, i['qty']); total += u * i['qty']
        lines.append({'product_id': i['product_id'], 'title': i['title'], 'qty': i['qty'], 'unit_paise': u, 'seller_org_id': i['seller_org_id']})
    shipping = 0 if (not physical or total >= FREE_SHIPPING_PAISE) else SHIPPING_PAISE
    o = payments.create_order('marketplace', f'Marketplace order ({len(items)} items)', total, user_id=g.user['id'], org_id=g.org['id'] if g.org else None,
                              gst_rate=12, inclusive=True, items=lines, address=address, shipping_paise=shipping, meta={'bulk': bool(g.org)})
    return redirect(url_for('pay.checkout', public_id=o['public_id']))

@payments.fulfiller('marketplace')
def _fulfil(order):
    items = db.all('SELECT * FROM order_items WHERE order_id = %s', order['id'])
    for it in items:
        db.run('UPDATE products SET stock = GREATEST(stock - %s, 0) WHERE id = %s AND NOT is_digital', it['qty'], it['product_id'])
    db.run('DELETE FROM cart_items WHERE user_id = %s', order['user_id'])
    from ..lib import entitlements as E
    for it in items:   # platform commission by the seller's tier (Basic 15% / Plus 10% / Pro 7%)
        if not it['seller_org_id']: continue
        pct = E.for_org(it['seller_org_id']).get('commission_pct', 20)
        gross = it['unit_paise'] * it['qty']; comm = int(round(gross * float(pct) / 100))
        db.insert('seller_ledger', dict(order_id=order['id'], order_item_id=it['id'], seller_org_id=it['seller_org_id'], gross_paise=gross,
                  commission_pct=pct, commission_paise=comm, net_paise=gross - comm), returning=None)
    for seller in {it['seller_org_id'] for it in items}:
        db.insert('shipments', dict(order_id=order['id'], seller_org_id=seller), returning=None)
        if seller: notify.notify_org(seller, 'New marketplace order', f"Order {order['invoice_no']} — please dispatch.", '/dashboard/sales')
    notify.notify_staff('New marketplace order', order['invoice_no'] or '', f"/admin/orders/{order['id']}")
    notify.notify(order['user_id'], 'Order confirmed', f"Thank you! Order {order['invoice_no']} is confirmed.", '/dashboard/orders', mail=True)
