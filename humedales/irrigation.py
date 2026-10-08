"""Irrigation seen from space outside the land where the law allows it.

The aquifer that feeds a wetland is drained by the wells of the farms around it, and the
plans that protect it say where those farms may irrigate. This module compares the two:
crops that only exist with irrigation, detected on Sentinel-2, against the official map
of irrigable land.

Doñana is the first site. Its irrigation signature is not green: the berry farms of the
Condado cover their fields with plastic macro-tunnels from autumn to spring and leave
them bare in summer, when the only green left is the pine forest. So the detector here
looks for plastic in January-March, not for vegetation in July (a summer NDVI detector
finds the forest and misses the farms). Each campaign is processed once:

1. Every Sentinel-2 date of the window is read at 10 m over the plan area. A pixel is
   valid if SCL calls it vegetation, soil, water or unclassified and its blue is below
   the cloud cut; it is plastic if RPGI, PMLI and blue/red all agree (see config).
2. Plastic is kept where it was seen on at least `PLASTIC_MIN_DATES` valid dates.
3. Persistent plastic is crossed with the zoning: inside the irrigable land (SAR) it is
   the expected use; in zones A, B or C outside it, more than `LEGAL_EDGE_M` away from
   the SAR boundary and on a SIGPAC parcel whose use can be farming, it is reported.
4. Reported pixels are grouped into patches of at least `PATCH_MIN_HA` and each patch
   gets the facts needed to check it: hectares, dates with plastic, plan zone, SIGPAC
   parcel and what that parcel declares (use, irrigation coefficient).

A patch is an indication to verify, not a finding of illegality. Art. 26.6 of the plan
lets a farm that meets the requirements prevail over the cartography, the cartography
itself has been revised (SAR 2014, 2018, 2021), and a plastic cover is not proof that
water from the aquifer is used. What the patch does say is that, on the official map,
irrigated farming should not be there.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Callable

import numpy as np
from odc.geo.geobox import GeoBox
from odc.stac import load
from pyproj import Transformer
from rasterio import features
from rasterio.transform import Affine, from_origin
from shapely import STRtree, set_precision
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

from . import config, legal, stac

# Zone codes of the legal raster.
OUT_OF_PLAN, IRRIGABLE, NOT_IRRIGABLE, URBAN = 0, 1, 2, 3


@dataclass(frozen=True)
class IrrigationSite:
    slug: str
    name: str
    wetland: str                    # slug in sites.SITES: the wetland this aquifer feeds
    months: tuple[int, ...]         # detection window within the campaign year
    province: str                   # FEGA ATOM folder
    municipalities: tuple[str, ...] # SIGPAC (Catastro) municipality codes
    zoning: str                     # which legal layer: "peorcfd"
    note: str = ""


IRRIGATION_SITES: dict[str, IrrigationSite] = {
    s.slug: s for s in [
        IrrigationSite(
            "donana", "Doñana · Corona Forestal (Condado de Huelva)", "donana",
            # The plastic peaks in January-February and starts to come off in late March:
            # on 2025 the plastic area fell from 4,744 ha (4 Feb) to 856 ha (31 Mar).
            months=(1, 2, 3),
            province="21 - HUELVA",
            # Every Huelva municipality with SIGPAC parcels inside the plan area. SIGPAC
            # numbers municipalities with the Catastro code, not the INE one.
            municipalities=("21005", "21013", "21014", "21038", "21046", "21050",
                            "21053", "21054", "21055", "21061", "21062"),
            zoning="peorcfd",
            note="Plan Especial de la Corona Forestal de Doñana (Decreto 178/2014)."),
    ]
}


# --- per-observation rules --------------------------------------------------------------

def plastic_rules(blue, green, red, nir, swir16, scl) -> tuple[np.ndarray, np.ndarray]:
    """(valid, plastic) for one date. Reflectances 0-1, NaN where there is no data."""
    with np.errstate(invalid="ignore", divide="ignore"):
        valid = (np.isin(scl, list(config.IRRIGATION_SCL_VALID)) & np.isfinite(blue)
                 & (blue < config.PLASTIC_BLUE_MAX))
        mean3 = (blue + green + nir) / 3
        rpgi = 100 * blue / (1 - mean3)
        pmli = (swir16 - red) / (swir16 + red)
        plastic = (valid & (rpgi >= config.PLASTIC_RPGI_MIN) & (pmli <= config.PLASTIC_PMLI_MAX)
                   & (blue / red >= config.PLASTIC_BLUE_RED_MIN))
    return valid, plastic


def dilate(mask: np.ndarray, n: int) -> np.ndarray:
    """Binary dilation by n pixels, 8-connected, without scipy."""
    m = mask.astype(bool)
    for _ in range(n):
        p = np.pad(m, 1)
        h, w = m.shape
        m = np.logical_or.reduce([p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]
                                  for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
    return m


def outside_mask(plastic_dates: np.ndarray, zone: np.ndarray, farming: np.ndarray,
                 res_m: float = config.IRRIGATION_RES_M) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Persistent plastic outside the irrigable land, after the edge, use and size filters.

    Also returns each intermediate stage, so the report can say how much every filter took.
    """
    persistent = plastic_dates >= config.PLASTIC_MIN_DATES
    near_legal = dilate(zone == IRRIGABLE, int(round(config.LEGAL_EDGE_M / res_m)))
    stages = {"not_irrigable": persistent & (zone == NOT_IRRIGABLE)}
    stages["away_from_edge"] = stages["not_irrigable"] & ~near_legal
    stages["farming_use"] = stages["away_from_edge"] & farming
    m = stages["farming_use"]
    min_px = int(round(config.PATCH_MIN_HA * 10_000 / res_m**2))
    kept = features.sieve(m.astype(np.uint8), size=min_px, connectivity=8).astype(bool) & m
    return kept, stages


