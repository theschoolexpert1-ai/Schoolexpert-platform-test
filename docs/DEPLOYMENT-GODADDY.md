# Deploying on GoDaddy

## Which GoDaddy product
The platform needs a long-running Python process, PostgreSQL and background jobs, so use a **GoDaddy VPS (Ubuntu 22.04/24.04), at least 2 vCPU / 4 GB RAM / 100 GB SSD**. Choose the **India** data centre if offered (keeps personal data in India). GoDaddy *shared/cPanel* hosting cannot run this application.

If you only keep the **domain** at GoDaddy and host elsewhere (AWS Mumbai, Azure Central India, DigitalOcean Bangalore), follow the same steps on that server and point GoDaddy DNS at it.

## 1. DNS (GoDaddy → My Products → DNS)
| Type | Name | Value | TTL |
|---|---|---|---|
| A | @ | your server IP | 1 hour |
| A | www | your server IP | 1 hour |
| CNAME | registration | www.schoolexpert.in | 1 hour |

The old `registration.schoolexpert.in` links keep working: the included nginx config redirects every old form, FAQ, privacy and contact URL to its new page.

Keep your existing MX records (GoDaddy / Microsoft 365 email) unchanged. Add SPF/DKIM/DMARC for transactional email:
`TXT @ "v=spf1 include:secureserver.net -all"` (adjust to your mail provider), and DKIM from the mail provider.

## 2. Server setup (as root)
```bash
apt update && apt -y upgrade
apt -y install python3-venv python3-pip postgresql nginx certbot python3-certbot-nginx ufw fail2ban unattended-upgrades
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw enable
adduser --system --group --home /var/www/schoolexpert schoolexpert
```

## 3. Database
```bash
sudo -u postgres psql -c "CREATE USER tse WITH PASSWORD 'STRONG_PASSWORD';"
sudo -u postgres createdb -O tse schoolexpert
sudo -u postgres psql -d schoolexpert -c "CREATE EXTENSION pgcrypto; CREATE EXTENSION pg_trgm; CREATE EXTENSION citext;"
```
PostgreSQL listens only on localhost by default — keep it that way.

## 4. Application
```bash
cd /var/www/schoolexpert            # upload the project here (git clone / sftp)
python3 -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env   # set SECRET_KEY, FIELD_ENCRYPTION_KEY, DATABASE_URL, SMTP, Razorpay…
chown -R schoolexpert:www-data /var/www/schoolexpert && chmod 600 .env
sudo -u schoolexpert bash -c 'set -a; . ./.env; set +a; FLASK_APP=wsgi venv/bin/flask migrate && FLASK_APP=wsgi venv/bin/flask seed'
sudo -u schoolexpert bash -c 'set -a; . ./.env; set +a; FLASK_APP=wsgi venv/bin/flask create-admin you@schoolexpert.in "Your Name"'
```
**Back up `FIELD_ENCRYPTION_KEY` offline.** Without it, encrypted private registration fields cannot be read.

## 5. Services
```bash
cp deploy/schoolexpert.service deploy/schoolexpert-worker.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now schoolexpert schoolexpert-worker
cp deploy/nginx-schoolexpert.conf /etc/nginx/sites-available/schoolexpert
ln -s /etc/nginx/sites-available/schoolexpert /etc/nginx/sites-enabled/ && rm -f /etc/nginx/sites-enabled/default
mkdir -p /var/www/letsencrypt
certbot --nginx -d schoolexpert.in -d www.schoolexpert.in -d registration.schoolexpert.in      # free TLS, auto-renews
nginx -t && systemctl reload nginx
crontab -u schoolexpert deploy/crontab.txt
openssl rand -base64 48 > /root/.tse-backup-pass && chmod 600 /root/.tse-backup-pass
```

## 6. Go-live checklist
- [ ] `.env`: `TSE_ENV=production`, `SESSION_COOKIE_SECURE=1`, `DEV_SHOW_OTP=0`, real `SITE_URL`
- [ ] Razorpay live keys + webhook `https://www.schoolexpert.in/webhooks/razorpay` (events: `payment.captured`, `order.paid`)
- [ ] SMTP tested (sign up a test account and receive the verification email)
- [ ] MSG91 OTP template approved (DLT registration is mandatory for SMS in India)
- [ ] Replace `tse/static/img/logo-mark.svg` with the official logo file
- [ ] Review prices in Admin → Content manager → Plans / Personal Assistance services (all prices are placeholders)
- [ ] Upload the full versions of the 9 provisional forms (see `docs/FORMS.md`)
- [ ] Grievance Officer name/email in `.env`; legal review of the Privacy Policy (see section 46 in your document)
- [ ] Google Search Console: verify, submit `https://www.schoolexpert.in/sitemap.xml`
- [ ] Off-site backups (rclone to Google Drive/S3) and a test restore

## Updating
```bash
cd /var/www/schoolexpert && git pull          # or upload new files
venv/bin/pip install -r requirements.txt
sudo -u schoolexpert bash -c 'set -a; . ./.env; set +a; FLASK_APP=wsgi venv/bin/flask migrate'
systemctl restart schoolexpert schoolexpert-worker
```

## Restore from backup
```bash
openssl enc -d -aes-256-cbc -pbkdf2 -pass file:/root/.tse-backup-pass -in db-YYYY-MM-DD.dump.enc | pg_restore -d schoolexpert --clean
```
