# Queue

- One work item per file: `queue/<NN>-<domain>.md`, where `<NN>` is the priority order. The first line reads `# <domain> — <goal in one line>`.
- Item state lives in `queue/state/<domain>.status` and is one of `OPEN`, `RUNNING`, `DONE`, `PARKED` or `BLOCKED`.
  A `BLOCKED` item names the exact key, URL or owner decision that would unblock it.
- `scripts/loop.sh` starts up to `MAX_PAR` workers on `OPEN` items. A worker reads `docs/INGEST_CONTRACT.md`,
  delivers on `worker/<domain>`, and does not commit to `main`. The Lead reviews, merges, runs the ingest, and logs a verdict.
