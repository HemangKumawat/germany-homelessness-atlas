#!/usr/bin/env bash
# germany-atlas work loop (original implementation).
#
# Picks OPEN items from queue/ (filename order), starts up to MAX_PAR Grok Build workers in tmux
# windows, and when a worker exits records the verdict, then runs the Lead checkpoint:
# quick_check -> backup -> audit -> verify -> build_site. Workers never touch data/atlas.db;
# the Lead merges their branch and runs `python3 -m ingest.run <domain>` by hand.
#
#   MAX_PAR=3 scripts/loop.sh          stop with: touch STOP
#   LOOP_COMMIT=1 also commits the working tree after each checkpoint (off by default)
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT" || exit 1
MAX_PAR=${MAX_PAR:-3}; TRIES=${MAX_ATTEMPTS:-3}; NAP=${SLEEP:-20}; LIMIT=${WORKER_TIMEOUT:-7200}
GROK=${GROK_BIN:-$(command -v grok || echo "$HOME/.local/bin/grok")}    # CLI default model; never pass --model
TMUX_S=${SESSION:-germany-atlas}; WD=$ROOT/logs/workers
mkdir -p "$WD" queue/state logs

pidf=logs/loop.pid
if [[ -s $pidf ]] && kill -0 "$(cat $pidf)" 2>/dev/null; then echo "loop already running ($(cat $pidf))"; exit 0; fi
echo $$ > $pidf; trap 'rm -f $pidf' EXIT

say()    { printf '[%s] %s\n' "$(date -Is)" "$*" | tee -a logs/loop.log; }
state()  { cat "queue/state/$1.status" 2>/dev/null || echo MISSING; }
mark()   { echo "$2" > "queue/state/$1.status"; say "$1 -> $2"; }
items()  { for f in queue/[0-9]*-*.md; do b=${f##*/}; b=${b%.md}; echo "${b#*-}"; done; }
tries()  { cat "queue/state/$1.attempts" 2>/dev/null || echo 0; }

prompt() {   # $1 domain -> logs/workers/<domain>.prompt.txt
  local d=$1 f; f=$(ls queue/*-"$d".md | head -1)
  {
    printf 'You are the %s worker for germany-atlas (repo: %s). You do not write data/atlas.db.\n' "$d" "$ROOT"
    printf 'First read in full: docs/INGEST_CONTRACT.md, ingest/schema.sql, ingest/common.py, GOALS/GOAL.md, and research/*.md.\n\n'
    printf 'Assignment:\n'; cat "$f"; printf '\n'
    cat <<'RULES'
Non-negotiable:
- No invented numbers, names, dates, AGS codes or URLs. Every value comes from a document fetched with
  common.fetch / common.archive, cited by source_id, and the archived document must contain the number.
- Idempotent writes with common.upsert on a natural key. Domain-private tables are prefixed <domain>_.
- Only edit ingest/domains/<domain>.py, research/<domain>.md and append to docs/SOURCES.md.
- Named people only in published roles (org_person, tied to an org and a source). No private individuals.
  No address, postcode or coordinates for Frauenhäuser or other protected shelters.
- 1 request/second. Missing key or 403: write it under '## <domain>' in BLOCKERS.md and continue.
- Test against a scratch DB only. Finish research/<domain>.md with '## Verified' (5 live spot checks) and '## Coverage'.
- Do not commit; leave your files saved for the Lead to review on branch worker/<domain>.
RULES
  } > "$WD/$d.prompt.txt"
}

start() {
  local d=$1
  prompt "$d"; mark "$d" RUNNING; echo $(( $(tries "$d") + 1 )) > "queue/state/$d.attempts"; rm -f "$WD/$d.exit"
  printf '#!/usr/bin/env bash\ncd %q || exit 1\n{ timeout %s %q --cwd %q --permission-mode acceptEdits --always-approve --output-format plain --max-turns 80 --prompt-file %q 2>&1; echo $? > %q; } | tee -a %q\n' \
    "$ROOT" "$LIMIT" "$GROK" "$ROOT" "$WD/$d.prompt.txt" "$WD/$d.exit" "$WD/$d.log" > "$WD/$d.run.sh"
  chmod +x "$WD/$d.run.sh"
  if tmux has-session -t "$TMUX_S" 2>/dev/null; then tmux new-window -t "$TMUX_S" -n "$d" "bash $WD/$d.run.sh"
  else tmux new-session -d -s "$TMUX_S" -n "$d" "bash $WD/$d.run.sh"; fi
  say "started $d (attempt $(tries "$d"))"
}

done_worker() {   # $1 domain, $2 exit code
  local d=$1 rc=$2 n; n=$(tries "$d")
  if [[ $rc == 0 ]]; then mark "$d" DONE; python3 scripts/ledger.py "$d" DONE - "logs/workers/$d.log" "worker finished; awaiting Lead review" >/dev/null
  elif (( n >= TRIES )); then mark "$d" PARKED; python3 scripts/ledger.py "$d" PARKED - "logs/workers/$d.log" "$n failed attempts" >/dev/null
  else mark "$d" OPEN; python3 scripts/ledger.py "$d" REJECT - "logs/workers/$d.log" "attempt $n rc=$rc" >/dev/null; fi
  tmux kill-window -t "$TMUX_S:$d" 2>/dev/null || true
}

checkpoint() {
  if [[ -f data/atlas.db ]]; then
    qc=$(sqlite3 "file:data/atlas.db?mode=ro" 'PRAGMA quick_check;' 2>&1 | head -1)
    if [[ $qc != ok ]]; then say "quick_check FAILED ($qc): stopping; restore from data/backups/"; touch STOP; return; fi
    scripts/backup_db.sh >> logs/backup.log 2>&1 || say "backup failed"
    python3 scripts/audit.py >> logs/audit.log 2>&1 || say "audit reports problems (logs/audit.log)"
    python3 scripts/verify.py >> logs/verify.log 2>&1 && say "verify: ALL GATES PASS" || say "verify: FAILED (logs/verify.log)"
    python3 scripts/build_site.py >> logs/build.log 2>&1 && say "site rebuilt" || say "site build failed"
  fi
  if [[ ${LOOP_COMMIT:-0} == 1 ]]; then git add -A && ! git diff --cached --quiet && git commit -qm "loop checkpoint $(date -Iminutes)" && say committed; fi
}

say "loop start MAX_PAR=$MAX_PAR"
while [[ ! -f STOP ]]; do
  free=$(df -Pk "$ROOT" | awk 'NR==2{print int($4/1048576)}')
  (( ${free:-99} < 20 )) && { say "disk ${free}G < 20G: stopping"; break; }
  live=0
  for d in $(items); do
    [[ $(state "$d") == RUNNING ]] || continue
    if [[ -f $WD/$d.exit ]]; then done_worker "$d" "$(cat "$WD/$d.exit")"; checkpoint
    elif ! pgrep -f -- "$WD/$d.run.sh" >/dev/null; then say "$d worker vanished without exit marker"; done_worker "$d" 1; checkpoint
    else live=$((live + 1)); fi
  done
  open=$(for d in $(items); do [[ $(state "$d") == OPEN ]] && echo "$d"; done)
  if (( live == 0 )) && [[ -z $open ]]; then say "queue empty"; checkpoint; break; fi
  for d in $open; do (( live >= MAX_PAR )) && break; start "$d"; live=$((live + 1)); done
  sleep "$NAP"
done
say "loop end"
