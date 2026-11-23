"""Helpers shared by every germany-atlas domain module (original implementation).

Public API (see docs/INGEST_CONTRACT.md):
    fetch, fetch_json, fetch_post_json, raw_path, save_raw, source_id_for, archive,
    upsert, clean, to_int, to_eur, now, slug, name_norm, parse_register, secret,
    html_to_text, document_text, selftest_report, db, main

Only ingest/run.py opens data/atlas.db for writing; db()/main() delegate to it so a module run
as `python3 -m ingest.domains.<x>` still goes through the single-writer lock.
"""
from __future__ import annotations

import hashlib
import html as _html
import json
import os
import re
import sys
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "atlas.db"
RAW = ROOT / "data" / "raw"
REAL_RAW = RAW
# Lead 2026-11-23: selftests and unit tests never write to the archived/cached sources. Under a test flag
# (--test / --selftest / --shape-test), under `python -m unittest` or with ATLAS_RAW_SANDBOX=1, RAW points at a
# throw-away sandbox under data/ (source_id_for needs paths under ROOT); raw_path()/cached_path() copy a real cached
# file into the sandbox on first use (copy-on-read), so tests can read the cache while every write lands in the
# sandbox. ATLAS_RAW_SANDBOX=0 disables it. ingest.run never passes a test flag.
_TEST_FLAGS = ("--test", "--selftest", "--shape-test")


def _raw_sandbox_wanted() -> bool:
    env = os.environ.get("ATLAS_RAW_SANDBOX")
    if env in ("0", "1"):
        return env == "1"
    a0 = os.path.basename(sys.argv[0]) if sys.argv and sys.argv[0] else ""
    return any(a in _TEST_FLAGS for a in sys.argv[1:]) or "unittest" in (sys.argv[0] if sys.argv else "") \
        or a0 in ("pytest", "py.test") or "pytest" in sys.modules


RAW_SANDBOX = None
if _raw_sandbox_wanted():
    import atexit as _atexit
    import shutil as _shutil
    import tempfile as _tempfile
    (ROOT / "data").mkdir(exist_ok=True)
    RAW_SANDBOX = Path(_tempfile.mkdtemp(prefix="raw_sandbox_", dir=ROOT / "data"))
    _atexit.register(_shutil.rmtree, RAW_SANDBOX, True)
    RAW = RAW_SANDBOX


def _cow(p: Path) -> Path:
    """In the test sandbox: copy the real cached file (and its .meta.json / .txt siblings) in on first use."""
    if RAW_SANDBOX is None or p.exists():
        return p
    try:
        rel = p.relative_to(RAW)
    except ValueError:
        return p
    real = REAL_RAW / rel
    if real.exists():
        import shutil as _sh
        p.parent.mkdir(parents=True, exist_ok=True)
        for src in (real, real.with_suffix(".meta.json"), Path(str(real) + ".txt")):
            if src.exists():
                _sh.copy2(src, RAW / src.relative_to(REAL_RAW))
    return p
LOGS = ROOT / "logs"
LOCK = ROOT / "data" / "atlas.lock"
SCHEMA = ROOT / "ingest" / "schema.sql"
# ISO 3166-2:DE letter code -> 2-digit Land AGS (geo_land.abbr -> geo_land.ags)
LAND_AGS = {"SH": "01", "HH": "02", "NI": "03", "HB": "04", "NW": "05", "HE": "06", "RP": "07", "BW": "08",
            "BY": "09", "SL": "10", "BE": "11", "BB": "12", "MV": "13", "SN": "14", "ST": "15", "TH": "16"}
ENV_FILE = Path(os.environ.get("GERMANY_ATLAS_ENV", Path.home() / ".config" / "germany-atlas" / "env"))
UA = "germany-atlas/1.0 (public-record research on homelessness in Germany; local, non-commercial)"
MIN_INTERVAL = 1.0                     # seconds between outgoing requests, per process

_WS = re.compile(r"[\s\u00a0\u2007\u2009\u202f]+")
_last_request = [0.0]


# ------------------------------------------------------------------ small utilities
def now() -> str:
    """Local time with offset (Europe/Berlin on the deck), second precision."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean(v):
    """Collapse all whitespace (incl. NBSP / thin space), strip; '' -> None. Numbers pass through."""
    if v is None or isinstance(v, (int, float)):
        return v
    v = _WS.sub(" ", str(v)).strip()
    return v or None


def to_int(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(round(v))
    f = to_eur(v)
    return None if f is None else int(round(f))


def to_eur(v):
    """Parse '1.234,56', '1 234,56', '1234.56', '1,234.56' or a number -> float. None if empty."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = _WS.sub("", str(v)).replace("€", "").replace("EUR", "").strip()
    if not s:
        return None
    neg = s.startswith("-")
    s = s.lstrip("+-")
    if "," in s and "." in s:          # whichever comes last is the decimal mark
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s:
        s = s.replace(",", ".") if re.fullmatch(r"\d+,\d{1,2}|\d+,\d{4,}", s) else s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")         # German thousands dots
    try:
        return -float(s) if neg else float(s)
    except ValueError:
        return None


