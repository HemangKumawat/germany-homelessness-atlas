"""geo_bevoelkerung: population for Bund, Länder and Kreise, and the Gemeinden (Lead-owned domain).

Sources (each archived under data/raw/geo_bevoelkerung/ and registered with its licence):
  * Destatis GENESIS-Online 12411-0001 (Deutschland), 12411-0010 (Länder), 12411-0015 (Kreise):
    Fortschreibung des Bevölkerungsstandes, Stichtag 31.12., anonymous JSON data cube + structure.
    Stored as metric 'einwohner' (entity de/land/kreis, year = Stichtag year, period = YYYY-12-31) for the
    Stichtage 31.12.2021–2025, i.e. the evening before each 22971 Stichtag 31.01.2022–2026. Destatis basis:
    Zensus 2011 up to 2021, Zensus 2022 from 31.12.2022 on (break in the series; noted on every row).
  * Destatis Gemeindeverzeichnis (GV-ISys), "Alle politisch selbständigen Gemeinden mit ausgewählten
    Merkmalen am 30.09.2026": one geo_gemeinde row per Gemeinde (Satzart 60) with AGS, name, kind,
    area, population 31.12.2025 (Gebietsstand 30.09.2026) and the published centre coordinates.
  * BKG Verwaltungsgebiete 1:250 000 (VG250), Ebenen, Stand 01.01.2026: Gemeinde polygons, simplified here
    (Douglas–Peucker 250 m per ring, 4 decimals) into geo_gemeinde.geometry with geometry_source_id.

  * Kreis boundary changes (KREIS_SPLITS): when a city leaves its Landkreis (Hanau 06415, kreisfrei from
    01.01.2026), 12411 has no row for the new Kreis on the previous 31.12. and the old Kreis's 31.12. figure
    still contains the city. From the GV-ISys Gemeinde populations (same Stichtag 31.12., new boundaries):
      - the new Kreis gets metric 'einwohner' (only when it has a single Gemeinde, so the figure is printed
        verbatim in the GV-ISys file, and only if 12411 has no row of its own);
      - the old Kreis gets metric 'einwohner_gebietsstand' = the exact sum of the official Gemeinde figures in
        its new boundaries (no estimate; verify G5/G9 recompute the sum from geo_gemeinde). Its 12411
        'einwohner' row stays unchanged. Before anything is written, old-Kreis sum + new-Kreis sum must equal
        the 12411 figure of the old Kreis exactly. The site prefers 'einwohner_gebietsstand' for the rate.

Only Lead runs write data/atlas.db: python3 -m ingest.run geo_bevoelkerung. Rows another domain created are
never changed. Per-capita rates are not stored; the site computes them at build time.
"""
from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from ingest import common
from ingest.domains import geo_bkg as _gb

DOMAIN = "geo_bevoelkerung"
API = "https://genesis.destatis.de/genesis/api/rest"
PUB_DESTATIS = "Statistisches Bundesamt (Destatis)"
LIC_GENESIS = ("Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0), "
               "© Statistisches Bundesamt (Destatis), 2026")
CUBES = {"12411-0001": ("de", "DINSG"), "12411-0010": ("land", "DLAND"), "12411-0015": ("kreis", "KREISE")}
YEARS = (2021, 2022, 2023, 2024, 2025)       # 31.12.Y precedes the 22971 Stichtag 31.01.(Y+1)

GV_URL = ("https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/Administrativ/"
          "Archiv/GVAuszugQ/AuszugGV3QAktuell.xlsx?__blob=publicationFile&v=22")
GV_FILE = "gv-isys_auszug_30092026.xlsx"
GV_STAND, GV_POP_DATE, GV_POP_YEAR = "30.09.2026", "31.12.2025", 2025
LIC_GV = ("Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0); © Statistisches Bundesamt "
          "(Destatis), 2026, im Auftrag der Herausgebergemeinschaft Statistische Ämter des Bundes und der Länder; "
          "Datei: „Vervielfältigung und Verbreitung, auch auszugsweise, mit Quellenangabe gestattet.“")