# --- rasters ---------------------------------------------------------------------------

def plan_grid(zones: list[legal.Zone], res_m: float = config.IRRIGATION_RES_M):
    x0, y0, x1, y1 = unary_union([z.geom for z in zones]).bounds
    x0, y1 = np.floor(x0 / res_m) * res_m, np.ceil(y1 / res_m) * res_m
    w, h = int(np.ceil((x1 - x0) / res_m)), int(np.ceil((y1 - y0) / res_m))
    return (h, w), from_origin(x0, y1, res_m, res_m)


def zone_rasters(zones: list[legal.Zone], shape_hw, transform: Affine):
    """Zone code per pixel and index (1-based) of the zone feature it falls in."""
    idx = features.rasterize([(z.geom, i + 1) for i, z in enumerate(zones)], shape_hw,
                             transform=transform, fill=0, dtype="int32")
    codes = np.array([OUT_OF_PLAN] + [URBAN if z.urban else IRRIGABLE if z.irrigable else NOT_IRRIGABLE
                                      for z in zones], dtype=np.uint8)
    return codes[idx], idx


def parcel_raster(parcels: list[legal.Parcel], shape_hw, transform: Affine) -> np.ndarray:
    return features.rasterize(((p.geom, i + 1) for i, p in enumerate(parcels)), shape_hw,
                              transform=transform, fill=0, dtype="int32")


# --- Sentinel-2 composite --------------------------------------------------------------

def offset_already_applied(blue_dn: np.ndarray) -> bool:
    """Whether the -1000 DN offset of baseline >= 04.00 is already out of the numbers.

    Earth Search flags it with `earthsearch:boa_offset_applied`, but in 2025 half of the
    Doñana scenes say False and still come without the offset: on a fixed patch of
    farmland the median blue is 208-336 DN on both kinds of scene, where an offset still
    inside would put it near 1,300. Trusting the flag subtracts 0.1 twice and drives the
    blue to zero, which hides every plastic tunnel. The data settle it instead: with the
    offset inside, nothing on land is below 1,000 DN in blue, and without it the darkest
    percentile of a scene is a few hundred at most.
    """
    v = blue_dn[blue_dn > 0]
    return v.size == 0 or float(np.percentile(v, 1)) < 1000


def reflectance(ds, items, band: str, applied: bool) -> np.ndarray:
    scale, declared = stac.band_scale_offset(items[0], band)
    dn = ds[band].values.astype("float32")
    refl = dn * scale + (0.0 if applied else declared)
    refl[dn == 0] = np.nan
    return refl