def slug(s: str, maxlen: int = 80) -> str:
    s = (s or "").lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:maxlen] or "x"


# ------------------------------------------------------------------ names & registers
_FOLD = str.maketrans({"Ä": "AE", "Ö": "OE", "Ü": "UE", "ß": "SS", "ẞ": "SS"})
# Legal-form tokens, matched on the folded upper-case string *before* punctuation is removed,
# longest first so "gemeinnützige GmbH" goes before "GmbH".
_LEGAL_FORMS = [
    r"GEMEINNUETZIGE GESELLSCHAFT MIT BESCHRAENKTER HAFTUNG", r"GESELLSCHAFT MIT BESCHRAENKTER HAFTUNG",
    r"UNTERNEHMERGESELLSCHAFT \(?HAFTUNGSBESCHRAENKT\)?", r"\(?HAFTUNGSBESCHRAENKT\)?",
    r"KOERPERSCHAFT DES OEFFENTLICHEN RECHTS", r"ANSTALT DES OEFFENTLICHEN RECHTS",
    r"(?<=STIFTUNG )DES (BUERGERLICHEN|PRIVATEN|OEFFENTLICHEN) RECHTS", r"RECHTSFAEHIGE(?= STIFTUNG)",
    r"EINGETRAGENER VEREIN", r"EINGETRAGENE GENOSSENSCHAFT",
    r"G\.?\s?GMBH", r"GMBH\s+UND\s+CO\.?\s*KG", r"GMBH", r"MBH", r"G\.?\s?UG", r"UG",
    r"G\.?\s?AG", r"AG", r"KGAA", r"KG", r"OHG", r"GBR", r"E\.?\s?G\.?(?=\s|$)",
    r"E\.?\s?V\.?(?=\s|$)", r"K\.?\s?D\.?\s?OE\.?\s?R\.?", r"A\.?\s?OE\.?\s?R\.?",
    r"INC\.?", r"LLC", r"LTD\.?",
]
_LEGAL_RE = re.compile(r"(?<![A-Z0-9])(" + "|".join(_LEGAL_FORMS) + r")(?![A-Z0-9])")
_STOP = re.compile(r"\b(GEMEINNUETZIGE[RSN]?|DER|DIE|DAS|DES|DEN|DEM|FUER|UND|IN|IM|ZU|ZUR|ZUM|VON|VOM|MIT|E|V|THE|OF|AND)\b")


def name_norm(s: str | None) -> str:
    """Matching key for organisation names.

    'Arbeiterwohlfahrt Berlin Spree-Wuhle e. V.'   -> 'ARBEITERWOHLFAHRT BERLIN SPREE WUHLE'
    'ARBEIT und LEBEN Berlin-Brandenburg gGmbH'    -> 'ARBEIT LEBEN BERLIN BRANDENBURG'
    'Stiftung SPI'                                 -> 'STIFTUNG SPI'   (Stiftung as a word is kept;
                                                      only 'Stiftung des bürgerlichen Rechts' etc. go)
    'Caritasverband für das Erzbistum Berlin KdöR' -> 'CARITASVERBAND ERZBISTUM BERLIN'
    """
    if not s:
        return ""
    t = str(s).upper().translate(_FOLD).replace("&", " UND ")
    t = _LEGAL_RE.sub(" ", t)
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    t = _STOP.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


_REG_PATTERNS = [
    # Berlin Zuwendungsdatenbank style: vr_021507, hrb_12345, gnr_123
    (re.compile(r"^(vr|hra|hrb|gnr|pr)[_\s-]*0*(\d+)\s*([a-z]{0,2})$", re.I), None),
    # 'VR 21507 B', 'HRB 123456 B', 'Amtsgericht Charlottenburg HRB 1234 B'
    (re.compile(r"(?:(Amtsgericht\s+[\wÄÖÜäöüß .-]+?)\s*,?\s*)?\b(VR|HRA|HRB|GnR|PR)\s*0*(\d+)\s*([A-Z]{0,2})\b", re.I), "court"),
    (re.compile(r"\b(R\d{6})\b"), "lobby"),                       # Lobbyregister Registernummer
    (re.compile(r"\b(DE\d{9})\b"), "ust"),
]


