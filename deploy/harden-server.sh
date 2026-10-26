#!/usr/bin/env bash
# One-time hardening for the Ubuntu 22.04/24.04 VPS (GoDaddy or cloud). Run as root AFTER adding your SSH key.
set -euo pipefail
APP_USER=schoolexpert; ADMIN_SSH_PORT=${ADMIN_SSH_PORT:-22}

# 1. Updates: install security patches automatically
apt-get update && apt-get -y upgrade
apt-get -y install unattended-upgrades fail2ban ufw auditd apparmor apparmor-utils clamav-daemon logwatch
dpkg-reconfigure -f noninteractive unattended-upgrades

# 2. Firewall: only SSH + web; PostgreSQL is never exposed
ufw default deny incoming; ufw default allow outgoing
ufw limit "$ADMIN_SSH_PORT"/tcp
ufw allow 80/tcp; ufw allow 443/tcp
ufw --force enable

# 3. SSH: keys only, no root, no passwords
sed -i -E 's/^#?PermitRootLogin.*/PermitRootLogin no/; s/^#?PasswordAuthentication.*/PasswordAuthentication no/; s/^#?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/; s/^#?X11Forwarding.*/X11Forwarding no/; s/^#?MaxAuthTries.*/MaxAuthTries 3/' /etc/ssh/sshd_config
systemctl restart ssh || systemctl restart sshd

# 4. fail2ban: SSH brute force + repeated 401/429 on sign-in pages
cat > /etc/fail2ban/filter.d/tse-auth.conf <<'F'
[Definition]
failregex = ^<HOST> - .* "POST /(login|login/verify|reauth|api/v1/auth/token)[^"]*" (401|429)
F
cat > /etc/fail2ban/jail.d/tse.conf <<'F'
[sshd]
enabled = true
maxretry = 4
bantime = 1h
[tse-auth]
enabled = true
port = http,https
filter = tse-auth
logpath = /var/log/nginx/access.log
maxretry = 20
findtime = 10m
bantime = 1h
F
systemctl enable --now fail2ban

# 5. Kernel/network hardening
cat > /etc/sysctl.d/99-tse.conf <<'F'
net.ipv4.tcp_syncookies = 1
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.accept_source_route = 0
net.ipv6.conf.all.accept_redirects = 0
kernel.kptr_restrict = 2
kernel.dmesg_restrict = 1
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
F
sysctl --system >/dev/null

# 6. PostgreSQL: local only, SCRAM passwords, least-privilege app role
PGV=$(ls /etc/postgresql | sort -V | tail -1); PGC=/etc/postgresql/$PGV/main
sed -i -E "s/^#?listen_addresses.*/listen_addresses = 'localhost'/; s/^#?password_encryption.*/password_encryption = scram-sha-256/; s/^#?log_connections.*/log_connections = on/" $PGC/postgresql.conf
sed -i -E 's/\b(md5|trust)\b/scram-sha-256/g' $PGC/pg_hba.conf
systemctl restart postgresql

# 7. App files: owned by the app user, secrets readable only by it
id $APP_USER >/dev/null 2>&1 || useradd --system --home /var/www/schoolexpert --shell /usr/sbin/nologin $APP_USER
chown -R $APP_USER:www-data /var/www/schoolexpert
chmod 600 /var/www/schoolexpert/.env
chmod 750 /var/www/schoolexpert/var/private
find /var/www/schoolexpert -type d -name __pycache__ -prune -o -type f -name '*.py' -exec chmod 640 {} +

# 8. Antivirus for uploads (set CLAMD_HOST=127.0.0.1 in .env)
sed -i 's/^#\?TCPSocket.*/TCPSocket 3310/; s/^#\?TCPAddr.*/TCPAddr 127.0.0.1/' /etc/clamav/clamd.conf || true
grep -q '^TCPSocket' /etc/clamav/clamd.conf || printf 'TCPSocket 3310\nTCPAddr 127.0.0.1\n' >> /etc/clamav/clamd.conf
systemctl enable --now clamav-freshclam clamav-daemon

# 9. Audit trail of admin activity on the server itself
systemctl enable --now auditd
echo "Done. Next: install nginx snippets (deploy/nginx-snippets.conf), certbot, then systemctl enable --now schoolexpert."
