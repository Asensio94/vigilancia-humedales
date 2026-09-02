"""Catálogo de humedales vigilados y obtención de sus límites (Natura 2000)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import requests
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from . import config


@dataclass(frozen=True)
class Site:
    slug: str
    name: str
    natura_codes: tuple[str, ...]
    region: str
    notes: str = ""
    # Humedales donde la lámina de agua es permanente (lagunas costeras): la
    # métrica relevante es la calidad del agua, no la superficie inundada.
    permanent_water: bool = False


SITES: dict[str, Site] = {
    s.slug: s
    for s in [
        Site("donana", "Doñana", ("ES0000024",), "Andalucía",
             "Marismas del Guadalquivir. Inundación estacional; desecación por sobreexplotación del acuífero."),
        Site("mar-menor", "Mar Menor", ("ES6200030",), "Murcia",
             "Laguna hipersalina. Crisis de eutrofización recurrentes (2016, 2019, 2021).",
             permanent_water=True),
        Site("tablas-daimiel", "Tablas de Daimiel", ("ES0000013",), "Castilla-La Mancha",
             "Humedal fluvial dependiente del acuífero 23. Se seca casi por completo en sequías."),
        Site("albufera-valencia", "L'Albufera de València", ("ES0000023",), "C. Valenciana",
             "Laguna costera eutrófica rodeada de arrozal.", permanent_water=True),
        Site("fuente-piedra", "Laguna de Fuente de Piedra", ("ES0000033",), "Andalucía",
             "Laguna salina endorreica. Colonia de flamenco; se seca en verano."),
        Site("gallocanta", "Laguna de Gallocanta", ("ES2430043",), "Aragón",
             "Laguna salina endorreica. Invernada de grulla; ciclos plurianuales de inundación."),
    ]
}


def natura_geometry(sitecode: str) -> dict:
    params = {
        "where": f"SITECODE='{sitecode}'",
        "outFields": "SITECODE,SITENAME,SITETYPE",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    r = requests.get(config.NATURA_URL, params=params, timeout=60)
    r.raise_for_status()
    fc = r.json()
    if not fc.get("features"):
        raise RuntimeError(f"Natura 2000: sin resultados para {sitecode}")
    return fc["features"][0]


def site_geometry(site: Site, refresh: bool = False):
    """Devuelve la geometría shapely (EPSG:4326) del humedal, cacheada en disco."""
    path = config.SITES_DIR / f"{site.slug}.geojson"
    if path.exists() and not refresh:
        with path.open(encoding="utf-8") as fh:
            return shape(json.load(fh)["geometry"])
    geoms = []
    names = []
    for code in site.natura_codes:
        feat = natura_geometry(code)
        geoms.append(shape(feat["geometry"]).buffer(0))
        names.append(feat["properties"].get("SITENAME"))
    geom = unary_union(geoms)
    feature = {
        "type": "Feature",
        "properties": {"slug": site.slug, "name": site.name,
                       "natura_codes": list(site.natura_codes), "natura_names": names},
        "geometry": mapping(geom),
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(feature, fh, ensure_ascii=False)
    return geom
