"""geo_bkg: Bund, 16 Länder and 400 Kreise/kreisfreie Städte with polygons (Lead-owned domain).

Source: BKG Verwaltungsgebiete 1:2 500 000 (VG2500), Stand 01.01.2026, GeoPackage in ETRS89/UTM32,
dl-de/by-2-0. Archived under data/raw/geo_bkg/. Gives AGS, ARS, names, Bezeichnung, NUTS, polygons.
Centroids are computed here (area-weighted, from the polygons), not published by BKG.

Rows that another domain already created (e.g. counts_law's INSERT OR IGNORE of Land/Kreis keys)
keep their source_id and name; this module only fills geometry/lat/lon/ars/nuts/bez and records
geometry_source_id. Rows it creates itself carry the BKG source_id.

Stdlib only: a GeoPackage is SQLite, geometries are GP header + WKB, and the reprojection is the
standard inverse transverse Mercator series (Snyder 1987), sub-metre accurate across Germany.
"""
from __future__ import annotations

import io
import json
import math
import sqlite3
import struct
import tempfile
import zipfile
from pathlib import Path

from ingest import common

DOMAIN = "geo_bkg"
VG_URL = "https://daten.gdz.bkg.bund.de/produkte/vg/vg2500/aktuell/vg2500_01-01-2026.utm32s.gpkg.zip"
ABBR = {"01": "SH", "02": "HH", "03": "NI", "04": "HB", "05": "NW", "06": "HE", "07": "RP", "08": "BW",
        "09": "BY", "10": "SL", "11": "BE", "12": "BB", "13": "MV", "14": "SN", "15": "ST", "16": "TH"}  # ISO 3166-2:DE


def jdump(o):
    return json.dumps(o, separators=(",", ":"))


# ---------------------------------------------------------------- projection
_A, _F = 6378137.0, 1 / 298.257222101           # GRS80
_K0, _LON0, _FE = 0.9996, math.radians(9.0), 500000.0
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_E1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))


def utm32_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """ETRS89/UTM32N (EPSG:25832) -> (lat, lon) degrees. Snyder eqs 8-18..8-25."""
    m = y / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * _E2**2 / 64 - 5 * _E2**3 / 256))
    p1 = (mu + (3 * _E1 / 2 - 27 * _E1**3 / 32) * math.sin(2 * mu)
          + (21 * _E1**2 / 16 - 55 * _E1**4 / 32) * math.sin(4 * mu)
          + (151 * _E1**3 / 96) * math.sin(6 * mu) + (1097 * _E1**4 / 512) * math.sin(8 * mu))
    c1 = _EP2 * math.cos(p1) ** 2
    t1 = math.tan(p1) ** 2
    n1 = _A / math.sqrt(1 - _E2 * math.sin(p1) ** 2)
    r1 = _A * (1 - _E2) / (1 - _E2 * math.sin(p1) ** 2) ** 1.5
    d = (x - _FE) / (n1 * _K0)
    lat = p1 - (n1 * math.tan(p1) / r1) * (
        d**2 / 2 - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * _EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * _EP2 - 3 * c1**2) * d**6 / 720)
    lon = _LON0 + (d - (1 + 2 * t1 + c1) * d**3 / 6
                   + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * _EP2 + 24 * t1**2) * d**5 / 120) / math.cos(p1)
    return math.degrees(lat), math.degrees(lon)


# ---------------------------------------------------------------- GeoPackage WKB
def parse_gpkg_geom(blob: bytes) -> list[list[list[tuple[float, float]]]]:
    """GeoPackage binary -> list of polygons, each a list of rings of (x, y)."""
    assert blob[:2] == b"GP", "not a GeoPackage geometry"
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    buf = io.BytesIO(blob[8 + env:])

    def rd(fmt, bo):
        size = struct.calcsize(fmt)
        return struct.unpack(("<" if bo == 1 else ">") + fmt, buf.read(size))

    def geom():
        bo = buf.read(1)[0]
        (typ,) = rd("I", bo)
        base = typ % 1000
        if base == 3:
            (nr,) = rd("I", bo)
            rings = []
            for _ in range(nr):
                (npt,) = rd("I", bo)
                rings.append([rd("dd", bo) for _ in range(npt)])
            return [rings]
        if base == 6:
            (n,) = rd("I", bo)
            out = []
            for _ in range(n):
                out += geom()
            return out
        raise ValueError(f"unsupported WKB type {typ}")

    return geom()


def _dp(pts, tol):
    """Douglas-Peucker on projected metres."""
    if len(pts) < 5:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy) or 1e-9
        best, bi = -1.0, -1
        for k in range(i + 1, j):
            x0, y0 = pts[k]
            dist = abs(dy * x0 - dx * y0 + x2 * y1 - y2 * x1) / L
            if dist > best:
                best, bi = dist, k
        if best > tol:
            keep[bi] = True
            stack += [(i, bi), (bi, j)]
    out = [p for p, k in zip(pts, keep) if k]
    return out if len(out) >= 4 else pts


def _ring_area_centroid(r):
    a = cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    a /= 2
    return (a, cx / (6 * a), cy / (6 * a)) if a else (0.0, r[0][0], r[0][1])