def parse_register(raw: str | None) -> dict | None:
    """Raw register string -> {'scheme','court','number','raw'} for org_register, or None."""
    r = clean(raw)
    if not r or r.lower() in ("ohne", "keine", "-", "n/a"):
        return None
    for rx, kind in _REG_PATTERNS:
        m = rx.search(r)
        if not m:
            continue
        if kind is None:
            scheme = {"vr": "VR", "hra": "HRA", "hrb": "HRB", "gnr": "GnR", "pr": "PR"}[m.group(1).lower()]
            num = (m.group(2) + (" " + m.group(3).upper() if m.group(3) else "")).strip()
            return {"scheme": scheme, "court": "", "number": num, "raw": r}
        if kind == "court":
            scheme = {"VR": "VR", "HRA": "HRA", "HRB": "HRB", "GNR": "GnR", "PR": "PR"}[m.group(2).upper()]
            num = (m.group(3) + (" " + m.group(4).upper() if m.group(4) else "")).strip()
            return {"scheme": scheme, "court": clean(m.group(1)) or "", "number": num, "raw": r}
        if kind == "lobby":
            return {"scheme": "LobbyR", "court": "", "number": m.group(1), "raw": r}
        if kind == "ust":
            return {"scheme": "USt-IdNr", "court": "", "number": m.group(1), "raw": r}
    return {"scheme": "other", "court": "", "number": r, "raw": r}


# ------------------------------------------------------------------ secrets
def secret(name: str) -> str | None:
    """Read a secret from the environment or ~/.config/germany-atlas/env (KEY=value, chmod 600).

    Never print or log the return value. Returns None when unset.
    """
    if os.environ.get(name):
        return os.environ[name]
    if ENV_FILE.exists():
        if ENV_FILE.stat().st_mode & 0o077:
            raise PermissionError(f"{ENV_FILE} must be chmod 600")
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == name and not k.strip().startswith("#"):
                return v.strip().strip('"').strip("'") or None
    return None


# ------------------------------------------------------------------ fetching & archiving
def _request_key(url: str, method: str = "GET", data=None) -> str:
    """One cache key, used by BOTH fetch() and source_id_for() (fixes the upstream mismatch where
    fetch hashed method+url+body but source_id_for hashed the bare url, so sha256 was never set)."""
    body = "" if data is None else (data if isinstance(data, str) else json.dumps(data, sort_keys=True, default=str))
    basis = url if method.upper() == "GET" and not body else f"{method.upper()} {url}\n{body}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def raw_path(domain: str, url: str, method: str = "GET", data=None) -> Path:
    return _cow(RAW / domain / f"{_request_key(url, method, data)}.bin")


def cached_path(domain: str, url: str, method: str = "GET", data=None) -> Path | None:
    """The archived copy for a request, if any: current key first, then the two key formats written
    by earlier helper versions (bare-url sha1, and sha1(method+url+json(data or {})))."""
    legacy_body = json.dumps(data or {}, sort_keys=True, default=str)
    for p in (raw_path(domain, url, method, data),
              _cow(RAW / domain / f"{hashlib.sha1(url.encode()).hexdigest()}.bin"),
              _cow(RAW / domain / f"{hashlib.sha1((method.upper() + url + legacy_body).encode()).hexdigest()}.bin")):
        if p.exists() and p.stat().st_size:
            return p
    return None


def _log(domain: str, url: str, status, nbytes, note: str = "") -> None:
    LOGS.mkdir(exist_ok=True)
    with open(LOGS / f"ingest-{domain}.jsonl", "a", encoding="utf-8") as f:
        eintrag = dict(ts=now(), url=url, status=status, bytes=nbytes, note=note)
        print(json.dumps(eintrag, ensure_ascii=False), file=f)


def _polite_wait() -> None:
    gap = time.monotonic() - _last_request[0]
    if gap < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - gap)
    _last_request[0] = time.monotonic()


def fetch(url: str, *, method: str = "GET", data=None, headers: dict | None = None, domain: str = "misc",
          force: bool = False, retries: int = 3, timeout: int = 180, binary: bool = False) -> bytes:
    """HTTP GET/POST with an on-disk cache at data/raw/<domain>/<key>.bin (+ .meta.json).

    1 request/second, exponential backoff on 429/5xx/network errors, raises on other 4xx.
    """
    hit = cached_path(domain, url, method, data)
    if hit is not None and not force:
        return hit.read_bytes()
    path = raw_path(domain, url, method, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    hdrs = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "de,en;q=0.8"}
    hdrs.update(headers or {})
    body = None
    if data is not None:
        body = data.encode() if isinstance(data, str) else (
            data if isinstance(data, bytes) else urllib.parse.urlencode(data).encode())
    err = None
    for attempt in range(retries):
        _polite_wait()
        try:
            req = urllib.request.Request(url, data=body, headers=hdrs, method=method.upper())
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read()
                ctype = resp.headers.get("Content-Type", "")
            _log(domain, url, 200, len(content))
            path.write_bytes(content)
            path.with_suffix(".meta.json").write_text(json.dumps(
                {"url": url, "method": method.upper(), "status": 200, "retrieved_at": now(),
                 "content_type": ctype, "bytes": len(content),
                 "sha256": hashlib.sha256(content).hexdigest()}, ensure_ascii=False), encoding="utf-8")
            return content
        except urllib.error.HTTPError as e:
            _log(domain, url, e.code, 0)
            if e.code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f"{url} -> HTTP {e.code}") from e
            err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            _log(domain, url, "error", 0, repr(e))
            err = repr(e)
        time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"fetch failed after {retries} attempts: {url}: {err}")


