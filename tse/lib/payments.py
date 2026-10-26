"""Payment gateway abstraction (Razorpay today; mock for development).

Flow: create_order() -> /pay/<public_id> (gateway checkout) -> verify callback/webhook -> mark_paid() -> fulfil()
Fulfilment handlers are registered per order kind, so new revenue streams plug in without touching the gateway.
"""
import hmac, hashlib, json, datetime, decimal
import requests
from flask import current_app, url_for
from ..db import db
from .security import audit

FULFILLERS = {}
def fulfiller(kind):
    def deco(fn):
        FULFILLERS[kind] = fn; return fn
    return deco

def gst_split(amount_paise, rate, inclusive):
    rate = decimal.Decimal(str(rate))
    if inclusive:
        base = (decimal.Decimal(amount_paise) * 100 / (100 + rate)).quantize(decimal.Decimal('1'))
        return int(base), int(amount_paise - base)
    gst = (decimal.Decimal(amount_paise) * rate / 100).quantize(decimal.Decimal('1'))
    return int(amount_paise), int(gst)

def create_order(kind, description, amount_paise, user_id=None, org_id=None, gst_rate=18, inclusive=False,
                 meta=None, items=None, address=None, shipping_paise=0, referral_code=None):
    sub, gst = gst_split(amount_paise, gst_rate, inclusive) if amount_paise else (0, 0)
    total = sub + gst + shipping_paise
    oid = db.insert('orders', dict(kind=kind, description=description[:300], subtotal_paise=sub, gst_paise=gst,
                    shipping_paise=shipping_paise, total_paise=total, user_id=user_id, org_id=org_id, meta=meta or {},
                    address=address, referral_code=referral_code, attribution=_attrib(), gateway=current_app.config['PAYMENT_GATEWAY']))
    for it in items or []:
        db.insert('order_items', dict(order_id=oid, **it), returning=None)
    order = db.one('SELECT * FROM orders WHERE id = %s', oid)
    if total == 0:
        mark_paid(order, gateway_payment_id='free')
    audit('order.created', 'order', oid, {'kind': kind, 'total': total}, org_id=org_id)
    return db.one('SELECT * FROM orders WHERE id = %s', oid)

def gateway_checkout(order):
    """Returns dict for the checkout template."""
    cfg = current_app.config
    if cfg['PAYMENT_GATEWAY'] == 'razorpay':
        if not order['gateway_order_id']:
            r = requests.post('https://api.razorpay.com/v1/orders', auth=(cfg['RAZORPAY_KEY_ID'], cfg['RAZORPAY_KEY_SECRET']),
                              json={'amount': order['total_paise'], 'currency': 'INR', 'receipt': str(order['public_id'])[:40],
                                    'notes': {'kind': order['kind'], 'order_id': order['id']}}, timeout=20)
            r.raise_for_status()
            gid = r.json()['id']
            db.run('UPDATE orders SET gateway_order_id = %s, gateway = %s WHERE id = %s', gid, 'razorpay', order['id'])
            order = db.one('SELECT * FROM orders WHERE id = %s', order['id'])
        return {'gateway': 'razorpay', 'key': cfg['RAZORPAY_KEY_ID'], 'gateway_order_id': order['gateway_order_id']}
    return {'gateway': 'mock'}

def verify_razorpay_signature(order_id, payment_id, signature):
    secret = current_app.config['RAZORPAY_KEY_SECRET'].encode()
    expected = hmac.new(secret, f'{order_id}|{payment_id}'.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or '')

def verify_webhook(body, signature):
    secret = current_app.config['RAZORPAY_WEBHOOK_SECRET'].encode()
    return bool(secret) and hmac.compare_digest(hmac.new(secret, body, hashlib.sha256).hexdigest(), signature or '')

def mark_paid(order, gateway_payment_id=None):
    """Idempotent: safe to call from both the browser callback and the webhook."""
    with db.transaction():
        row = db.one('SELECT * FROM orders WHERE id = %s FOR UPDATE', order['id'])
        if row['status'] in ('paid', 'fulfilled', 'shipped', 'delivered'):
            return row
        inv = f"TSE/{datetime.date.today().strftime('%y%m')}/{db.val('SELECT nextval(%s)', 'invoice_seq')}"
        db.run("UPDATE orders SET status = 'paid', paid_at = now(), gateway_payment_id = %s, invoice_no = %s WHERE id = %s",
               gateway_payment_id, inv, row['id'])
        row = db.one('SELECT * FROM orders WHERE id = %s', row['id'])
        fn = FULFILLERS.get(row['kind'])
        with db.elevated():       # fulfilment legitimately writes across tenants (seller ledgers, notifications, leads)
            if fn: fn(row)
            if row['referral_code']:
                _credit_referral(row)
    from . import crm
    crm.emit('order.paid', {'order_id': row['id'], 'kind': row['kind'], 'total_inr': row['total_paise'] / 100,
                            'user_id': row['user_id'], 'org_id': row['org_id'], 'invoice_no': row['invoice_no']})
    audit('order.paid', 'order', row['id'], {'kind': row['kind']}, org_id=row['org_id'])
    return row

def _attrib():
    try:
        from .security import attribution
        return attribution()
    except RuntimeError:
        return None

def _credit_referral(order):
    rc = db.one('SELECT * FROM referral_codes WHERE code = %s AND active', order['referral_code'])
    if not rc: return
    if (rc['user_id'] and rc['user_id'] == order['user_id']) or (rc['org_id'] and rc['org_id'] == order['org_id']): return   # no self-referral
    if db.val('SELECT 1 FROM referrals WHERE order_id = %s', order['id']): return
    commission = int(order['subtotal_paise'] * float(rc['commission_pct']) / 100)
    db.insert('referrals', dict(code=rc['code'], referred_user_id=order['user_id'], referred_org_id=order['org_id'],
              order_id=order['id'], commission_paise=commission), returning=None)

def refund(order, amount_paise=None, reason=''):
    cfg = current_app.config
    if order['gateway'] == 'razorpay' and order['gateway_payment_id']:
        r = requests.post(f"https://api.razorpay.com/v1/payments/{order['gateway_payment_id']}/refund",
                          auth=(cfg['RAZORPAY_KEY_ID'], cfg['RAZORPAY_KEY_SECRET']),
                          json={'amount': amount_paise or order['total_paise'], 'notes': {'reason': reason[:200]}}, timeout=20)
        r.raise_for_status()
    db.run("UPDATE orders SET status = 'refunded' WHERE id = %s", order['id'])
    audit('order.refunded', 'order', order['id'], {'reason': reason})

def inr(paise, decimals=False):
    if paise is None: return ''
    rupees = decimal.Decimal(paise) / 100
    s = f'{rupees:,.2f}' if decimals or rupees % 1 else f'{int(rupees):,}'
    # Indian digit grouping
    whole, _, frac = s.replace(',', '').partition('.')
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = ','.join([head[max(i - 2, 0):i] for i in range(len(head), 0, -2)][::-1])
        whole = head + ',' + tail
    return '₹' + whole + ('.' + frac if frac else '')