VG_URL = "https://daten.gdz.bkg.bund.de/produkte/vg/vg250_ebenen_0101/aktuell/vg250_01-01.utm32s.gpkg.ebenen.zip"
VG_FILE = "vg250_01-01-2026.utm32s.gpkg.ebenen.zip"
SIMPLIFY_M = 250
LAND_ABBR = {ags: abbr for abbr, ags in common.LAND_AGS.items()}
KIND = {"60": "markt", "61": "kreisfreie_stadt", "62": "stadtkreis", "63": "stadt", "64": "gemeinde",
        "65": "gemeindefrei_bewohnt", "66": "gemeindefrei_unbewohnt", "67": "grosse_kreisstadt"}


# (new Kreis, old Kreis, first day in the new boundaries, population year = the 31.12. before it, note)
KREIS_SPLITS = [
    ("06415", "06435", "2026-01-01", 2025,
     "Hanau (Gemeinde 06415000) ist seit 01.01.2026 kreisfrei und gehört nicht mehr zum Main-Kinzig-Kreis"),
]
GEBIETSSTAND_METRIC = "einwohner_gebietsstand"


class ShapeError(RuntimeError):
    """A source no longer has the layout this module was written for; nothing is written."""


# ---------------------------------------------------------------- 12411 cubes
def decode(data: dict, region_var: str):
    """Yield (region, stichtag, value, status) for every cell of a GENESIS JSON cube."""
    ds = data["data"][0]
    ids, sizes = ds["id"], ds["size"]
    inv = {k: {i: c for c, i in ds["dimension"][k]["category"]["index"].items()} for k in ids}
    status = ds.get("status") or ["e"] * len(ds["value"])
    for n, (v, st) in enumerate(zip(ds["value"], status)):
        pos, rest = [], n
        for size in reversed(sizes):
            pos.append(rest % size)
            rest //= size
        key = {k: inv[k][i] for k, i in zip(ids, reversed(pos))}
        yield (key.get(region_var) or "DE"), key["STAG"], v, st


