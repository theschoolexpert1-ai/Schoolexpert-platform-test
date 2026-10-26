"""Scheduled jobs over HTTPS, for hosts without a crontab (Vercel Cron).

Every endpoint requires  Authorization: Bearer <CRON_SECRET>  — Vercel Cron sends exactly this header when the
CRON_SECRET environment variable is set. Without CRON_SECRET configured the endpoints are switched off (404).

  GET  /cron/outbox          deliver pending CRM events and e-mails       (vercel.json: every day; call more often from any scheduler)
  GET  /cron/housekeeping    DPDP retention, plan expiries, reminders     (daily)
  POST /cron/setup           apply migrations + seed (add ?demo=1 for demo data) — one-time setup of a new database
"""
import hmac, json
from flask import Blueprint, current_app, request, abort, Response, g
from ..db import db

bp = Blueprint('cron', __name__, url_prefix='/cron')

@bp.before_request
def _authorise():
    secret = current_app.config.get('CRON_SECRET')
    if not secret: abort(404)
    if not hmac.compare_digest(request.headers.get('Authorization', ''), f'Bearer {secret}'): abort(401)
    g.db_bypass = True          # trusted server job: cross-tenant work, same as the CLI

def _ok(result): return Response(json.dumps(result, default=str), mimetype='application/json', headers={'Cache-Control': 'no-store'})

@bp.route('/outbox', methods=['GET', 'POST'])
def outbox():
    from ..lib import crm
    with db.elevated(): return _ok({'delivered': crm.deliver_pending()})

@bp.route('/housekeeping', methods=['GET', 'POST'])
def housekeeping():
    from ..lib import retention
    with db.elevated(): return _ok(retention.run())

@bp.route('/setup', methods=['POST'])
def setup():
    from ..cli import apply_migrations
    from ..db import seed
    with db.elevated():
        applied = apply_migrations()
        seed.run(demo=request.args.get('demo') == '1')
    return _ok({'migrations_applied': applied, 'seeded': True, 'demo': request.args.get('demo') == '1'})
