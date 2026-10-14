"""The water of the Spanish wetlands as signals for Estado de las IBA (signals.json).

Estado de las IBA (estado-iba) gathers what the sibling projects publish per Natura 2000
site, municipality and region, and reads each one's `signals.json` in the common format of
its CONTRATO.md. Until this file existed the hub computed these signals itself from
`data/series` and `data/sites`; the figures here are the same ones, so its panel does not
change when it switches to reading them from here.

One signal per wetland: its latest good observation of open water against the median of the
same calendar month in earlier years. It is not the alert rule (±30 days, 10th percentile):
the alerts decide whether something is wrong, the hub wants one figure per wetland that reads
"x % of the usual water in that month".
"""
from __future__ import annotations

import csv
import json
import statistics
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from shapely.geometry import shape
from shapely.ops import unary_union
from shapely.validation import make_valid

from . import config
from .sites import SITES, Site

# Every Spanish Natura 2000 site, simplified to ~300 m, as Vigía de incendios publishes it
# (properties `codigo`, `nombre`, `tipo`). Fetched on each run: it is the same layer the hub
# keeps its sites from, so the codes always match.
NATURA_LAYER_URL = "https://asensio94.github.io/vigia-incendios/natura.geojson"
PAGE_URL = "https://asensio94.github.io/vigilancia-humedales/"

QUALITY = {"ok"}     # cloudy, partial or anomalous scenes do not set the state
MIN_YEARS = 3        # the same-month reference needs at least this many earlier years
MAX_AGE_DAYS = 45    # an older observation is still sent, but not as the current state
DRY_SHARE = 0.05     # a reference under this share of the series maximum = usually dry
MIN_OVERLAP = 0.25   # share of the wetland's area that must lie inside a site

COVERAGE = {"label": "Seis humedales",
            "note": "Agua libre con Sentinel-2 desde 2017, frente a la mediana del mismo mes en años anteriores."}


def state(rows: list[dict], today: date) -> dict | None:
    """Latest good observation of open water against the same month in earlier years.

    The reference is the median, over the earlier years with good observations in that
    calendar month, of each year's median; with fewer than MIN_YEARS of them there is no
    ratio. Seasonal lagoons that are usually dry in that month (reference under DRY_SHARE of
    the series maximum) get no ratio either: dividing by almost nothing would turn a normal
    wet year into thousands of percent. Rows are the series CSV as read by csv.DictReader.
    """
    good = [r for r in rows if r["quality"] in QUALITY and r.get("water_ha") not in (None, "")]
    if not good:
        return None
    last = max(good, key=lambda r: r["date"])
    d = date.fromisoformat(last["date"])
    ref: dict[int, list[float]] = {}
    for r in good:
        rd = date.fromisoformat(r["date"])
        if rd.month == d.month and rd.year < d.year:
            ref.setdefault(rd.year, []).append(float(r["water_ha"]))
    median = statistics.median(statistics.median(v) for v in ref.values()) if len(ref) >= MIN_YEARS else None
    water = float(last["water_ha"])
    dry = median is not None and median < DRY_SHARE * max(float(r["water_ha"]) for r in good)
    return {
        "date": last["date"], "water_ha": round(water, 1), "ref_ha": None if median is None else round(median, 1),
        "ratio": round(water / median, 2) if median and not dry else None, "dry_ref": dry, "ref_years": sorted(ref),
        "current": (today - d).days <= MAX_AGE_DAYS,
    }


def title(name: str, st: dict) -> str:
    if st["dry_ref"]:
        return f"{name}: {st['water_ha']:.0f} ha de agua; en ese mes suele estar seca"
    if st["ratio"] is not None:
        return f"{name}: {st['ratio'] * 100:.0f} % del agua normal en ese mes"
    return f"{name}: {st['water_ha']:.0f} ha de agua"


def polygonal(geometry: dict):
    """A valid areal shape from a GeoJSON geometry.

    Simplified to ~300 m, some rings of the Natura layer cross themselves and some small parts
    collapse into lines or single points. Each part is repaired on its own and only areas are
    kept: GEOS 3.14 refuses to repair a MultiPolygon with a part collapsed into a point.
    """
    g = shape(geometry)
    fixed = [make_valid(p) for p in getattr(g, "geoms", [g])]
    return unary_union([q for p in fixed for q in getattr(p, "geoms", [p]) if q.geom_type in ("Polygon", "MultiPolygon")])


def natura_shapes(natura: dict) -> dict[str, object]:
    """SITECODE → repaired shape, for every site of the layer (ZEPA, ZEC or both)."""
    return {f["properties"]["codigo"]: polygonal(f["geometry"]) for f in natura["features"]}


def sites_of(geom, shapes: dict[str, object]) -> set[str]:
    """Natura 2000 sites that hold at least MIN_OVERLAP of the wetland's area.

    The wetland's own code is not enough: it may be the ZEC drawn around the water while the
    ZEPA that covers the same water has another code (Gallocanta is measured on ZEC ES2430043,
    its ZEPA is ES0000017). A site that only grazes the edge does not count.
    """
    return {code for code, g in shapes.items()
            if g.intersects(geom) and g.intersection(geom).area >= MIN_OVERLAP * geom.area}


def _rows(slug: str) -> list[dict]:
    path = config.SERIES_DIR / f"{slug}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _signal(site: Site, st: dict, codes: set[str], point: list[float]) -> dict:
    return {
        "id": site.slug, "kind": "wetland_water", "date": st["date"], "title": title(site.name, st),
        "url": PAGE_URL, "sites": [{"code": c} for c in sorted(codes)], "municipalities": [],
        "precision": "lamina", "deadline": None, "status": "vigente" if st["current"] else "antiguo",
        "value": {"amount": st["water_ha"], "unit": "ha"},
        "details": {**{k: st[k] for k in ("ratio", "ref_ha", "ref_years", "dry_ref", "current")},
                    "name": site.name, "point": point},
    }


def build(natura: dict, today: date, now: datetime | None = None) -> dict:
    """The signals.json document for the Spanish wetlands, from the series and contours on disk.

    A wetland with no good observation gives no signal, but its sites still count as watched:
    the hub tells "watched, nothing to report" from "not covered" by coverage.sites.
    """
    now = now or datetime.now(timezone.utc)
    shapes = natura_shapes(natura)
    watched: set[str] = set()
    signals = []
    for site in (s for s in SITES.values() if s.country == "ES"):
        with (config.SITES_DIR / f"{site.slug}.geojson").open(encoding="utf-8") as fh:
            geom = polygonal(json.load(fh)["geometry"])
        codes = sites_of(geom, shapes)
        watched |= codes
        st = state(_rows(site.slug), today)
        if st:
            c = geom.representative_point()
            signals.append(_signal(site, st, codes, [round(c.x, 4), round(c.y, 4)]))
    signals.sort(key=lambda s: (s["date"], s["id"]))
    return {"source": "vigilancia-humedales", "version": 1, "generated": now.strftime("%Y-%m-%dT%H:%MZ"),
            "coverage": {"label": COVERAGE["label"], "sites": sorted(watched), "note": COVERAGE["note"]},
            "signals": signals}


def write(run_date: date) -> Path:
    """Download the Natura layer, build the document and write output/signals_<date>.json.

    Raises if the layer cannot be fetched; the caller decides that this must not stop the run.
    """
    r = requests.get(NATURA_LAYER_URL, timeout=120)
    r.raise_for_status()
    doc = build(r.json(), run_date)
    path = config.OUTPUT_DIR / f"signals_{run_date.isoformat()}.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return path