def fetch_json(url: str, **kw):
    return json.loads(fetch(url, **kw))


def fetch_post_json(url: str, payload, **kw):
    hdr = {"Content-Type": "application/json", **kw.pop("headers", {})}
    return json.loads(fetch(url, method="POST", data=json.dumps(payload), headers=hdr, **kw))


def save_raw(domain: str, dateiname: str, inhalt: bytes) -> Path:
    """Readable copy of a fetched document next to the cache (data/raw/<domain>/<dateiname>)."""
    ziel = _cow(RAW / domain / dateiname)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(inhalt)
    return ziel


def html_to_text(raw: bytes | str) -> str:
    """Deterministic HTML -> text; verify.py searches exactly this output."""
    s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
    s = re.sub(r"(?is)<(script|style|noscript|svg|template)\b.*?</\1\s*>", " ", s)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|h[1-6]|tr|td|th|section|article)\s*>", "\n", s)
    s = _html.unescape(re.sub(r"<[^>]+>", " ", s))
    return "\n".join(x for x in (_WS.sub(" ", ln).strip() for ln in s.splitlines()) if x)


_NUMCELL = re.compile(r"^-?[0-9][0-9 .,]*(?:[eE][-+]?[0-9]+)?$")


def xlsx_col(ci: int) -> str:
    out = ""
    ci += 1
    while ci:
        ci, r = divmod(ci - 1, 26)
        out = chr(65 + r) + out
    return out


def xlsx_row_label(row) -> str:
    cells = [clean(c) for c in row]
    return " ".join(c for c in cells if c and not _NUMCELL.match(str(c)))[:160]


def xlsx_cell_line(sheet: str, ri: int, ci: int, row) -> str:
    """One rendered line per numeric cell: '[sheet!B41] <row text cells> = <value>' (0-based ri/ci)."""
    return f"[{sheet}!{xlsx_col(ci)}{ri + 1}] {xlsx_row_label(row)} = {clean(row[ci])}"


def xlsx_text(data: bytes) -> str:
    """Deterministic text of an XLSX workbook: per row its text cells, then one cell-addressed line per numeric cell."""
    from ingest.domains.institutions_media_orgs import iter_xlsx_sheets
    lines = []
    for sheet, rows in iter_xlsx_sheets(data).items():
        for ri, row in enumerate(rows):
            lab = xlsx_row_label(row)
            if lab:
                lines.append(f"[{sheet}!row {ri + 1}] {lab}")
            for ci, c in enumerate(row):
                c = clean(c)
                if c and _NUMCELL.match(str(c)):
                    lines.append(xlsx_cell_line(sheet, ri, ci, row))
    return "\n".join(lines)


def document_text(path: Path, content_type: str = "") -> str | None:
    """Plain text for an archived document (HTML, PDF, JSON/CSV/XML/plain). None for binaries."""
    head = path.read_bytes()[:2048]
    name = path.name.lower()
    if head.startswith(b"%PDF") or name.endswith(".pdf"):
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True)
        return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None
    if head.startswith(b"PK\x03\x04"):
        # ZIP (e.g. Hamburg open-data GeoJSON download): text of its text members, so verify can check values
        import io, zipfile
        try:
            with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as z:
                is_xlsx = "xl/workbook.xml" in z.namelist()
            if is_xlsx:
                return xlsx_text(path.read_bytes()) or None
            with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as z:
                parts = [f"=== {n}\n" + z.read(n).decode("utf-8", "replace") for n in sorted(z.namelist())
                         if n.lower().endswith((".json", ".geojson", ".csv", ".xml", ".txt", ".gml"))]
            return "\n".join(parts) or None
        except zipfile.BadZipFile:
            return None
    if b"\x00" in head:
        return None
    raw = path.read_bytes()
    if "html" in content_type or name.endswith((".html", ".htm")) or re.search(rb"(?i)<!doctype html|<html", head):
        return html_to_text(raw)
    return raw.decode("utf-8", "replace")


