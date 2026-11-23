"""The single writer for data/atlas.db. Runs exactly ONE domain per process.

    python3 -m ingest.run <domain> [--refresh] [--cfg '{"key": 1}']
    python3 -m ingest.run --list
    python3 -m ingest.run --schema            # apply ingest/schema.sql and exit

Discipline (original implementation; the idea comes from the US atlas's operational lessons):
  * exclusive non-blocking flock(2) on data/atlas.lock for the life of the process. If another
    writer holds it we refuse to start (exit 75 = EX_TEMPFAIL); we never wait and write alongside it.
  * PRAGMA journal_mode=WAL, synchronous=FULL, foreign_keys=ON, busy_timeout
  * the domain's run(conn, cfg) executes inside ONE transaction. The connection handed to the module
    ignores its own commit() calls and runs executescript() statement by statement, so a module that
    commits mid-way (as reference-style modules do) cannot leave a half-written domain behind.
  * every run is logged in ingest_run and appended to LEDGER.md / ledger.jsonl
  * schema 5 (G11): per-column non-NULL counts are snapshotted into ingest_colstats before and after the
    module runs, org_link is synced for every org row, org_register row and award inside the same
    transaction, and reports/join_gaps.md is rewritten after the commit
"""
from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import traceback
from pathlib import Path

from ingest import common

EX_TEMPFAIL = 75
_held: list = []

# additive migrations for databases created by an older schema: (table, column, decl)
MIGRATIONS: list[tuple[str, str, str]] = []


class LockHeld(RuntimeError):
    pass


def take_lock():
    """Take the writer lock once per process (re-entrant inside the same process)."""
    if _held:
        return _held[0]
    common.LOCK.parent.mkdir(parents=True, exist_ok=True)
    fh = open(common.LOCK, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.seek(0)
        who = fh.read().strip() or "unknown holder"
        fh.close()
        raise LockHeld(f"{common.LOCK} is held ({who}); one writer at a time, refusing to start")
    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} host={socket.gethostname()} since={common.now()} argv={' '.join(sys.argv)}\n")
    fh.flush()
    _held.append(fh)
    return fh


class AtlasConnection(sqlite3.Connection):
    """Connection whose commit() is deferred while a runner transaction is open."""
    runner_txn = False

    def commit(self):
        if not self.runner_txn:
            super().commit()

    def executescript(self, script):
        if not self.runner_txn:
            return super().executescript(script)
        buf = ""
        for line in script.splitlines(keepends=True):
            buf += line
            if sqlite3.complete_statement(buf):
                stmt = buf.strip()
                buf = ""
                if stmt and not stmt.upper().startswith(("BEGIN", "COMMIT", "END")):
                    self.execute(stmt)
        if buf.strip():
            self.execute(buf)
        return self.cursor()

    def real_commit(self):
        super().commit()


def open_db(path: Path | None = None) -> AtlasConnection:
    path = Path(path or common.DB)
    direct = common.direct_domain_invocation()
    if direct and common.is_canonical_db(path):
        raise SystemExit(f"REFUSED: {direct} was started directly; only `python3 -m ingest.run <domain>` "
                         f"opens {path.name}. Use --db <scratch path> or an in-memory dry run.")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=60, factory=AtlasConnection, isolation_level=None)
    conn.row_factory = sqlite3.Row
    mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    if str(mode).lower() != "wal":
        raise RuntimeError(f"journal_mode={mode}, expected wal")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=60000")
    schema = common.SCHEMA.read_text(encoding="utf-8")
    from ingest import migrate as _mig
    if _mig.is_legacy(conn):          # schema 1 (English columns) -> schema 2, lossless, one transaction
        _mig.migrate(conn, schema, log=lambda m: print(m, file=sys.stderr))
    if _mig.needs_v6(conn):           # schema 6: org rebuilt with the legal form in its key, before schema.sql's index
        _mig.upgrade_6(conn, schema, log=lambda m: print(m, file=sys.stderr))
    conn.executescript(schema)
    _mig.upgrade(conn, log=lambda m: print(m, file=sys.stderr))     # schema 2 -> 3 (idempotent)
    if conn.execute("PRAGMA user_version").fetchone()[0] < _mig.SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version={_mig.SCHEMA_VERSION}")
    for table, col, decl in MIGRATIONS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
    return conn


def write_join_gaps(conn) -> str:
    """reports/join_gaps.md after every run (read-only on the committed DB; a failure never fails the run)."""
    try:
        from ingest import join_gaps
        head = join_gaps.write(conn)
        return f"reports/join_gaps.md: {head}"
    except Exception as exc:  # noqa: BLE001
        return f"reports/join_gaps.md NOT written: {type(exc).__name__}: {exc}"


def git_rev() -> str | None:
    r = subprocess.run(["git", "-C", str(common.ROOT), "rev-parse", "--short", "HEAD"], capture_output=True, text=True)
    return r.stdout.strip() or None