def check_cube(code: str, data: dict, region_var: str) -> None:
    try:
        ds = data["data"][0]
        dims = set(ds["id"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ShapeError(f"GENESIS {code}: no data block ({exc})") from exc
    if "STAG" not in dims or (region_var != "DINSG" and region_var not in dims):
        raise ShapeError(f"GENESIS {code}: dimensions {sorted(dims)} lack STAG/{region_var}")
    have = set(ds["dimension"]["STAG"]["category"]["index"])
    missing = [f"{y}-12-31" for y in YEARS if f"{y}-12-31" not in have]
    if missing:
        raise ShapeError(f"GENESIS {code}: Stichtage {missing} missing")
    if len(ds["value"]) != _prod(ds["size"]):
        raise ShapeError(f"GENESIS {code}: {len(ds['value'])} values for sizes {ds['size']}")


def _prod(xs):
    out = 1
    for x in xs:
        out *= x
    return out


def ingest_population(conn, notes: list) -> int:
    known_kreis = {r[0] for r in conn.execute("SELECT ags FROM geo_kreis")}
    known_land = {r[0] for r in conn.execute("SELECT ags FROM geo_land")}
    totals: dict[tuple[str, int], float] = {}
    staged = []
    for code, (level, region_var) in CUBES.items():
        data_url, struct_url = f"{API}/tables/{code}/data", f"{API}/tables/{code}/structure"
        structure = json.loads(common.fetch(struct_url, domain=DOMAIN, headers={"Accept": "application/json"}))
        data = json.loads(common.fetch(data_url, domain=DOMAIN, headers={"Accept": "application/json"}))
        check_cube(code, data, region_var)
        label = (structure.get("table", {}).get("label") or {}).get("de", code).replace("\n", " ")
        changed = structure.get("table", {}).get("lastChange")
        sid = common.source_id_for(conn, data_url, DOMAIN, title=f"GENESIS-Online {code}: {label}",
                                   publisher=PUB_DESTATIS, license=LIC_GENESIS)
        common.source_id_for(conn, struct_url, DOMAIN, title=f"GENESIS-Online {code} structure (labels, notes)",
                             publisher=PUB_DESTATIS, license=LIC_GENESIS)
        n_year = {y: 0 for y in YEARS}
        for region, stag, value, status in decode(data, region_var):
            year = int(stag[:4])
            if year not in YEARS or status != "e" or value is None:
                continue
            if level == "kreis" and region not in known_kreis:
                raise ShapeError(f"GENESIS {code}: Kreis {region} has data on {stag} but is not in geo_kreis")
            if level == "land" and region not in known_land:
                raise ShapeError(f"GENESIS {code}: Land {region} is not in geo_land")
            n_year[year] += 1
            totals[(level, year)] = totals.get((level, year), 0) + value
            basis = "Zensus 2011" if year < 2022 else "Zensus 2022"
            staged.append({"entity_type": level, "entity_id": "DE" if level == "de" else region,
                           "metric": "einwohner", "year": year, "period": stag, "value": value,
                           "einheit": "persons", "is_est": 0,
                           "anmerkung": (f"Destatis Fortschreibung des Bevölkerungsstandes, Stichtag {stag[8:10]}."
                                         f"{stag[5:7]}.{stag[:4]}, GENESIS {code}, auf Grundlage des {basis} "
                                         f"(Bruch der Reihe zwischen 31.12.2021 und 31.12.2022); "
                                         f"table lastChange {changed}"),
                           "source_id": sid})
        want = {"de": 1, "land": 16, "kreis": 390}[level]
        thin = {y: n for y, n in n_year.items() if n < want}
        if thin:
            raise ShapeError(f"GENESIS {code}: too few regions per Stichtag {thin} (expected >= {want})")
        notes.append(f"{code}: " + ", ".join(f"{y} {n}" for y, n in n_year.items()))
    for y in YEARS:   # the three cubes must agree exactly before anything is written
        de, la, kr = totals[("de", y)], totals[("land", y)], totals[("kreis", y)]
        if not (de == la == kr):
            raise ShapeError(f"12411 {y}-12-31: DE {de:.0f}, sum of Länder {la:.0f}, sum of Kreise {kr:.0f} differ")
    for row in staged:
        common.upsert(conn, "metric", row, keys=["entity_type", "entity_id", "metric", "year"])
    notes.append("12411 DE = sum of Länder = sum of Kreise for " + ", ".join(
        f"31.12.{y} ({totals[('de', y)]:,.0f})".replace(",", ".") for y in YEARS))
    return len(staged)


# ---------------------------------------------------------------- Gemeindeverzeichnis
def _num(text):
    t = (text or "").strip().replace("\u00a0", "")
    if not t:
        return None
    return float(t.replace(",", ".")) if "," in t else float(t)


def parse_gv(raw: bytes) -> list[dict]:
    from ingest.domains.institutions_media_orgs import iter_xlsx_sheets
    sheets = iter_xlsx_sheets(raw)
    name, rows = max(sheets.items(), key=lambda kv: len(kv[1]))
    head = next((i for i, r in enumerate(rows[:20]) if r and r[0].strip() == "Satzart"), None)
    if head is None:
        raise ShapeError(f"GV-ISys {name}: header row 'Satzart' not found")
    h0, h1, h2 = rows[head], rows[head + 1], rows[head + 2]
    expect = [(h0, 7, "Gemeindename"), (h0, 8, "Fläche"), (h0, 9, "Bevölkerung"), (h1, 9, "insgesamt"),
              (h1, 14, "Längengrad"), (h1, 15, "Breitengrad"), (h1, 2, "Land"), (h1, 6, "Gem"),
              (h2, 9, GV_POP_DATE), (h2, 2, GV_STAND)]
    for row, col, word in expect:
        if word not in (row[col] if col < len(row) else ""):
            raise ShapeError(f"GV-ISys {name}: column {col} should mention '{word}', has {row[col] if col < len(row) else None!r}")
    out = []
    for r in rows[head + 3:]:
        if not r or r[0].strip() != "60":
            continue
        ags = r[2] + r[3] + r[4] + r[6]
        if len(ags) != 8 or not ags.isdigit():
            raise ShapeError(f"GV-ISys {name}: malformed AGS parts {r[2:7]}")
        lon, lat = _num(r[14]), _num(r[15])
        if lat == 0 and lon == 0:            # unbewohnte Sondergebiete publish 0/0 as a placeholder
            lat = lon = None
        if lat is not None and not (47.0 <= lat <= 55.2 and 5.5 <= lon <= 15.3):
            raise ShapeError(f"GV-ISys {name}: {ags} centre {lat},{lon} outside Germany")
        pop = _num(r[9])
        out.append({"ags": ags, "name": r[7].strip(), "kind": KIND.get(r[1].strip(), f"tk_{r[1].strip()}"),
                    "einwohner": int(pop) if pop is not None else None, "flaeche_km2": _num(r[8]),
                    "lat": lat, "lon": lon})
    if not 10_000 <= len(out) <= 12_000:
        raise ShapeError(f"GV-ISys {name}: {len(out)} Gemeinden (expected 10,000–12,000)")
    if len({g["ags"] for g in out}) != len(out):
        raise ShapeError(f"GV-ISys {name}: duplicate AGS")
    return out


# ---------------------------------------------------------------- VG250 geometry
def _simplify_ring(ring, tol):
    """Douglas–Peucker for a closed ring: split at the vertex farthest from the start, simplify both halves."""
    if len(ring) < 8:
        return ring
    x0, y0 = ring[0]
    far = max(range(len(ring)), key=lambda k: (ring[k][0] - x0) ** 2 + (ring[k][1] - y0) ** 2)
    left, right = _gb._dp(ring[:far + 1], tol), _gb._dp(ring[far:], tol)
    joined = left[:-1] + right
    return joined if len(joined) >= 4 else ring


def vg250_geometries(zpath: Path) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(zpath) as z:
        member = next(n for n in z.namelist() if n.endswith(".gpkg"))
        z.extract(member, td)
        g = sqlite3.connect(f"file:{Path(td) / member}?mode=ro", uri=True)
        rows = g.execute("SELECT AGS, geom FROM vg250_gem WHERE GF=4").fetchall()
        g.close()
    out = {}
    for ags, blob in rows:
        polys = _gb.parse_gpkg_geom(blob)
        coords = [[[[round(lon, 4), round(lat, 4)] for lat, lon in
                    (_gb.utm32_to_wgs84(x, y) for x, y in _simplify_ring(ring, SIMPLIFY_M))] for ring in rings]
                  for rings in polys]
        out[ags] = json.dumps({"type": "MultiPolygon", "coordinates": coords}, separators=(",", ":"))
    if len(out) < 10_000:
        raise ShapeError(f"VG250: only {len(out)} Gemeinde polygons")
    return out


def ingest_gemeinden(conn, notes: list, force: bool) -> int:
    gv_sid = common.archive(
        conn, GV_URL, domain=DOMAIN, filename=GV_FILE, slug="destatis-gv-isys-30092026",
        title=f"Gemeindeverzeichnis (GV-ISys): Alle politisch selbständigen Gemeinden mit ausgewählten Merkmalen "
              f"am {GV_STAND} (3. Quartal 2026), Bevölkerung {GV_POP_DATE}",
        publisher=PUB_DESTATIS, license=LIC_GV, license_url="https://www.govdata.de/dl-de/by-2-0",
        attribution="© Statistisches Bundesamt (Destatis), 2026",
        notes="Satzart 60 rows; coordinates are the published geografische Mittelpunktkoordinaten.", force=force)
    vg_sid = common.archive(
        conn, VG_URL, domain=DOMAIN, filename=VG_FILE, slug="bkg-vg250-ebenen-2026",
        title="Verwaltungsgebiete 1:250 000 (VG250), Ebenen, Stand 01.01.2026, GeoPackage UTM32s",
        publisher="Bundesamt für Kartographie und Geodäsie (BKG)",
        license="Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)",
        license_url="https://www.govdata.de/dl-de/by-2-0",
        attribution="© GeoBasis-DE / BKG (2026) dl-de/by-2-0, Datenquellen: "
                    "https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf",
        notes="Licence text: dokumentation/nutzungsbedingungen_vg250.pdf inside the archive. Polygons simplified "
              f"by the atlas (Douglas–Peucker {SIMPLIFY_M} m).", force=force)
    gems = parse_gv((common._cow(common.RAW / DOMAIN / GV_FILE)).read_bytes())
    geoms = vg250_geometries(common._cow(common.RAW / DOMAIN / VG_FILE))
    de_pop = conn.execute("SELECT value FROM metric WHERE entity_type='de' AND entity_id='DE' AND metric='einwohner' "
                          "AND year=?", (GV_POP_YEAR,)).fetchone()
    gv_sum = sum(g["einwohner"] or 0 for g in gems)
    if de_pop and abs(gv_sum - de_pop[0]) > 0.001 * de_pop[0]:
        raise ShapeError(f"GV-ISys population sum {gv_sum} vs 12411 DE {de_pop[0]:.0f} on {GV_POP_DATE}")
    kreise = {r[0] for r in conn.execute("SELECT ags FROM geo_kreis")}
    foreign = {r[0] for r in conn.execute("SELECT g.ags FROM geo_gemeinde g JOIN source s ON s.id=g.source_id "
                                          "WHERE s.domain <> ?", (DOMAIN,))}
    tally = {"rows": 0, "geometry": 0, "no_kreis": 0, "foreign": 0}
    for g in gems:
        if g["ags"] in foreign:
            tally["foreign"] += 1
            continue
        kreis = g["ags"][:5]
        if kreis not in kreise:
            tally["no_kreis"] += 1
        geom = geoms.get(g["ags"])
        tally["geometry"] += geom is not None
        common.upsert(conn, "geo_gemeinde", {
            "ags": g["ags"], "land_ags": g["ags"][:2], "kreis_ags": kreis, "land": LAND_ABBR.get(g["ags"][:2]),
            "name": g["name"], "kind": g["kind"], "einwohner": g["einwohner"], "flaeche_km2": g["flaeche_km2"],
            "lat": g["lat"], "lon": g["lon"], "source_id": gv_sid,
            "geometry": geom, "geometry_source_id": vg_sid if geom else None}, keys=["ags"])
        tally["rows"] += 1
    only_vg = len(set(geoms) - {g["ags"] for g in gems})
    notes.append(f"GV-ISys {GV_STAND}: {len(gems)} Gemeinden, population {GV_POP_DATE} sum {gv_sum:,} "
                 f"(= 12411 DE)".replace(",", ".")
                 + f"; {tally['geometry']} with VG250 geometry, {len(gems) - tally['geometry']} without "
                   f"(Gebietsstand differs), {only_vg} VG250 AGS not in GV; Kreis not in geo_kreis: {tally['no_kreis']}; "
                   f"rows of other domains left alone: {tally['foreign']}")
    return tally["rows"]


def ingest_kreis_splits(conn, notes: list) -> int:
    """Kreis populations in the new boundaries after a Kreis split (KREIS_SPLITS); official GV-ISys figures only."""
    gv = conn.execute("SELECT id FROM source WHERE domain=? AND url=?", (DOMAIN, GV_URL)).fetchone()
    if not gv:
        raise ShapeError("Kreis splits need the GV-ISys source (ingest_gemeinden first)")
    gv_sid = gv[0]
    n = 0
    for new, old, since, year, why in KREIS_SPLITS:
        if year != GV_POP_YEAR:
            raise ShapeError(f"split {new}/{old}: population year {year} but GV-ISys gives {GV_POP_DATE}")
        def gem(k):
            return conn.execute("SELECT ags, einwohner FROM geo_gemeinde WHERE kreis_ags=? AND source_id=? ORDER BY ags",
                                (k, gv_sid)).fetchall()
        g_new, g_old = gem(new), gem(old)
        if not g_new or not g_old or any(e is None for _, e in g_new + g_old):
            raise ShapeError(f"split {new}/{old}: Gemeinde populations missing in geo_gemeinde")
        if len(g_new) != 1:
            raise ShapeError(f"split {new}: {len(g_new)} Gemeinden; only a single-Gemeinde new Kreis is supported")
        s_new, s_old = sum(e for _, e in g_new), sum(e for _, e in g_old)
        old_12411 = conn.execute("SELECT value FROM metric WHERE entity_type='kreis' AND entity_id=? AND metric='einwohner' "
                                 "AND year=?", (old, year)).fetchone()
        if not old_12411 or old_12411[0] != s_new + s_old:
            raise ShapeError(f"split {new}/{old}: {s_old} + {s_new} != 12411 {old} {year} "
                             f"({old_12411[0] if old_12411 else None}); Gebietsstand not consistent")
        period, since_de = f"{year}-12-31", f"{since[8:10]}.{since[5:7]}.{since[:4]}"
        own = conn.execute("SELECT m.source_id FROM metric m WHERE m.entity_type='kreis' AND m.entity_id=? "
                           "AND m.metric='einwohner' AND m.year=?", (new, year)).fetchone()
        if own and own[0] != gv_sid:
            notes.append(f"split {new}: a 12411 einwohner row for {year} exists, left unchanged")
        else:
            common.upsert(conn, "metric", {
                "entity_type": "kreis", "entity_id": new, "metric": "einwohner", "year": year, "period": period,
                "value": s_new, "einheit": "persons", "is_est": 0,
                "locator": f"GV-ISys {GV_STAND}, Gemeinde {g_new[0][0]}, Bevölkerung insgesamt",
                "anmerkung": (f"Kreisfreie Stadt seit {since_de}: Bevölkerung am {GV_POP_DATE} = amtliche Zahl der "
                              f"einzigen Gemeinde {g_new[0][0]} (Destatis GV-ISys, Gebietsstand {GV_STAND}, auf Grundlage "
                              f"des Zensus 2022); 12411-0015 führt den Kreis {new} für diesen Stichtag nicht. {why}."),
                "source_id": gv_sid}, keys=["entity_type", "entity_id", "metric", "year"])
            n += 1
        common.upsert(conn, "metric", {
            "entity_type": "kreis", "entity_id": old, "metric": GEBIETSSTAND_METRIC, "year": year, "period": period,
            "value": s_old, "einheit": "persons", "is_est": 0,
            "locator": f"GV-ISys {GV_STAND}: Summe der {len(g_old)} Gemeinden {g_old[0][0]}–{g_old[-1][0]}",
            "anmerkung": (f"Summe der amtlichen Gemeindezahlen: Bevölkerung am {GV_POP_DATE} der {len(g_old)} Gemeinden "
                          f"im Gebietsstand ab {since_de} (Destatis GV-ISys, Gebietsstand {GV_STAND}). Keine Schätzung und "
                          f"kein veröffentlichter Kreiswert, sondern die exakte Summe der Gemeindezahlen. 12411 {old} am "
                          f"{GV_POP_DATE} = {old_12411[0]:.0f} (alter Gebietsstand) = diese Summe + {s_new} ({new}). {why}."),
            "source_id": gv_sid}, keys=["entity_type", "entity_id", "metric", "year"])
        n += 1
        notes.append(f"split {new}/{old} {GV_POP_DATE}: {new} {s_new} + {old} in new boundaries {s_old} "
                     f"= 12411 {old} {old_12411[0]:.0f}")
    return n


def run(conn, cfg):
    cfg = cfg or {}
    notes: list[str] = []
    n_pop = ingest_population(conn, notes)
    n_gem = ingest_gemeinden(conn, notes, force=bool(cfg.get("force")))
    n_split = ingest_kreis_splits(conn, notes)
    return {"rows": n_pop + n_gem + n_split, "notes": " | ".join(notes)}


if __name__ == "__main__":
    raise SystemExit(common.no_direct_run(DOMAIN))
