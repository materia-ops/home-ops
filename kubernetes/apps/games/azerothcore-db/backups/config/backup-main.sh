#!/usr/bin/env bash
# Nightly mysqldump of the small, precious databases. Any failure exits
# non-zero -> the Job goes Failed -> the games namespace alerts fire.
set -euo pipefail

HOST=azerothcore-db.games.svc.cluster.local
STAMP="$(date +%Y%m%d-%H%M%S)"
RETENTION_DAYS=14

# Poisoning guard: refuse to dump or prune while acore_characters.characters is
# empty. That almost always means a blank datadir (volume/staging fault), and
# dump-then-prune would replace the good backups inside the retention window.
CHAR_ROWS="$(mysql --host="${HOST}" --user=acore -N -B \
  -e 'SELECT COUNT(*) FROM acore_characters.characters' 2>/dev/null || echo 0)"
if [ "${CHAR_ROWS:-0}" -lt 1 ]; then
  echo "[backup-main] REFUSING: acore_characters.characters has ${CHAR_ROWS:-0} rows;" >&2
  echo "[backup-main] aborting before any dump or prune to protect existing backups." >&2
  exit 1
fi
echo "[backup-main] guard OK: acore_characters.characters has ${CHAR_ROWS} rows"

for db in acore_auth acore_characters acore_playerbots; do
  out="/backups/${db}-${STAMP}.sql.gz"
  echo "[backup-main] dumping ${db} -> ${out}"
  # --no-tablespaces: skips the tablespace dump that would need PROCESS priv;
  # the acore user only has grants on acore_%.
  mysqldump --host="${HOST}" --user=acore \
    --single-transaction --routines --no-tablespaces \
    "${db}" | gzip > "${out}"
  gunzip -t "${out}"
done

echo "[backup-main] pruning dumps older than ${RETENTION_DAYS} days"
find /backups -maxdepth 1 -type f \
  \( -name 'acore_auth-*.sql.gz' \
  -o -name 'acore_characters-*.sql.gz' \
  -o -name 'acore_playerbots-*.sql.gz' \) \
  -mtime "+${RETENTION_DAYS}" -print -delete

echo "[backup-main] done"
ls -lh /backups
