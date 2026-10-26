"""CRM integration via a transactional outbox.

Business code calls emit(event, payload). Events are written to the `outbox` table in the same database
transaction, then delivered by `flask --app wsgi outbox-worker` (cron/systemd) to the configured CRM.
This keeps the site fast and guarantees no lead is lost if the CRM is down. Switching CRM = change env vars.

Events: lead.created, registration.submitted, registration.verified, order.paid, expert_request.created,
        pa_request.created, job_application.created, contact.created, newsletter.subscribed, sponsorship.enquiry
"""
import json, hmac, hashlib, datetime, time
import requests
from flask import current_app
from ..db import db

def emit(event, payload):
    db.insert('outbox', dict(channel='crm', event=event, payload=payload), returning=None)

# ---------------- adapters ----------------
def _webhook(event, payload, cfg):
    body = json.dumps({'event': event, 'data': payload, 'sent_at': datetime.datetime.utcnow().isoformat() + 'Z'}, default=str)
    sig = hmac.new(cfg['CRM_WEBHOOK_SECRET'].encode(), body.encode(), hashlib.sha256).hexdigest()
    from .security import safe_outbound_url
    r = requests.post(safe_outbound_url(cfg['CRM_WEBHOOK_URL']), data=body, allow_redirects=False, headers={'Content-Type': 'application/json', 'X-TSE-Signature': sig}, timeout=15)
    r.raise_for_status()

_zoho_token = {'value': None, 'exp': 0}
def _zoho(event, payload, cfg):
    if time.time() > _zoho_token['exp']:
        r = requests.post(f"https://accounts.zoho.{cfg['ZOHO_DC']}/oauth/v2/token", data={
            'refresh_token': cfg['ZOHO_REFRESH_TOKEN'], 'client_id': cfg['ZOHO_CLIENT_ID'],
            'client_secret': cfg['ZOHO_CLIENT_SECRET'], 'grant_type': 'refresh_token'}, timeout=15)
        r.raise_for_status(); j = r.json()
        _zoho_token.update(value=j['access_token'], exp=time.time() + int(j.get('expires_in', 3600)) - 60)
    lead = {'Last_Name': payload.get('name') or payload.get('org_name') or 'Unknown', 'Email': payload.get('email'),
            'Phone': payload.get('phone'), 'Lead_Source': 'The School Expert Website', 'Company': payload.get('org_name') or payload.get('school'),
            'Description': f"{event}: " + json.dumps(payload, default=str)[:30000], 'City': payload.get('city')}
    r = requests.post(f"https://www.zohoapis.{cfg['ZOHO_DC']}/crm/v6/Leads/upsert", headers={'Authorization': f"Zoho-oauthtoken {_zoho_token['value']}"},
                      json={'data': [lead], 'duplicate_check_fields': ['Email']}, timeout=15)
    r.raise_for_status()

def _hubspot(event, payload, cfg):
    if not payload.get('email'):
        return
    props = {'email': payload.get('email'), 'firstname': (payload.get('name') or '').split(' ')[0], 'phone': payload.get('phone'),
             'city': payload.get('city'), 'company': payload.get('org_name'), 'tse_last_event': event}
    r = requests.post('https://api.hubapi.com/crm/v3/objects/contacts/batch/upsert', headers={'Authorization': f"Bearer {cfg['HUBSPOT_TOKEN']}"},
                      json={'inputs': [{'idProperty': 'email', 'id': payload['email'], 'properties': {k: v for k, v in props.items() if v}}]}, timeout=15)
    r.raise_for_status()

def _leadsquared(event, payload, cfg):
    fields = [{'Attribute': 'EmailAddress', 'Value': payload.get('email')}, {'Attribute': 'FirstName', 'Value': payload.get('name')},
              {'Attribute': 'Phone', 'Value': payload.get('phone')}, {'Attribute': 'Source', 'Value': 'The School Expert'},
              {'Attribute': 'Notes', 'Value': f'{event}: ' + json.dumps(payload, default=str)[:3000]}]
    r = requests.post(f"https://{cfg['LEADSQUARED_HOST']}/v2/LeadManagement.svc/Lead.Capture",
                      params={'accessKey': cfg['LEADSQUARED_ACCESS_KEY'], 'secretKey': cfg['LEADSQUARED_SECRET_KEY']},
                      json=[f for f in fields if f['Value']], timeout=15)
    r.raise_for_status()

ADAPTERS = {'webhook': _webhook, 'zoho': _zoho, 'hubspot': _hubspot, 'leadsquared': _leadsquared}

def deliver_pending(limit=100):
    cfg = current_app.config
    provider = cfg['CRM_PROVIDER']
    rows = db.all("SELECT * FROM outbox WHERE status = 'pending' AND next_attempt_at <= now() ORDER BY id LIMIT %s", limit)
    sent = 0
    for r in rows:
        if r['channel'] == 'crm' and provider == 'none':
            db.run("UPDATE outbox SET status = 'skipped' WHERE id = %s", r['id']); continue
        try:
            if r['channel'] == 'crm': ADAPTERS[provider](r['event'], r['payload'], cfg)
            elif r['channel'] == 'email':
                from .notify import send_email_now; send_email_now(**r['payload'])
            db.run("UPDATE outbox SET status = 'sent', sent_at = now(), attempts = attempts + 1 WHERE id = %s", r['id']); sent += 1
        except Exception as e:
            backoff = min(3600, 30 * (2 ** r['attempts']))
            status = 'failed' if r['attempts'] >= 8 else 'pending'
            db.run("UPDATE outbox SET attempts = attempts + 1, last_error = %s, status = %s, next_attempt_at = now() + make_interval(secs => %s) WHERE id = %s",
                   str(e)[:500], status, backoff, r['id'])
    return sent