def _register(conn, *, domain: str, url: str, path: Path | None, title=None, publisher=None, license=None,
              slug_=None, license_url=None, attribution=None, notes=None, content_type=None,
              retrieved_at=None) -> int:
    sha = nbytes = local = text_rel = None
    if path is not None and path.exists():
        content = path.read_bytes()
        sha, nbytes, local = hashlib.sha256(content).hexdigest(), len(content), str(path.relative_to(ROOT))
        meta = path.with_suffix(".meta.json")
        if meta.exists() and not content_type:
            m = json.loads(meta.read_text(encoding="utf-8"))
            content_type = m.get("content_type")
            retrieved_at = retrieved_at or m.get("retrieved_at") or m.get("at")
        txt = document_text(path, content_type or "")
        if txt is not None:
            tp = path.with_name(path.name + ".txt")
            tp.write_text(txt, encoding="utf-8")
            text_rel = str(tp.relative_to(ROOT))
        retrieved_at = retrieved_at or datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat(timespec="seconds")
    row = {"domain": domain, "url": url, "title": title, "publisher": publisher, "license": license,
           "retrieved_at": retrieved_at or now(), "bytes": nbytes, "sha256": sha, "slug": slug_,
           "license_url": license_url, "attribution": attribution, "local_path": local, "text_path": text_rel,
           "content_type": content_type, "notes": notes}
    return upsert(conn, "source", row, keys=["domain", "url"])


def source_id_for(conn, url: str, domain: str, *, title=None, publisher=None, license=None,
                  method: str = "GET", data=None, **extra) -> int:
    """Register (or refresh) the source row for a URL fetched with fetch(); returns source.id.

    Finds the archived copy under the same cache key fetch() used, so sha256 / bytes / local_path
    / text_path are filled. A source with no archived copy is registered but fails verify G4.
    """
    path = cached_path(domain, url, method, data)
    return _register(conn, domain=domain, url=url, path=path, title=title,
                     publisher=publisher, license=license,
                     slug_=extra.get("slug"), license_url=extra.get("license_url"),
                     attribution=extra.get("attribution"), notes=extra.get("notes"))


def archive(conn, url: str, *, domain: str, filename: str, title: str, publisher: str, license: str,
            slug: str | None = None, license_url: str | None = None, attribution: str | None = None,
            notes: str | None = None, force: bool = False) -> int:
    """Fetch url into data/raw/<domain>/<filename> (a readable name), register it, return source.id."""
    dest = _cow(RAW / domain / filename)
    if force or not dest.exists():
        content = fetch(url, domain=domain, force=force)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        cache = raw_path(domain, url)
        if cache.with_suffix(".meta.json").exists():
            dest.with_suffix(dest.suffix + ".meta.json").write_text(
                cache.with_suffix(".meta.json").read_text(encoding="utf-8"), encoding="utf-8")
    meta = dest.with_suffix(dest.suffix + ".meta.json")
    m = json.loads(meta.read_text(encoding="utf-8")) if meta.exists() else {}
    return _register(conn, domain=domain, url=url, path=dest, title=title, publisher=publisher, license=license,
                     slug_=slug, license_url=license_url, attribution=attribution, notes=notes,
                     content_type=m.get("content_type"), retrieved_at=m.get("retrieved_at"))


# ------------------------------------------------------------------ writing
def upsert(conn, table: str, row: dict, keys: list[str]) -> int:
    """INSERT … ON CONFLICT(keys) DO UPDATE; None values never overwrite stored values.

    Returns the row's id (rowid). `keys` must match a UNIQUE / PRIMARY KEY constraint.
    """
    # schema-1 names (English columns, table 'pit') are still accepted and mapped to schema 2
    from ingest.migrate import translate
    old_table = table
    table, row = translate(old_table, row)
    keys = [next(iter(translate(old_table, {k: None})[1]), k) for k in keys]
    if table == "metric" and row.get("entity_type") == "land" and row.get("entity_id") in LAND_AGS:
        row = {**row, "entity_id": LAND_AGS[row["entity_id"]]}           # metric rows always carry the Land AGS
    conflict = ", ".join(keys)
    if table == "org" and set(keys) == {"name_norm", "land"}:
        # schema 6 (INGEST_CONTRACT §12): the org key is (name_norm, legal_form_norm, Land). An existing row of the
        # same or a compatible legal form is updated (find_org); otherwise a new row is keyed with its legal form.
        from ingest import orglink
        if row.get("legal_form_norm") is None:
            row = {**row, "legal_form_norm": orglink.legal_form_norm(row.get("name"), row.get("legal_form"))}
        hit = find_org(conn, row.get("name") or "", row.get("land"), nn=row.get("name_norm"),
                       legal_form=row.get("legal_form"), lf=row["legal_form_norm"])
        if hit["org_id"] is not None and hit["how"] in ("exact", "single", "family"):
            sets = [(c, v) for c, v in row.items() if v is not None and c not in ("name_norm", "legal_form_norm", "land")]
            if sets:
                conn.execute(f"UPDATE org SET {', '.join(f'{c}=coalesce(?, {c})' for c, _ in sets)} WHERE id=?",
                             [v for _, v in sets] + [hit["org_id"]])
            return hit["org_id"]
        keys = ["name_norm", "legal_form_norm", "land"]
        conflict = "name_norm, coalesce(legal_form_norm, ''), land"
    row = {spalte: wert for spalte, wert in row.items() if spalte in keys or wert is not None}
    cols = [*row]
    updates = [f"{c}=coalesce(excluded.{c}, {table}.{c})" for c in cols if c not in keys]
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) "
           f"ON CONFLICT ({conflict}) DO "
           + (f"UPDATE SET {', '.join(updates)}" if updates else f"UPDATE SET {keys[0]}={keys[0]}")
           + " RETURNING rowid")
    return conn.execute(sql, [row[c] for c in cols]).fetchone()[0]


