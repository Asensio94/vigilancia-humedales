"""Legal reference layers for the irrigation check: where irrigation is allowed.

Two sources, both open and without keys:

- The zoning of the Plan Especial de Ordenación de las zonas de regadío al norte de la
  Corona Forestal de Doñana (PEORCFD, Decreto 178/2014), published by REDIAM as WFS.
  Its `SAR_1025` attribute marks the *suelos agrícolas regables*: the only land where
  the plan allows irrigation. Everything else inside the plan area is forest (zone A)
  or farmland that may not be irrigated (zones B and C, "no regable").
- SIGPAC parcels (recintos) from FEGA, per municipality and campaign. They carry the
  declared land use (`uso_sigpac`, e.g. IV = greenhouse / under plastic) and the
  irrigation coefficient (`coef_regadio`, 0-100), which is what the CAP payments
  recognise as irrigated. FEGA keeps online only the current and previous campaigns.

The zoning is versioned in the repository (see README, "Los contornos van versionados"):
a change in the official cartography must show up as a commit, not as a silent jump in
the hectares outside it. SIGPAC is downloaded into the cache and only the attributes of
the parcels touched by a detection are kept, in the output.
"""
from __future__ import annotations

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
import requests
from pyproj import Transformer
from shapely import from_wkb, set_precision
from shapely import transform as shp_transform
from shapely.geometry import MultiPolygon, Polygon, mapping, shape

from . import config

GML = "http://www.opengis.net/gml"
MS = "http://mapserver.gis.umn.edu/mapserver"


@lru_cache(maxsize=8)
def _transformer(src, dst) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


def reproject(geom, src, dst):
    """Shapely geometry from one CRS to another, vectorised over the coordinates."""
    t = _transformer(src, dst)
    return shp_transform(geom, lambda xy: np.column_stack(t.transform(xy[:, 0], xy[:, 1])))


# --- PEORCFD zoning (Doñana) -----------------------------------------------------------

@dataclass(frozen=True)
class Zone:
    geom: object           # shapely, in config.IRRIGATION_CRS
    irrigable: bool        # SAR = SI
    urban: bool            # suelo urbano o urbanizable: outside the scope of the check
    admin_zone: str        # "Zona A" | "Zona B" | "Zona C"
    label: str             # INFORMACIO, the plan's own wording


def _ring(e) -> list[tuple[float, float]]:
    txt = e.find(f".//{{{GML}}}coordinates").text
    return [tuple(map(float, p.split(",")[:2])) for p in txt.split()]


def parse_peorcfd_gml(text: str | bytes) -> list[Zone]:
    """Zones from the REDIAM WFS 1.0.0 GetFeature response (GML 2, x,y order).

    The server answers in EPSG:3042 (ETRS89 / UTM 30N with northing-first axes in the
    EPSG definition) but WFS 1.0.0 always writes easting first, so the numbers are the
    same as EPSG:25830.
    """
    root = ET.fromstring(text)
    out = []
    for member in root.iter(f"{{{GML}}}featureMember"):
        f = next(iter(member))
        attr = {c.tag.split("}")[1]: (c.text or "").strip() for c in f if c.tag.startswith(f"{{{MS}}}")}
        polys = [Polygon(_ring(p.find(f"{{{GML}}}outerBoundaryIs")),
                         [_ring(i) for i in p.findall(f"{{{GML}}}innerBoundaryIs")])
                 for p in f.iter(f"{{{GML}}}Polygon")]
        label = attr.get("INFORMACIO", "")
        out.append(Zone(MultiPolygon(polys).buffer(0), attr.get("SAR_1025") == "SI",
                        "Urbano" in label, attr.get("ZonADM1025", ""), label))
    return out


def _zones_to_geojson(zones: list[Zone]) -> dict:
    feats = []
    for z in zones:
        g = set_precision(z.geom.simplify(config.ZONING_SIMPLIFY_M), 1.0)
        feats.append({"type": "Feature", "geometry": mapping(g),
                      "properties": {"irrigable": z.irrigable, "urban": z.urban,
                                     "admin_zone": z.admin_zone, "label": z.label}})
    return {"type": "FeatureCollection", "crs_epsg": 25830, "source": config.PEORCFD_WFS,
            "features": feats}


