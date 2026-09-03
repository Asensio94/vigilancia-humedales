"""Área inundable de cada humedal, medida con los propios datos.

El polígono de la red europea de espacios protegidos es la unidad administrativa,
no la unidad hidrológica: el de Doñana incluye pinares, arenas y marisma seca. Usarlo
como denominador hace que "fracción del humedal inundada" no signifique nada allí.

El denominador que sí significa algo es el área que alguna vez tiene agua. Se mide
acumulando los píxeles de agua de una muestra de fechas buenas repartidas por los
años de serie, con preferencia por los meses húmedos, que es cuando la lámina alcanza
su extensión máxima. El resultado es un mapa de frecuencia de inundación, del que se
derivan dos cosas: el área inundable (píxeles con agua en al menos una fecha) y el
área de agua permanente (píxeles con agua en casi todas).

Es una medida de la muestra, no una verdad absoluta: con más fechas el área inundable
solo puede crecer. Por eso se guarda cuántas fechas la sostienen.
"""
from __future__ import annotations

import json
from datetime import date

import numpy as np

from . import config, stac
from .indices import observe, resolution_for
from .sites import Site, site_geometry

WET_MONTHS = (12, 1, 2, 3, 4)   # la lámina ibérica alcanza su máximo al final del invierno
PER_YEAR_MONTH = 1              # fechas por año y mes húmedo
MIN_FREQ_FLOODABLE = 1          # agua en al menos esta cantidad de fechas = inundable
PERMANENT_FRACTION = 0.90       # agua en esta fracción de las fechas = permanente


def path(slug: str):
    d = config.DATA_DIR / "masks"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{slug}.json"


def sample_dates(site: Site, geom, start: date, end: date) -> dict:
    """Una fecha por año y mes húmedo, la de menos nubes de la escena."""
    from .backfill import search_all
    days = search_all(site, geom, start, end, max_scene_cloud=25.0)
    best: dict[tuple[int, int], tuple[float, date]] = {}
    for d, its in days.items():
        if d.month not in (site.wet_months or WET_MONTHS):
            continue
        cloud = min(float(it.properties.get("eo:cloud_cover", 100)) for it in its)
        key = (d.year, d.month)
        if key not in best or cloud < best[key][0]:
            best[key] = (cloud, d)
    return {d: days[d] for _, d in sorted(best.values(), key=lambda t: t[1])}


def build(site: Site, start: date, end: date, log=print) -> dict:
    geom = site_geometry(site)
    days = sample_dates(site, geom, start, end)
    meses = ", ".join(str(mes) for mes in (site.wet_months or WET_MONTHS))
    log(f"{site.name}: {len(days)} fechas candidatas de los meses {meses}")

    counts: np.ndarray | None = None
    inside: np.ndarray | None = None
    used: list[str] = []
    for d, its in days.items():
        try:
            obs, rasters = observe(site.slug, d, its, geom, with_rasters=True)
        except Exception as exc:  # noqa: BLE001
            log(f"  {d}: no se pudo leer ({type(exc).__name__})")
            continue
        if obs.quality != "ok":
            log(f"  {d}: descartada ({obs.quality})")
            continue
        if counts is None:
            counts = np.zeros(rasters.water.shape, dtype="uint16")
            inside = rasters.inside
        elif rasters.water.shape != counts.shape:
            log(f"  {d}: rejilla distinta, descartada")
            continue
        # Agua libre y vegetación inundada cuentan las dos: las dos son humedal con agua.
        counts += (rasters.water | rasters.wet_veg).astype("uint16")
        used.append(d.isoformat())
        log(f"  {d}: sumada ({obs.water_ha:.0f} ha de agua libre)")

    if counts is None or not used:
        raise RuntimeError(f"{site.name}: ninguna fecha utilizable para el área inundable")

    n = len(used)
    pixel_ha = config.pixel_ha(resolution_for(site.slug))
    floodable = (counts >= MIN_FREQ_FLOODABLE) & inside
    permanent = (counts >= max(1, int(round(PERMANENT_FRACTION * n)))) & inside
    result = {
        "site": site.slug,
        "dates_used": n,
        "dates": used,
        "site_ha": round(float(inside.sum()) * pixel_ha, 1),
        "floodable_ha": round(float(floodable.sum()) * pixel_ha, 1),
        "permanent_ha": round(float(permanent.sum()) * pixel_ha, 1),
        "min_freq_floodable": MIN_FREQ_FLOODABLE,
        "permanent_fraction": PERMANENT_FRACTION,
    }
    path(site.slug).write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def load(slug: str) -> dict | None:
    p = path(slug)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def floodable_ha(slug: str) -> float | None:
    """Denominador con sentido hidrológico, o None si aún no se ha medido."""
    m = load(slug)
    return m["floodable_ha"] if m else None