# ------------------------------------------------------------------ org entity resolution (schema 5)
def canonical_org(conn, org_id):
    """The canonical org id for any org id (an alias row resolves to its canonical org)."""
    from ingest import orglink
    return orglink.canonical(conn, org_id)


def resolve_org(conn, *, register=None, ust_id=None, lei=None, qid=None, ba_traeger=None):
    """Canonical org id that holds one of these hard ids, or None. Call it BEFORE creating an org row.

    register: a register string as published ('VR 21507 B', 'HRB 26997 (AG Köln)', 'vr_021507', 'R001276');
    ust_id: 'DE123456789'; lei: 20 characters; qid: 'Q123' or a wikidata.org URL; ba_traeger: BA Jobcenter Nr.
    Raises ValueError if the ids already name two canonical orgs (that is a G11 failure for the Lead).
    """
    from ingest import orglink
    return orglink.resolve(conn, register=register, ust_id=ust_id, lei=lei, qid=qid, ba_traeger=ba_traeger)


def find_org(conn, name, land=None, *, legal_form=None, nn=None, lf="?", any_land=False, compatible=None) -> dict:
    """Name step of org resolution (schema 6, INGEST_CONTRACT §12). Call it only after resolve_org() found nothing.

    The key is (name_norm, legal_form_norm, Land). Returns dict(org_id, how, legal_form_norm, candidates, taken):
      how='exact'   a row with the same name_norm and the same legal form (both known) -> reuse
      how='family'  same name_norm, legal form of the same family (GmbH/gGmbH, KöR/KdöR), the only one -> reuse
      how='single'  one side's legal form is unknown and exactly one candidate exists -> reuse
      how='ambiguous' the record's legal form is unknown and ≥ 2 candidates exist -> org_id None: create a new row
                    and flag it (flag_new_org); never pick one. If the NULL-form key itself is taken, that row is
                    returned with how='ambiguous_existing' (it is the record's exact key) and the caller flags the link.
      how='new'     no candidate.
    `compatible(cid) -> bool` drops candidates the caller knows are another entity (a different register number);
    taken=True when such a dropped row holds the new row's exact key. A name match is a flagged name_fuzzy link
    wherever the caller records links."""
    from ingest import orglink
    nn = nn or name_norm(name)
    lf = orglink.legal_form_norm(name, legal_form) if lf == "?" else lf
    sql = "SELECT id, legal_form_norm, land FROM org WHERE name_norm=?" + ("" if any_land else " AND land IS ?")
    rows = conn.execute(sql + " ORDER BY land IS NULL, id", (nn,) if any_land else (nn, land)).fetchall()
    cands, taken = {}, False
    for oid, f, ld in rows:
        cid = orglink.canonical(conn, oid)
        if compatible is not None and not compatible(cid):
            if f == lf and ld == land:
                taken = True
            continue
        if cid not in cands:
            cands[cid] = (orglink.legal_form_norm(*conn.execute("SELECT name, legal_form FROM org WHERE id=?", (cid,)).fetchone())
                          if cid != oid else f)
    out = dict(org_id=None, how="new", legal_form_norm=lf, candidates=sorted(cands), taken=taken)
    if not cands:
        return out
    if lf is not None:
        same = [c for c, f in cands.items() if f == lf]
        fam = [c for c, f in cands.items() if orglink.same_form_family(f, lf)]
        if same:
            return {**out, "org_id": same[0], "how": "exact"}
        if len(fam) == 1:
            return {**out, "org_id": fam[0], "how": "family"}
        if len(cands) == 1 and next(iter(cands.values())) is None:
            return {**out, "org_id": next(iter(cands)), "how": "single"}
        return out
    if len(cands) == 1:
        return {**out, "org_id": next(iter(cands)), "how": "single"}
    nulls = [r[0] for r in rows if r[1] is None and r[2] == land and orglink.canonical(conn, r[0]) in cands]
    if nulls:
        return {**out, "org_id": orglink.canonical(conn, nulls[0]), "how": "ambiguous_existing"}
    return {**out, "how": "ambiguous"}