def composite(site: IrrigationSite, year: int, geobox: GeoBox, in_plan: np.ndarray,
              log: Callable = print) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Per pixel: number of valid dates and of dates with plastic in the window."""
    to_ll = Transformer.from_crs(config.IRRIGATION_CRS, 4326, always_xy=True)
    b = geobox.boundingbox
    lon0, lat0 = to_ll.transform(b.left, b.bottom)
    lon1, lat1 = to_ll.transform(b.right, b.top)
    start, end = date(year, min(site.months), 1), date(year, max(site.months) % 12 + 1, 1)
    items = stac.search((lon0, lat0, lon1, lat1), start, end)
    days = {d: its for d, its in stac.group_by_day(items).items()
            if d.month in site.months and d < end}
    valid_n = np.zeros(geobox.shape, np.uint8)
    plastic_n = np.zeros(geobox.shape, np.uint8)
    used = []
    for d, its in days.items():
        ds = load(its, bands=config.IRRIGATION_BANDS, geobox=geobox, groupby="solar_day",
                  resampling={"scl": "nearest", "*": "average"},
                  chunks={"x": 2048, "y": 2048}).isel(time=0)
        ds = ds.compute(scheduler="threads", num_workers=config.DASK_THREADS)
        applied = offset_already_applied(ds.blue.values)
        refl = {k: reflectance(ds, its, k, applied) for k in config.IRRIGATION_BANDS if k != "scl"}
        valid, plastic = plastic_rules(**refl, scl=ds.scl.values)
        coverage = float(valid[in_plan].mean())
        if coverage < config.DAY_MIN_COVERAGE:
            log(f"  {d}  descartada: {100 * coverage:.0f} % del ámbito visible")
            continue
        valid_n += valid
        plastic_n += plastic
        ha = float(plastic[in_plan].sum()) * config.IRRIGATION_RES_M**2 / 10_000
        used.append({"date": d.isoformat(), "coverage": round(coverage, 3), "plastic_ha": round(ha),
                     "scenes": sorted(it.id for it in its)})
        log(f"  {d}  visible {100 * coverage:3.0f} %  plástico {ha:7.0f} ha")
    return valid_n, plastic_n, used


# --- patches ---------------------------------------------------------------------------

def _majority(labels: np.ndarray, values: np.ndarray, n: int) -> np.ndarray:
    """For each label 1..n, the most frequent non-zero value. 0 if none."""
    out = np.zeros(n + 1, dtype=values.dtype)
    sel = (labels > 0) & (values > 0)
    if not sel.any():
        return out
    pairs, counts = np.unique(np.stack([labels[sel], values[sel]]), axis=1, return_counts=True)
    order = np.lexsort((-counts, pairs[0]))
    first = np.unique(pairs[0][order], return_index=True)[1]
    out[pairs[0][order][first]] = pairs[1][order][first]
    return out


def patches(mask, transform, plastic_n, valid_n, zone_idx, zones, parcel_idx, parcels,
            site_slug: str, year: int) -> list[dict]:
    """One GeoJSON feature per connected patch of `mask`, with what is known about it."""
    polys = [shape(g) for g, _ in features.shapes(mask.astype(np.uint8), mask=mask,
                                                  transform=transform, connectivity=8)]
    if not polys:
        return []
    labels = features.rasterize([(p, i + 1) for i, p in enumerate(polys)], mask.shape,
                                transform=transform, fill=0, dtype="int32")
    labels[~mask] = 0
    n = len(polys)
    px = np.bincount(labels.ravel(), minlength=n + 1)
    plastic_sum = np.bincount(labels.ravel(), weights=plastic_n.ravel(), minlength=n + 1)
    valid_sum = np.bincount(labels.ravel(), weights=valid_n.ravel(), minlength=n + 1)
    zone_of = _majority(labels, zone_idx, n)
    parcel_of = _majority(labels, parcel_idx, n)
    greenhouse = np.zeros(n + 1)
    coef_any = np.zeros(n + 1)
    if parcels:
        use_iv = np.array([False] + [p.use == "IV" for p in parcels])
        coef = np.array([0] + [p.irrigation_coef for p in parcels])
        greenhouse = np.bincount(labels.ravel(), weights=use_iv[parcel_idx].ravel(), minlength=n + 1)
        coef_any = np.bincount(labels.ravel(), weights=(coef[parcel_idx] > 0).ravel(), minlength=n + 1)

    irrigable = [z.geom for z in zones if z.irrigable and not z.urban]
    tree = STRtree(irrigable)
    to_ll = Transformer.from_crs(config.IRRIGATION_CRS, 4326, always_xy=True).transform
    res2 = abs(transform.a * transform.e)
    out = []
    for i, poly in enumerate(polys, start=1):
        ha = px[i] * res2 / 10_000
        c = poly.representative_point()
        _, dist = tree.query_nearest(poly, return_distance=True)
        z = zones[zone_of[i] - 1] if zone_of[i] else None
        p = parcels[parcel_of[i] - 1] if parcel_of[i] else None
        greenhouse_share = greenhouse[i] / px[i]
        coef_share = coef_any[i] / px[i]
        lon, lat = to_ll(c.x, c.y)
        geom = set_precision(legal.reproject(poly.simplify(transform.a / 2), config.IRRIGATION_CRS, 4326), 1e-6)
        out.append({"type": "Feature", "geometry": mapping(geom), "properties": {
            "id": f"{site_slug}-{year}-{int(c.x) // 10 * 10}-{int(c.y) // 10 * 10}",
            "ha": round(ha, 2),
            # Means over the patch, so the two read together: plastic on 9 of 10 clear dates.
            "plastic_dates": round(plastic_sum[i] / px[i], 1),
            "valid_dates": round(valid_sum[i] / px[i], 1),
            "admin_zone": z.admin_zone if z else None,
            "plan_zone": z.label if z else None,
            "distance_to_irrigable_m": round(float(dist[0])),
            "sigpac_ref": p.ref if p else None,
            "sigpac_use": p.use if p else None,
            "sigpac_irrigation_coef": p.irrigation_coef if p else None,
            "sigpac_url": legal.sigpac_info_url(p.ref) if p else None,
            # Share of the patch on parcels that SIGPAC itself records as greenhouse or
            # with irrigation rights: the administrations' own records contradicting the
            # plan's map, independent of the satellite.
            "declared_greenhouse_share": round(float(greenhouse_share), 2),
            "declared_irrigated_share": round(float(coef_share), 2),
            "lon": round(lon, 6), "lat": round(lat, 6),
        }})
    out.sort(key=lambda f: -f["properties"]["ha"])
    return out


# --- run -------------------------------------------------------------------------------

def _ha(mask) -> float:
    return round(float(mask.sum()) * config.IRRIGATION_RES_M**2 / 10_000)


def run(site: IrrigationSite, year: int, refresh_zoning: bool = False,
        log: Callable = print) -> dict:
    zones = legal.peorcfd_zoning(refresh=refresh_zoning)
    shape_hw, transform = plan_grid(zones)
    zone, zone_idx = zone_rasters(zones, shape_hw, transform)
    in_plan = zone > OUT_OF_PLAN
    log(f"Ámbito del plan: {_ha(in_plan):,} ha, suelo regable {_ha(zone == IRRIGABLE):,} ha")

    campaign = legal.available_campaign(site.province, year)
    if campaign is None:
        raise RuntimeError("FEGA no sirve ninguna campaña de SIGPAC cercana")
    log(f"SIGPAC campaña {campaign} ({len(site.municipalities)} municipios)")
    parcels = legal.sigpac_parcels(site.province, site.municipalities, campaign)
    parcel_idx = parcel_raster(parcels, shape_hw, transform)
    non_farming = np.array([True] + [p.use in config.NON_FARMING_USES for p in parcels])
    farming = (parcel_idx > 0) & ~non_farming[parcel_idx]

    geobox = GeoBox(shape_hw, transform, config.IRRIGATION_CRS)
    valid_n, plastic_n, used = composite(site, year, geobox, in_plan, log)
    if not used:
        raise RuntimeError(f"ninguna fecha válida en {year} para {site.slug}")

    persistent = plastic_n >= config.PLASTIC_MIN_DATES
    out, stages = outside_mask(plastic_n, zone, farming)
    feats = patches(out, transform, plastic_n, valid_n, zone_idx, zones, parcel_idx, parcels,
                    site.slug, year)
    declared = sum(f["properties"]["ha"] for f in feats
                   if max(f["properties"]["declared_greenhouse_share"],
                          f["properties"]["declared_irrigated_share"]) >= 0.5)
    adjacent = sum(f["properties"]["ha"] for f in feats
                   if f["properties"]["distance_to_irrigable_m"] <= config.ADJACENT_M)
    by_zone: dict[str, float] = {}
    for f in feats:
        k = f["properties"]["admin_zone"] or "?"
        by_zone[k] = round(by_zone.get(k, 0) + f["properties"]["ha"], 1)

    summary = {
        "site": site.slug, "name": site.name, "wetland": site.wetland, "campaign": year,
        "window_months": list(site.months), "dates": used,
        "plan_ha": _ha(in_plan), "irrigable_ha": _ha(zone == IRRIGABLE),
        "plastic_in_plan_ha": _ha(persistent & in_plan),
        "plastic_in_irrigable_ha": _ha(persistent & (zone == IRRIGABLE)),
        # What each filter leaves, from the upper bound down to the reported patches.
        "funnel_ha": {k: _ha(v) for k, v in stages.items()},
        "outside_ha": round(sum(f["properties"]["ha"] for f in feats), 1),
        "outside_patches": len(feats),
        "outside_declared_ha": round(declared, 1),
        "outside_adjacent_ha": round(adjacent, 1),
        "outside_by_admin_zone": by_zone,
        "sigpac_campaign": campaign,
        "sources": {"zoning": config.PEORCFD_WFS, "sigpac": config.SIGPAC_ATOM,
                    "sentinel2": config.STAC_URL},
        "rules": {k: getattr(config, k) for k in (
            "PLASTIC_RPGI_MIN", "PLASTIC_PMLI_MAX", "PLASTIC_BLUE_RED_MIN", "PLASTIC_MIN_DATES",
            "LEGAL_EDGE_M", "PATCH_MIN_HA", "IRRIGATION_RES_M")},
    }
    base = config.IRRIGATION_DIR / f"{site.slug}_{year}"
    base.with_suffix(".geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
    base.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=1),
                                         encoding="utf-8")
    return summary