def peorcfd_zoning(refresh: bool = False) -> list[Zone]:
    """PEORCFD zoning, from the versioned copy unless `refresh`."""
    path = config.LEGAL_DIR / "donana_peorcfd.geojson"
    if refresh or not path.exists():
        r = requests.get(config.PEORCFD_WFS, timeout=300, params={
            "service": "WFS", "version": "1.0.0", "request": "GetFeature",
            "typeName": "ms:Zona_B_C_regable"})
        r.raise_for_status()
        zones = parse_peorcfd_gml(r.content)
        path.write_text(json.dumps(_zones_to_geojson(zones), ensure_ascii=False), encoding="utf-8")
    fc = json.loads(path.read_text(encoding="utf-8"))
    return [Zone(shape(f["geometry"]), **f["properties"]) for f in fc["features"]]


# --- SIGPAC (FEGA) ---------------------------------------------------------------------

@dataclass(frozen=True)
class Parcel:
    geom: object           # shapely, in config.IRRIGATION_CRS
    ref: str               # provincia:municipio:agregado:zona:poligono:parcela:recinto
    use: str               # uso_sigpac
    irrigation_coef: int   # coef_regadio, 0 when null


_ENVELOPE_BYTES = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}


def gpkg_to_shapely(blob: bytes):
    """GeoPackage geometry blob → shapely. Header: 'GP', version, flags, srs_id, envelope."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry")
    envelope = _ENVELOPE_BYTES[(blob[3] >> 1) & 0b111]
    return from_wkb(bytes(blob[8 + envelope:]))


def sigpac_zip_url(listing_html: str, municipality: str, campaign: int) -> str | None:
    """Name of the municipality's GeoPackage zip in a FEGA ATOM directory listing.

    The file name ends in the publication date (`21005_rec_2026_20251215_gpkg.zip`), which
    changes with every republication, so it is read from the listing, never assumed.
    """
    names = re.findall(rf'href="({municipality}_rec_{campaign}_\d{{8}}_gpkg\.zip)"', listing_html)
    return sorted(names)[-1] if names else None


def _download_sigpac(province: str, municipality: str, campaign: int) -> Path | None:
    cache = config.CACHE_DIR / "sigpac" / str(campaign)
    cache.mkdir(parents=True, exist_ok=True)
    found = list(cache.glob(f"{municipality}_rec_{campaign}_*.gpkg"))
    if found:
        return found[0]
    base = f"{config.SIGPAC_ATOM}/{campaign}/rec_{campaign}/{requests.utils.quote(province)}/"
    r = requests.get(base, timeout=60)
    if r.status_code != 200:
        return None
    name = sigpac_zip_url(r.text, municipality, campaign)
    if not name:
        return None
    z = cache / name
    with requests.get(base + name, timeout=300, stream=True) as resp:
        resp.raise_for_status()
        with open(z, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
    with zipfile.ZipFile(z) as zf:
        gpkg = next(n for n in zf.namelist() if n.endswith(".gpkg"))
        zf.extract(gpkg, cache)
    z.unlink()
    return cache / gpkg


def available_campaign(province: str, wanted: int) -> int | None:
    """The SIGPAC campaign closest to `wanted` that FEGA still serves."""
    for c in sorted(range(wanted - 2, wanted + 3), key=lambda c: (abs(c - wanted), -c)):
        if requests.get(f"{config.SIGPAC_ATOM}/{c}/rec_{c}/{requests.utils.quote(province)}/",
                        timeout=60).status_code == 200:
            return c
    return None


def read_sigpac(path: Path) -> list[Parcel]:
    con = sqlite3.connect(path)
    con.text_factory = lambda b: b.decode("latin-1")
    rows = con.execute("select dn_geom, provincia, municipio, agregado, zona, poligono, parcela, "
                       "recinto, uso_sigpac, coef_regadio from recinto").fetchall()
    con.close()
    out = []
    for blob, *ref, use, coef in rows:
        g = reproject(gpkg_to_shapely(blob), 4258, config.IRRIGATION_CRS)
        out.append(Parcel(g, ":".join(str(v) for v in ref), use or "", int(coef or 0)))
    return out


def sigpac_parcels(province: str, municipalities: tuple[str, ...], campaign: int) -> list[Parcel]:
    parcels: list[Parcel] = []
    for m in municipalities:
        p = _download_sigpac(province, m, campaign)
        if p is None:
            raise RuntimeError(f"SIGPAC {campaign}: no hay fichero para el municipio {m}")
        parcels += read_sigpac(p)
    return parcels


def sigpac_info_url(ref: str) -> str:
    """Public SIGPAC query for one parcel: use, slope, irrigation coefficient. No owner data."""
    return f"{config.SIGPAC_QUERY}/recinfo/{ref.replace(':', '/')}.json"
