"""Check the irrigation patches against the PNOA aerial orthophoto (IGN, 25 cm).

Sentinel-2 sees 10 m pixels; PNOA sees the tunnels themselves. Each patch of a campaign
is shown on the PNOA flight closest in time, with its outline, and labelled by eye into
one of `LABELS`. The labels live in a versioned CSV, one row per patch, so the check can
be repeated, disputed and corrected like any other data in the repository. The share of
patches that turn out to be greenhouses or tunnels is the precision that the report
quotes next to the hectares.

PNOA is flown in summer and every two or three years per region, so it is a check of
what the land is, not of whether it was covered that winter: a tunnel structure without
its plastic in June counts as a greenhouse. A patch that is bare in the photo may also
be a plot converted after the flight; those are labelled `no_agricola` all the same and
the report says so.
"""
from __future__ import annotations

import csv
import io
import re
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from shapely.geometry import shape

from . import config, legal

# Label → (text in Spanish for the report, counts as a hit).
LABELS = {
    "invernadero": ("macrotúnel o invernadero, cubierto o solo la estructura", True),
    "cultivo": ("cultivo sin túnel visible (frutal, arable)", False),
    "no_agricola": ("pinar, matorral, arena, balsa o edificación", False),
    "dudoso": ("no se distingue a esta escala", None),
}


# Flight month of each PNOA layer over the Condado de Huelva (from `flight_date`), for the page.
FLIGHTS = {"PNOA2022": "junio de 2022", "PNOA2019": "junio de 2019"}


def labels_path(slug: str, year: int, flight: str) -> Path:
    return config.IRRIGATION_DIR / "validation" / f"{slug}_{year}_{flight}.csv"


def chip_bbox(geom, min_side_m: float = config.VALIDATION_CHIP_M) -> tuple[float, float, float, float]:
    """Square box around a patch (in IRRIGATION_CRS), at least `min_side_m` wide."""
    x0, y0, x1, y1 = geom.bounds
    side = max(x1 - x0, y1 - y0) * 1.4
    side = max(side, min_side_m)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2


def pnoa_url(layer: str, bbox, px: int) -> str:
    """WMS GetMap of one historical PNOA flight. The page embeds this URL as is: the image
    is never copied, it comes from IGN every time. PNG, not JPEG: the historical service
    answers 500 to JPEG requests that accept gzip, which every browser does."""
    return config.PNOA_WMS + "?" + urlencode({
        "service": "WMS", "version": "1.3.0", "request": "GetMap", "layers": layer, "styles": "",
        "crs": config.IRRIGATION_CRS, "bbox": ",".join(f"{v:.0f}" for v in bbox),
        "width": px, "height": px, "format": "image/png"})


def outline_svg_path(geom, bbox, px: int) -> str:
    """SVG path of a patch outline in the pixel frame of its chip (y grows downwards)."""
    x0, y0, x1, y1 = bbox
    sx, sy = px / (x1 - x0), px / (y1 - y0)
    parts = []
    for poly in getattr(geom, "geoms", [geom]):
        for ring in [poly.exterior, *poly.interiors]:
            pts = [f"{(x - x0) * sx:.1f},{(y1 - y) * sy:.1f}" for x, y in ring.coords]
            parts.append("M" + " L".join(pts) + " Z")
    return " ".join(parts)


def patch_geoms(fc: dict) -> dict[str, object]:
    """Patch id → geometry in IRRIGATION_CRS (the GeoJSON is in EPSG:4326)."""
    return {f["properties"]["id"]: legal.reproject(shape(f["geometry"]), 4326, config.IRRIGATION_CRS)
            for f in fc["features"]}