def flag_new_org(conn, org_id: int, source_id: int) -> int | None:
    """After inserting an org row with an unknown legal form: if other canonical orgs share its name_norm (same Land,
    or any Land when its Land is unknown), write a flagged org_link so the Lead reviews the split (§12)."""
    from ingest import orglink
    nn, lf, land, name = conn.execute("SELECT name_norm, legal_form_norm, land, name FROM org WHERE id=?", (org_id,)).fetchone()
    if lf is not None:
        return None
    sql = "SELECT id FROM org WHERE name_norm=? AND id<>? AND canonical_org_id IS NULL" + ("" if land is None else " AND land IS ?")
    others = [r[0] for r in conn.execute(sql, (nn, org_id) if land is None else (nn, org_id, land))]
    if not others:
        return None
    return orglink.link(conn, record_kind="org_name", record_key=f"{nn}|{land or '-'}|new#{org_id}", org_id=org_id,
                        method="name_fuzzy", confidence=0.5, source_id=source_id, record_name=name,
                        note=f"legal form unknown; {len(others)} existing org(s) with this name ("
                             + ", ".join(f"#{o}" for o in others[:5]) + ") not matched: new row (INGEST_CONTRACT §12)")


def ensure_org(conn, name, land, source_id, *, legal_form=None, register=None, ust_id=None, lei=None, qid=None,
               ba_traeger=None, record_kind=None, record_key=None, compatible=None, **cols) -> int | None:
    """Schema 6 helper for new code: hard ids (resolve_org) -> name step (find_org) -> new row keyed
    (name_norm, legal_form_norm, Land). With record_kind/record_key, a name match is a flagged name_fuzzy link and
    a new row an origin link. Returns the canonical org id, or None if the key is held by a different entity."""
    from ingest import orglink
    hit = resolve_org(conn, register=register, ust_id=ust_id, lei=lei, qid=qid, ba_traeger=ba_traeger)
    if hit:
        return hit
    nn = name_norm(name)
    if not nn:
        return None
    r = find_org(conn, name, land, legal_form=legal_form, nn=nn, compatible=compatible)
    if r["org_id"] is not None:
        row = conn.execute("SELECT source_id, name_norm, legal_form_norm, land FROM org WHERE id=?", (r["org_id"],)).fetchone()
        own = (r["how"] in ("exact", "single") and tuple(row) == (source_id, nn, r["legal_form_norm"], land))
        if record_kind and record_key and own:
            # same name_norm + legal form + Land, and the row was created from this very source: a re-run, not a guess
            link_org(conn, record_kind=record_kind, record_key=record_key, org_id=r["org_id"], method="origin",
                     confidence=1.0, source_id=source_id, record_name=name)
        elif record_kind and record_key:
            link_org(conn, record_kind=record_kind, record_key=record_key, org_id=r["org_id"], method="name_fuzzy",
                     confidence=0.9 if r["how"] == "exact" else 0.7, source_id=source_id, record_name=name,
                     note=f"name step: {r['how']} (name_norm + legal form + Land, INGEST_CONTRACT §12)")
        return r["org_id"]
    if r["taken"]:
        return None
    vals = {"name": name, "name_norm": nn, "legal_form": legal_form, "legal_form_norm": r["legal_form_norm"],
            "land": land, "source_id": source_id, **{k: v for k, v in cols.items() if v is not None}}
    vals = {k: v for k, v in vals.items() if v is not None or k == "land"}
    oid = conn.execute(f"INSERT INTO org({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))}) RETURNING id",
                       list(vals.values())).fetchone()[0]
    flagged = flag_new_org(conn, oid, source_id)       # legal form unknown and namesakes exist -> flagged link
    if flagged is None and record_kind and record_key:
        link_org(conn, record_kind=record_kind, record_key=record_key, org_id=oid, method="origin", confidence=1.0,
                 source_id=source_id, record_name=name)
    return oid


def link_org(conn, *, record_kind: str, record_key, org_id: int, method: str, confidence: float, source_id: int,
             record_name=None, id_value=None, source_system=None, note=None) -> int:
    """Record which canonical org a source-level record resolves to (org_link). Returns the link id.

    method: register_id | lei | ust_id | wikidata_qid (id_value required: use orglink.register_keys(),
    orglink.ust_key(), orglink.lei_key(), orglink.qid_key()) | name_fuzzy (always flagged for review) |
    manual (Lead only) | origin (the org row was created from this very record).
    """
    from ingest import orglink
    return orglink.link(conn, record_kind=record_kind, record_key=record_key, org_id=org_id, method=method,
                        confidence=confidence, source_id=source_id, record_name=record_name, id_value=id_value,
                        source_system_=source_system, note=note)


