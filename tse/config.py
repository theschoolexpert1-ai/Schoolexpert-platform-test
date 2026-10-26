import os

def _bool(v, default=False):
    if v is None: return default
    return str(v).lower() in ('1', 'true', 'yes', 'on')

ON_VERCEL = bool(os.getenv('VERCEL'))

def _database_url():
    # On Vercel + Neon use the DIRECT (unpooled) connection: row-level security keeps per-connection settings,
    # which a transaction-mode pooler (PgBouncer) would mix up between requests.
    for k in ('DATABASE_URL_UNPOOLED', 'POSTGRES_URL_NON_POOLING', 'DATABASE_URL', 'POSTGRES_URL'):
        if os.getenv(k): return os.getenv(k)
    return 'postgresql://tse:tse_dev_pw@127.0.0.1:5432/schoolexpert'

def _site_url():
    if os.getenv('SITE_URL'): return os.getenv('SITE_URL')
    host = os.getenv('VERCEL_PROJECT_PRODUCTION_URL') or os.getenv('VERCEL_URL')
    return f'https://{host}' if host else 'http://localhost:8000'

class Config:
    ENV = os.getenv('TSE_ENV', 'staging' if ON_VERCEL else 'development')   # staging = secure like production, test payments, not indexed
    ON_VERCEL = ON_VERCEL
    STAGING_BASIC_AUTH = os.getenv('STAGING_BASIC_AUTH', '')        # "team:password" — optional site-wide password for the prototype
    CRON_SECRET = os.getenv('CRON_SECRET', '')                      # Vercel sends it as "Authorization: Bearer <CRON_SECRET>"
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-insecure-change-me')
    # Pages under /embed/ may be framed by these origins (existing www.schoolexpert.in site, school websites using the widget).
    EMBED_FRAME_ANCESTORS = os.getenv('EMBED_FRAME_ANCESTORS', 'https:')
    ASSET_VERSION = os.getenv('ASSET_VERSION', '4')
    GOOGLE_ADS_LABEL_PURCHASE = os.getenv('GOOGLE_ADS_LABEL_PURCHASE', ''); GOOGLE_ADS_LABEL_SIGNUP = os.getenv('GOOGLE_ADS_LABEL_SIGNUP', '')
    API_TOKEN_DAYS = int(os.getenv('API_TOKEN_DAYS', '90'))
    DATABASE_URL = _database_url()
    DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '2' if ON_VERCEL else '10'))   # serverless: few connections per instance
    SITE_URL = _site_url().rstrip('/')
    SITE_NAME = 'The School Expert™'
    # 32-byte base64 key for AES-256-GCM encryption of private registration fields
    FIELD_ENCRYPTION_KEY = os.getenv('FIELD_ENCRYPTION_KEY', '')
    FIELD_ENCRYPTION_KEYS = os.getenv('FIELD_ENCRYPTION_KEYS', '')      # "v2:<b64>,v1:<b64>" — newest first (key rotation)
    # Storage: 'local' now; 's3' (AWS S3 / DigitalOcean Spaces / Azure via S3 gateway / GCS interop) after cloud migration
    STORAGE_BACKEND = os.getenv('STORAGE_BACKEND', 'db' if ON_VERCEL else 'local')   # local | db | s3
    UPLOAD_DIR = os.getenv('UPLOAD_DIR', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'var', 'uploads'))
    PRIVATE_UPLOAD_DIR = os.getenv('PRIVATE_UPLOAD_DIR', os.path.join(os.path.dirname(os.path.dirname(__file__)), 'var', 'private'))
    MAX_CONTENT_LENGTH = int(os.getenv('MAX_UPLOAD_MB', '15')) * 1024 * 1024
    S3_BUCKET = os.getenv('S3_BUCKET', ''); S3_ENDPOINT = os.getenv('S3_ENDPOINT', ''); S3_REGION = os.getenv('S3_REGION', 'ap-south-1')
    S3_ACCESS_KEY = os.getenv('S3_ACCESS_KEY', ''); S3_SECRET_KEY = os.getenv('S3_SECRET_KEY', '')
    # Payments
    PAYMENT_GATEWAY = os.getenv('PAYMENT_GATEWAY', 'mock')          # mock | razorpay
    RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', '')
    RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', '')
    RAZORPAY_WEBHOOK_SECRET = os.getenv('RAZORPAY_WEBHOOK_SECRET', '')
    GSTIN = os.getenv('TSE_GSTIN', '')
    # CRM (outbox delivers events): none | webhook | zoho | hubspot | leadsquared
    CRM_PROVIDER = os.getenv('CRM_PROVIDER', 'none')
    CRM_WEBHOOK_URL = os.getenv('CRM_WEBHOOK_URL', ''); CRM_WEBHOOK_SECRET = os.getenv('CRM_WEBHOOK_SECRET', '')
    ZOHO_CLIENT_ID = os.getenv('ZOHO_CLIENT_ID', ''); ZOHO_CLIENT_SECRET = os.getenv('ZOHO_CLIENT_SECRET', '')
    ZOHO_REFRESH_TOKEN = os.getenv('ZOHO_REFRESH_TOKEN', ''); ZOHO_DC = os.getenv('ZOHO_DC', 'in')
    HUBSPOT_TOKEN = os.getenv('HUBSPOT_TOKEN', '')
    LEADSQUARED_HOST = os.getenv('LEADSQUARED_HOST', ''); LEADSQUARED_ACCESS_KEY = os.getenv('LEADSQUARED_ACCESS_KEY', ''); LEADSQUARED_SECRET_KEY = os.getenv('LEADSQUARED_SECRET_KEY', '')
    # Email / SMS
    MAIL_FROM = os.getenv('MAIL_FROM', 'The School Expert <info@schoolexpert.in>')
    SMTP_HOST = os.getenv('SMTP_HOST', ''); SMTP_PORT = int(os.getenv('SMTP_PORT', '587'))
    SMTP_USER = os.getenv('SMTP_USER', ''); SMTP_PASSWORD = os.getenv('SMTP_PASSWORD', ''); SMTP_TLS = _bool(os.getenv('SMTP_TLS', '1'), True)
    SMS_PROVIDER = os.getenv('SMS_PROVIDER', 'console')               # console | msg91
    MSG91_AUTH_KEY = os.getenv('MSG91_AUTH_KEY', ''); MSG91_TEMPLATE_ID = os.getenv('MSG91_TEMPLATE_ID', '')
    # AI (CV generation, moderation assist)
    ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
    ANTHROPIC_MODEL = os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-5')
    # Analytics / SEM (loaded only after cookie consent)
    GA4_ID = os.getenv('GA4_ID', ''); GOOGLE_ADS_ID = os.getenv('GOOGLE_ADS_ID', ''); META_PIXEL_ID = os.getenv('META_PIXEL_ID', '')
    GOOGLE_SITE_VERIFICATION = os.getenv('GOOGLE_SITE_VERIFICATION', '')
    # Contacts
    CONTACT_EMAIL = 'info@schoolexpert.in'; PARTNER_EMAIL = 'shalini@schoolexpert.in'; CONTACT_PHONE = '9972915700'
    GRIEVANCE_OFFICER = os.getenv('GRIEVANCE_OFFICER', 'Grievance Officer, The School Expert™')
    GRIEVANCE_EMAIL = os.getenv('GRIEVANCE_EMAIL', 'info@schoolexpert.in')
    LEGAL_ENTITY = 'Poornaphala Media and Infotech Services LLP'
    REGISTERED_ADDRESS = '#559, Sanjeevini, 26th Cross, Kirloskar Layout, Bangalore - 560073'
    SESSION_COOKIE_SECURE = _bool(os.getenv('SESSION_COOKIE_SECURE'), ENV in ('production', 'staging'))
    SESSION_DAYS = int(os.getenv('SESSION_DAYS', '14'))                 # absolute lifetime
    IDLE_MINUTES_STAFF = int(os.getenv('IDLE_MINUTES_STAFF', '30'))
    IDLE_HOURS_USER = int(os.getenv('IDLE_HOURS_USER', '72'))
    MFA_REQUIRED_FOR_STAFF = _bool(os.getenv('MFA_REQUIRED_FOR_STAFF'), ENV == 'production')   # staging: team can opt in
    ADMIN_IP_ALLOWLIST = [x.strip() for x in os.getenv('ADMIN_IP_ALLOWLIST', '').split(',') if x.strip()]   # e.g. office / VPN IPs or CIDRs
    CLAMD_HOST = os.getenv('CLAMD_HOST', ''); CLAMD_PORT = os.getenv('CLAMD_PORT', '3310')
    TRUSTED_PROXIES = int(os.getenv('TRUSTED_PROXIES', '1'))            # nginx in front of the app
    DEV_SHOW_OTP = _bool(os.getenv('DEV_SHOW_OTP'), ENV == 'development')   # never on shared/staging sites: it would reveal reset links