def ledger(domain: str, verdict: str, rows, evidence: str, note: str = "") -> None:
    """Append one row to ledger.jsonl and LEDGER.md (append-only)."""
    rec = {"ts": common.now(), "domain": domain, "verdict": verdict, "rows": rows, "evidence": evidence, "note": note}
    with open(common.ROOT / "ledger.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    md = common.ROOT / "LEDGER.md"
    if not md.exists():
        md.write_text("# Ledger — germany-atlas\n\n| ts | domain | verdict | rows | evidence | note |\n|---|---|---|---|---|---|\n",
                      encoding="utf-8")
    cell = lambda s: str(s).replace("|", "\\|").replace("\n", " ")  # noqa: E731
    with open(md, "a", encoding="utf-8") as f:
        f.write(f"| {rec['ts']} | {cell(domain)} | {cell(verdict)} | {cell(rows)} | {cell(evidence)} | {cell(note)} |\n")


def list_domains() -> list[str]:
    return sorted(p.stem for p in (common.ROOT / "ingest" / "domains").glob("*.py") if not p.stem.startswith("_"))


def load_cfg(domain: str, extra: dict | None = None) -> dict:
    p = common.ROOT / "ingest" / "domains" / f"{domain}.json"
    cfg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg.update(extra or {})
    return cfg


def run_domain(domain: str, cfg: dict | None = None, db_path: Path | None = None) -> int:
    if domain not in list_domains():
        print(f"unknown domain {domain!r}; available: {', '.join(list_domains())}", file=sys.stderr)
        return 2
    try:
        take_lock()
    except LockHeld as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return EX_TEMPFAIL
    conn = open_db(db_path)
    started = common.now()
    run_id = conn.execute(
        "INSERT INTO ingest_run(domain, ts, started_at, status, ok, host, pid, git_rev) VALUES (?,?,?,?,?,?,?,?)",
        (domain, started, started, "running", 0, socket.gethostname(), os.getpid(), git_rev())).lastrowid
    mod = importlib.import_module(f"ingest.domains.{domain}")
    if not callable(getattr(mod, "run", None)):
        print(f"ingest/domains/{domain}.py has no run(conn, cfg)", file=sys.stderr)
        return 2
    from ingest import orglink
    conn.execute("BEGIN IMMEDIATE")
    conn.runner_txn = True
    try:
        orglink.snapshot(conn, run_id, "before")          # G11c: per-column non-NULL counts before the run
        before = conn.total_changes
        res = mod.run(conn, load_cfg(domain, cfg)) or {}
        changes = conn.total_changes - before
        link_stats = orglink.sync(conn, run_id)            # org_link for every org row, register row and award
        n_search = common.rebuild_search(conn)
        orglink.snapshot(conn, run_id, "after")
        conn.runner_txn = False
        conn.real_commit()
    except BaseException as exc:  # noqa: BLE001
        conn.runner_txn = False
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        err = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        conn.execute("UPDATE ingest_run SET finished_at=?, status='failed', ok=0, rows=0, error=? WHERE id=?",
                     (common.now(), err[:4000], run_id))
        traceback.print_exc()
        ledger(domain, "FAILED", 0, f"ingest_run #{run_id}", err[:300])
        return 1
    rows = res.get("rows", changes) if isinstance(res, dict) else changes
    notes = (res.get("notes", "") if isinstance(res, dict) else "") or ""
    conn.execute("UPDATE ingest_run SET finished_at=?, status='ok', ok=1, rows=?, notes=? WHERE id=?",
                 (common.now(), rows, notes[:8000], run_id))
    qc = conn.execute("PRAGMA quick_check").fetchone()[0]
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    gaps_line = write_join_gaps(conn)
    conn.close()
    print(f"[{domain}] OK run #{run_id}: rows={rows} row_changes={changes} search={n_search} quick_check={qc}")
    print(f"[{domain}] org_link: {json.dumps(link_stats, sort_keys=True)}; {gaps_line}")
    print(f"[{domain}] {notes}")
    ledger(domain, "INGESTED" if qc == "ok" else "INGESTED-QC-FAIL", rows, f"ingest_run #{run_id}; quick_check {qc}",
           notes[:400])
    return 0 if qc == "ok" else 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("domain", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--schema", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="pass refresh=True / force re-download to the module")
    ap.add_argument("--cfg", default=None, help="JSON merged into the module cfg")
    a = ap.parse_args(argv)
    if a.list:
        print("\n".join(list_domains()))
        return 0
    if a.schema:
        try:
            take_lock()
        except LockHeld as e:
            print(f"REFUSED: {e}", file=sys.stderr)
            return EX_TEMPFAIL
        open_db().close()
        print(f"schema applied: {common.DB}")
        return 0
    if len(a.domain) != 1:
        ap.error("exactly one domain per process (single-writer discipline)")
    extra = json.loads(a.cfg) if a.cfg else {}
    if a.refresh:
        extra.update(refresh=True, force=True)
    return run_domain(a.domain[0], extra)


if __name__ == "__main__":
    sys.exit(main())
