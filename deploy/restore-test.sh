#!/usr/bin/env bash
# Monthly restore drill into a throw-away database; proves backups are usable and the audit chain is intact.
set -euo pipefail
LATEST=$(ls -1t /var/backups/schoolexpert/db-*.dump.enc | head -1)
sudo -u postgres dropdb --if-exists tse_restore_test; sudo -u postgres createdb -O tse tse_restore_test
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:/root/.tse-backup-pass -in "$LATEST" | sudo -u postgres pg_restore -d tse_restore_test --no-owner
cd /var/www/schoolexpert && DATABASE_URL=postgresql:///tse_restore_test?host=/var/run/postgresql venv/bin/flask --app wsgi verify-audit
sudo -u postgres psql -d tse_restore_test -c "select count(*) as users from users; select count(*) as registrations from registrations;"
sudo -u postgres dropdb tse_restore_test
echo "Restore drill OK: $LATEST"
