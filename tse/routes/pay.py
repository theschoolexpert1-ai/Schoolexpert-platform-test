import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, g, abort, current_app, jsonify
from ..db import db
from ..lib import payments
from ..lib.auth import login_required, is_staff

bp = Blueprint('pay', __name__)

NEXT = {'plan': '/dashboard', 'unlock_pack': '/ask/schools', 'personal_assistance': '/dashboard/personal-assistance', 'expert': '/dashboard/requests',
        'event_pass': '/dashboard/events', 'marketplace': '/dashboard/orders', 'subscription': '/dashboard/subscriptions', 'teacher_premium': '/dashboard'}

def _order(public_id):
    o = db.one('SELECT * FROM orders WHERE public_id = %s', str(public_id)) or abort(404)
    if not g.user or (o['user_id'] != g.user['id'] and not is_staff()): abort(404)
    return o

def _track(o):
    from ..lib.security import conversion
    conversion('purchase', ads_label=current_app.config.get('GOOGLE_ADS_LABEL_PURCHASE') or None, transaction_id=o['invoice_no'] or str(o['id']),
               value=round(o['total_paise'] / 100, 2), currency='INR', items=[{'item_name': o['kind'], 'item_category': (o['meta'] or {}).get('plan', o['kind'])}])

def _next_url(o):
    if o['kind'] == 'unlock_pack': return f"/ask/schools?city={o['meta'].get('city', '')}"
    if o['kind'] == 'personal_assistance': return f"/personal-assistance/{o['meta']['pa_request_id']}"
    return NEXT.get(o['kind'], '/dashboard/orders')

@bp.route('/pay/<uuid:public_id>')
@login_required
def checkout(public_id):
    o = _order(public_id)
    if o['status'] != 'created':
        return redirect(_next_url(o))
    gw = payments.gateway_checkout(o)
    o = _order(public_id)
    items = db.all('SELECT * FROM order_items WHERE order_id = %s', o['id'])
    return render_template('pay/checkout.html', o=o, gw=gw, items=items)

@bp.route('/pay/<uuid:public_id>/razorpay', methods=['POST'])
@login_required
def razorpay_callback(public_id):
    o = _order(public_id)
    f = request.form
    if f.get('razorpay_order_id') != o['gateway_order_id'] or not payments.verify_razorpay_signature(f.get('razorpay_order_id'), f.get('razorpay_payment_id'), f.get('razorpay_signature')):
        db.run("UPDATE orders SET status = 'failed' WHERE id = %s AND status = 'created'", o['id'])
        flash('Payment verification failed. If money was debited it will be auto-refunded by the bank, or contact us.', 'error')
        return redirect(url_for('pay.checkout', public_id=public_id))
    o = payments.mark_paid(o, f.get('razorpay_payment_id')) or o
    _track(o)
    flash('Payment successful. Thank you!', 'success')
    return redirect(_next_url(o))

@bp.route('/pay/<uuid:public_id>/mock', methods=['POST'])
@login_required
def mock(public_id):
    if current_app.config['PAYMENT_GATEWAY'] != 'mock': abort(404)
    o = _order(public_id)
    if request.form.get('result') == 'success':
        o = payments.mark_paid(o, 'mock_' + str(o['id'])) or o
        _track(o)
        flash('Payment successful (test mode). Thank you!', 'success')
        return redirect(_next_url(o))
    db.run("UPDATE orders SET status = 'failed' WHERE id = %s AND status = 'created'", o['id'])
    flash('Payment failed (test mode).', 'error')
    return redirect(url_for('dashboard.orders'))

@bp.route('/pay/<uuid:public_id>/retry', methods=['POST'])
@login_required
def retry(public_id):
    o = _order(public_id)
    if o['status'] == 'failed':
        db.run("UPDATE orders SET status = 'created', gateway_order_id = NULL WHERE id = %s", o['id'])
    return redirect(url_for('pay.checkout', public_id=public_id))

@bp.route('/webhooks/razorpay', methods=['POST'])
def webhook():
    body = request.get_data()
    ok = payments.verify_webhook(body, request.headers.get('X-Razorpay-Signature'))
    try: data = json.loads(body)
    except ValueError: abort(400)
    ent = (data.get('payload', {}).get('payment', {}) or {}).get('entity', {})
    db.insert('payment_events', dict(gateway='razorpay', event=data.get('event'), gateway_order_id=ent.get('order_id'), raw=data, verified=ok), returning=None)
    if not ok: abort(400)
    g.db_bypass = True        # server-to-server call, authenticated by the HMAC signature verified above
    if data.get('event') in ('payment.captured', 'order.paid') and ent.get('order_id'):
        o = db.one('SELECT * FROM orders WHERE gateway_order_id = %s', ent['order_id'])
        if o and o['total_paise'] == ent.get('amount'):
            payments.mark_paid(o, ent.get('id'))
    return jsonify(ok=True)

@bp.route('/orders/<uuid:public_id>/invoice')
@login_required
def invoice(public_id):
    o = _order(public_id)
    if o['status'] in ('created', 'failed', 'cancelled'): abort(404)
    items = db.all('SELECT * FROM order_items WHERE order_id = %s', o['id'])
    u = db.one('SELECT name, email, phone FROM users WHERE id = %s', o['user_id'])
    org = db.one('SELECT name, gstin, billing FROM organisations WHERE id = %s', o['org_id']) if o['org_id'] else None
    return render_template('pay/invoice.html', o=o, items=items, u=u, org=org)
