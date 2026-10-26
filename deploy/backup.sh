#!/usr/bin/env bash
# Nightly encrypted backups (AES-256, passphrase file chmod 600) + off-site copy + 30-day local retention.
# Restore drill: deploy/restore-test.sh (run monthly — a backup that has never been restored is not a backup).
set -euo pipefail
cd /var/www/schoolexpert; set -a; . ./.env; set +a
DEST=/var/backups/schoolexpert; mkdir -p "$DEST"; chmod 700 "$DEST"; STAMP=$(date +%F)
umask 077
pg_dump "${MIGRATION_DATABASE_URL:-$DATABASE_URL}" -Fc | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass file:/root/.tse-backup-pass -out "$DEST/db-$STAMP.dump.enc"
tar czf - var/uploads var/private | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass file:/root/.tse-backup-pass -out "$DEST/files-$STAMP.tgz.enc"
sha256sum "$DEST"/*-"$STAMP".* > "$DEST/SHA256SUMS-$STAMP"
find "$DEST" -type f -mtime +30 -delete
# Off-site copy to a different provider/region (immutable/versioned bucket recommended):
if command -v rclone >/dev/null && [ -n "${BACKUP_REMOTE:-}" ]; then rclone copy "$DEST" "$BACKUP_REMOTE" --include "*-$STAMP*"; fi