def to_geojson(polys, tol_m: float):
    """Polygons in UTM -> (GeoJSON MultiPolygon in WGS84, area-weighted centroid lat/lon)."""
    A = SX = SY = 0.0
    out = []
    for rings in polys:
        new_rings = []
        for i, r in enumerate(rings):
            a, cx, cy = _ring_area_centroid(r)
            w = abs(a) if i == 0 else -abs(a)   # holes subtract
            A += w
            SX += w * cx
            SY += w * cy
            s = _dp(r, tol_m)
            new_rings.append([[round(lon, 4), round(lat, 4)] for lat, lon in (utm32_to_wgs84(x, y) for x, y in s)])
        out.append(new_rings)
    clat, clon = utm32_to_wgs84(SX / A, SY / A)
    return {"type": "MultiPolygon", "coordinates": out}, round(clat, 5), round(clon, 5)



def _merge(conn, table, key, ags, own: dict, geo: dict, sid):
    """Insert with our source_id, or fill only geometry fields on a row another domain created."""
    hit = conn.execute(f"SELECT source_id FROM {table} WHERE {key}=?", (ags,)).fetchone()
    if hit is None:
        common.upsert(conn, table, {key: ags, **own, **geo, "source_id": sid}, keys=[key])
        return "new"
    sets = ", ".join(f"{k}=?" for k in geo)
    extra = ", geometry_source_id=?" if hit[0] != sid else ""
    args = list(geo.values()) + ([sid] if extra else []) + [ags]
    conn.execute(f"UPDATE {table} SET {sets}{extra} WHERE {key}=?", args)
    return "geom"


def run(conn, cfg):
    cfg = cfg or {}
    sid = common.archive(
        conn, VG_URL, domain=DOMAIN, filename="vg2500_01-01-2026.utm32s.gpkg.zip", slug="bkg-vg2500-2026",
        title="Verwaltungsgebiete 1:2 500 000 (VG2500), Stand 01.01.2026, GeoPackage UTM32s",
        publisher="Bundesamt für Kartographie und Geodäsie (BKG)",
        license="Datenlizenz Deutschland – Namensnennung – Version 2.0 (dl-de/by-2-0)",
        license_url="https://www.govdata.de/dl-de/by-2-0",
        attribution="© GeoBasis-DE / BKG (2026) dl-de/by-2-0, Datenquellen: https://sgx.geodatenzentrum.de/web_public/gdz/datenquellen/datenquellen_vg_nuts.pdf",
        notes="Licence text: dokumentation/nutzungsbedingungen_vg2500.pdf inside the archive.",
        force=bool(cfg.get("force")))
    zpath = common._cow(common.RAW / DOMAIN / "vg2500_01-01-2026.utm32s.gpkg.zip")
    with tempfile.TemporaryDirectory() as td, zipfile.ZipFile(zpath) as z:
        name = next(n for n in z.namelist() if n.endswith(".gpkg"))
        z.extract(name, td)
        g = sqlite3.connect(f"file:{Path(td) / name}?mode=ro", uri=True)
        lan = g.execute("SELECT AGS, GEN, BEZ, ARS, NUTS, geom FROM vg2500_lan WHERE GF=9 ORDER BY AGS").fetchall()
        krs = g.execute("SELECT AGS, GEN, BEZ, ARS, NUTS, geom FROM vg2500_krs WHERE GF=9 ORDER BY AGS").fetchall()
        sta = g.execute("SELECT geom FROM vg2500_sta WHERE GF=9").fetchall()
        g.close()
    geo, clat, clon = to_geojson([p for (b,) in sta for p in parse_gpkg_geom(b)], 2500)
    common.upsert(conn, "geo_country", {"code": "DE", "name": "Deutschland", "lat": clat, "lon": clon,
                                        "geometry": jdump(geo), "source_id": sid}, keys=["code"])
    tally = {"new": 0, "geom": 0}
    for ags, gen, bez, ars, nuts, blob in lan:
        geo, clat, clon = to_geojson(parse_gpkg_geom(blob), 1500)
        tally[_merge(conn, "geo_land", "ags", ags, {"name": gen, "abbr": ABBR[ags]},
                     {"bez": bez, "ars": ars, "nuts": nuts, "lat": clat, "lon": clon, "geometry": jdump(geo)}, sid)] += 1
    for ags, gen, bez, ars, nuts, blob in krs:
        geo, clat, clon = to_geojson(parse_gpkg_geom(blob), 600)
        kind = "kreisfreie_stadt" if "reisfreie Stadt" in (bez or "") or bez == "Stadtkreis" else (
            "landkreis" if bez in ("Landkreis", "Kreis") else common.slug(bez or "kreis").replace("-", "_"))
        tally[_merge(conn, "geo_kreis", "ags", ags,
                     {"name": gen, "land_ags": ags[:2], "land": ABBR[ags[:2]], "kind": kind},
                     {"bez": bez, "ars": ars, "nuts": nuts, "lat": clat, "lon": clon, "geometry": jdump(geo)}, sid)] += 1
    if len(lan) != 16 or len(krs) < 390:
        raise RuntimeError(f"unexpected VG2500 counts: {len(lan)} Länder, {len(krs)} Kreise")
    note = f"DE + {len(lan)} Länder + {len(krs)} Kreise; {tally['new']} rows created, {tally['geom']} existing rows given geometry"
    return {"rows": 1 + len(lan) + len(krs), "notes": note, "sources": [(VG_URL, "dl-de/by-2-0")]}


if __name__ == "__main__":
    from ingest.common import no_direct_run
    raise SystemExit(no_direct_run("geo_bkg"))
