"""Email, SMS and in-app notifications. Email goes through the outbox (retries); OTP SMS is sent immediately."""
import smtplib, ssl
from email.message import EmailMessage
import requests
from flask import current_app, render_template_string
from ..db import db

def email(to, subject, text, html=None):
    if not to: return
    db.insert('outbox', dict(channel='email', event='email', payload={'to': to, 'subject': subject, 'text': text, 'html': html}), returning=None)
    if not current_app.config['SMTP_HOST']:
        current_app.logger.info('EMAIL (not configured) to=%s subject=%s\n%s', to, subject, text)

def send_email_now(to, subject, text, html=None):
    cfg = current_app.config
    if not cfg['SMTP_HOST']:
        return
    msg = EmailMessage(); msg['From'] = cfg['MAIL_FROM']; msg['To'] = to; msg['Subject'] = subject
    msg.set_content(text)
    if html: msg.add_alternative(html, subtype='html')
    with smtplib.SMTP(cfg['SMTP_HOST'], cfg['SMTP_PORT'], timeout=20) as s:
        if cfg['SMTP_TLS']: s.starttls(context=ssl.create_default_context())
        if cfg['SMTP_USER']: s.login(cfg['SMTP_USER'], cfg['SMTP_PASSWORD'])
        s.send_message(msg)

def sms(phone, text, otp=None):
    cfg = current_app.config
    if cfg['SMS_PROVIDER'] == 'msg91' and cfg['MSG91_AUTH_KEY'] and otp:
        requests.post('https://control.msg91.com/api/v5/otp', params={'template_id': cfg['MSG91_TEMPLATE_ID'], 'mobile': '91' + phone[-10:], 'otp': otp},
                      headers={'authkey': cfg['MSG91_AUTH_KEY']}, timeout=15)
    else:
        current_app.logger.info('SMS to %s: %s', phone, text)

def notify(user_id, title, body=None, link=None, mail=False):
    if not user_id: return
    db.insert('notifications', dict(user_id=user_id, title=title[:200], body=body, link=link), returning=None)
    if mail:
        u = db.one('SELECT email, name FROM users WHERE id = %s', user_id)
        if u:
            site = current_app.config['SITE_URL']
            email(u['email'], title, f"Hello {u['name']},\n\n{body or ''}\n\n{site + link if link else site}\n\n— The School Expert™")

def notify_org(org_id, title, body=None, link=None, mail=True):
    for m in db.all("SELECT user_id FROM org_members WHERE org_id = %s AND role IN ('owner','admin')", org_id):
        notify(m['user_id'], title, body, link, mail=mail)

def notify_staff(title, body=None, link=None, role=None):
    sql = "SELECT id FROM users WHERE account_type IN ('admin','staff') AND status = 'active'"
    for u in db.all(sql + (' AND staff_role = %s' if role else ''), *([role] if role else [])):
        notify(u['id'], title, body, link)