def read_labels(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8", newline="") as fh:
        rows = {r["patch_id"]: r for r in csv.DictReader(fh)}
    bad = {r["label"] for r in rows.values()} - LABELS.keys()
    if bad:
        raise ValueError(f"{path.name}: etiquetas desconocidas {sorted(bad)}")
    return rows


def write_labels(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["patch_id", "ha", "label", "note"], lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def precision(fc: dict, labels: dict[str, dict]) -> dict:
    """Share of labelled patches, and of their hectares, that are greenhouses or tunnels
    (strict precision) and that are farmland at all (tunnels or crops: the share that is
    not a false positive of the plastic rule). `dudoso` is left out of every ratio."""
    ha = {f["properties"]["id"]: f["properties"]["ha"] for f in fc["features"]}
    counts = {k: 0 for k in LABELS}
    area = {k: 0.0 for k in LABELS}
    for pid, r in labels.items():
        if pid in ha:
            counts[r["label"]] += 1
            area[r["label"]] += ha[pid]
    decided = [k for k, (_, hit) in LABELS.items() if hit is not None]
    n = sum(counts[k] for k in decided)
    a = sum(area[k] for k in decided)
    farm = ("invernadero", "cultivo")
    return {"patches": len(ha), "labelled": sum(counts.values()), "counts": counts,
            "ha": {k: round(v, 1) for k, v in area.items()},
            "precision_patches": counts["invernadero"] / n if n else None,
            "precision_ha": area["invernadero"] / a if a else None,
            "farmland_patches": sum(counts[k] for k in farm) / n if n else None,
            "farmland_ha": sum(area[k] for k in farm) / a if a else None}


def _get_chip(url: str, tries: int = 4) -> bytes:
    """IGN's WMS answers an occasional 500 that succeeds on the next try."""
    for k in range(tries):
        r = requests.get(url, timeout=60)
        if r.ok:
            return r.content
        time.sleep(2 * (k + 1))
    r.raise_for_status()


def contact_sheets(fc: dict, layer: str, out_dir: Path, per_sheet: int = 8, px: int = 700) -> list[Path]:
    """PNG sheets of numbered chips with the outline in red, for labelling by eye. Working
    files: they go to the cache, never to the repository or the page."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.image import imread

    geoms = patch_geoms(fc)
    feats = fc["features"]
    out_dir.mkdir(parents=True, exist_ok=True)
    sheets = []
    for s0 in range(0, len(feats), per_sheet):
        chunk = feats[s0:s0 + per_sheet]
        cols = 4
        rows = -(-len(chunk) // cols)
        fig, axes = plt.subplots(rows, cols, figsize=(cols * 5, rows * 5.3), squeeze=False)
        for ax in axes.ravel():
            ax.axis("off")
        for k, f in enumerate(chunk):
            p = f["properties"]
            g = geoms[p["id"]]
            bbox = chip_bbox(g)
            img = imread(io.BytesIO(_get_chip(pnoa_url(layer, bbox, px))), format="png")
            ax = axes.ravel()[k]
            ax.imshow(img, extent=(bbox[0], bbox[2], bbox[1], bbox[3]))
            for poly in getattr(g, "geoms", [g]):
                xs, ys = poly.exterior.xy
                ax.plot(xs, ys, color="red", lw=1.2)
            ax.set_title(f"#{s0 + k + 1}  {p['ha']} ha  {p['admin_zone']}  SIGPAC {p['sigpac_use'] or '–'}",
                         fontsize=9)
        fig.tight_layout()
        path = out_dir / f"sheet_{s0 // per_sheet + 1:02d}.png"
        fig.savefig(path, dpi=95)
        plt.close(fig)
        sheets.append(path)
    return sheets


def flight_date(lon: float, lat: float) -> str | None:
    """Year-month of the current PNOA orthophoto at a point, from IGN's own metadata."""
    t = legal._transformer(4326, config.IRRIGATION_CRS)
    x, y = t.transform(lon, lat)
    r = requests.get(config.PNOA_CURRENT_WMS, timeout=60, params={
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": "OI.MosaicElement", "query_layers": "OI.MosaicElement",
        "crs": config.IRRIGATION_CRS, "bbox": f"{x - 50},{y - 50},{x + 50},{y + 50}",
        "width": 101, "height": 101, "i": 50, "j": 50, "info_format": "text/html"})
    m = re.search(r"\d{4}-\d{2}", re.sub(r"<[^>]+>", " ", r.text))
    return m.group(0) if m else None