def rebuild_search(conn) -> int:
    conn.execute("DELETE FROM search_fts")
    feeds = [
        ("land", "SELECT ags, name, coalesce(bez,'') || ' ' || coalesce(abbr,'') || ' AGS ' || ags FROM geo_land"),
        ("kreis", "SELECT ags, name, coalesce(bez,'') || ' AGS ' || ags FROM geo_kreis"),
        ("gemeinde", "SELECT ags, name, 'Gemeinde AGS ' || ags FROM geo_gemeinde"),
        ("org", "SELECT id, name, coalesce(legal_form,'') || ' ' || coalesce(ort,'') || ' ' || coalesce(register_id,'') FROM org"
                + (" WHERE canonical_org_id IS NULL" if "canonical_org_id" in {r[1] for r in conn.execute("PRAGMA table_info(org)")} else "")),
        ("person", "SELECT p.id, p.funktionstraeger, p.funktion || ' · ' || coalesce(o.name, p.org_bezeichnung, '') FROM org_person p LEFT JOIN org o ON o.id=p.org_id"),
        ("law", "SELECT id, coalesce(short_name || ' – ', '') || coalesce(title,''), coalesce(citation,'') || ' ' || coalesce(summary,'') FROM law"),
        ("facility", "SELECT id, name, coalesce(kind,'') || ' ' || coalesce(ort,'') FROM facility"),
        ("doc", "SELECT id, title, coalesce(herausgeber,'') || ' ' || coalesce(zusammenfassung,'') FROM doc"),
        ("media", "SELECT id, title, coalesce(herausgeber,'') FROM media"),
        ("source", "SELECT id, coalesce(title, url), coalesce(publisher,'') || ' ' || url FROM source"),
    ]
    for kind, sql in feeds:
        conn.execute(f"INSERT INTO search_fts(kind, ref, title, body) SELECT '{kind}', * FROM ({sql})")
    return conn.execute("SELECT count(*) FROM search_fts").fetchone()[0]


def selftest_report(conn, domain: str, table: str, where: str = "1=1", n: int = 3) -> None:
    total = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
    print(f"[{domain}] {table}: {total} rows")
    cur = conn.execute(f"SELECT * FROM {table} WHERE {where} ORDER BY random() LIMIT {int(n)}")
    names = [d[0] for d in cur.description]
    for r in cur.fetchall():
        print("  ", dict(zip(names, r)))


# ------------------------------------------------------------------ direct-invocation guard
# Only the runner (`python3 -m ingest.run <domain>`) may open data/atlas.db. A domain module started
# directly (`python3 -m ingest.domains.x ...` or `python3 ingest/domains/x.py`) gets worker tools at most
# (offline tests, in-memory dry runs, scratch DBs); run.open_db() refuses the canonical DB for it.

def direct_domain_invocation() -> str | None:
    """Name of the domain module running as __main__, or None when the process was started otherwise."""
    main_mod = sys.modules.get("__main__")
    spec_name = getattr(getattr(main_mod, "__spec__", None), "name", "") or ""
    if spec_name.startswith("ingest.domains."):
        return spec_name
    datei = getattr(main_mod, "__file__", None)
    if datei and Path(datei).resolve().parent == (ROOT / "ingest" / "domains").resolve():
        return Path(datei).stem
    return None


def is_canonical_db(path) -> bool:
    """True for data/atlas.db of this checkout, and for any file named atlas.db (other worktrees)."""
    p = Path(path).resolve()
    return p == DB.resolve() or p.name == "atlas.db"


def no_direct_run(domain: str, argv=None) -> int:
    """__main__ of a module without worker tools: strict flags, then refuse (exit 2)."""
    import argparse
    ap = argparse.ArgumentParser(prog=f"python3 -m {direct_domain_invocation() or domain}", allow_abbrev=False,
                                 description=f"No direct entry point. The Lead runs: python3 -m ingest.run {domain}")
    ap.parse_args(argv)
    print(f"REFUSED: this module is not run directly; data/atlas.db is written only by "
          f"`python3 -m ingest.run {domain}`", file=sys.stderr)
    return 2


def db():
    """Writer connection under the single-writer lock (delegates to ingest.run)."""
    from ingest import run as _run
    _run.take_lock()
    return _run.open_db()


def main(domain: str, fn=None, selftest_table: str | None = None) -> int:
    """Former plain-run entry point of domain modules. Direct runs no longer write the DB: refuse."""
    print(f"REFUSED: run `python3 -m ingest.run {domain}` (the runner is the only writer of data/atlas.db)",
          file=sys.stderr)
    return 2
