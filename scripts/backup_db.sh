#!/usr/bin/env bash
# Online snapshot of data/atlas.db via VACUUM INTO (safe alongside the WAL writer: it is a read txn).
# Retention: keep the newest 96 snapshots (24 h at 15-min cadence) + the newest snapshot of each
# day for 30 days. Everything else is deleted. Fired by systemd --user germany-atlas-backup.timer.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="$ROOT/data/atlas.db"
DIR="$ROOT/data/backups"
KEEP_RECENT="${KEEP_RECENT:-96}"
KEEP_DAYS="${KEEP_DAYS:-30}"
mkdir -p "$DIR"

[[ -f "$DB" ]] || { echo "backup: no database at $DB, nothing to do"; exit 0; }

# one backup at a time (separate from the writer lock, so ingests are never blocked by backups)
exec 9>"$DIR/.backup.lock"
flock -n 9 || { echo "backup: another backup is running"; exit 0; }

TS="$(date +%Y%m%dT%H%M%S)"
OUT="$DIR/atlas-$TS.db"
TMP="$OUT.partial"
rm -f "$TMP"
sqlite3 "file:$DB?mode=ro" "VACUUM INTO '$TMP'"
QC="$(sqlite3 "$TMP" 'PRAGMA quick_check;')"
if [[ "$QC" != "ok" ]]; then
  echo "backup: quick_check failed on snapshot: $QC" >&2
  mv "$TMP" "$OUT.bad"
  exit 1
fi
mv "$TMP" "$OUT"
echo "backup: wrote $OUT ($(stat -c %s "$OUT") bytes, quick_check ok)"

# retention
mapfile -t ALL < <(ls -1 "$DIR"/atlas-*.db 2>/dev/null | sort -r)
CUTOFF="$(date -d "-$KEEP_DAYS days" +%Y%m%d)"
declare -A SEEN_DAY=()
deleted=0
for i in "${!ALL[@]}"; do
  f="${ALL[$i]}"
  base="$(basename "$f")"           # atlas-YYYYmmddTHHMMSS.db
  day="${base:6:8}"
  if (( i < KEEP_RECENT )); then SEEN_DAY[$day]=1; continue; fi
  if [[ "$day" > "$CUTOFF" || "$day" == "$CUTOFF" ]] && [[ -z "${SEEN_DAY[$day]:-}" ]]; then
    SEEN_DAY[$day]=1; continue      # newest snapshot of that day
  fi
  rm -f -- "$f"; deleted=$((deleted+1))
done
echo "backup: retention kept $(( ${#ALL[@]} - deleted )) / ${#ALL[@]} (recent $KEEP_RECENT + daily $KEEP_DAYS d)"
