"""Búsqueda de escenas Sentinel-2 L2A en Earth Search (AWS, sin autenticación)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from pystac import Item
from pystac_client import Client

from . import config

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = Client.open(config.STAC_URL)
    return _client


def search(bbox: tuple[float, float, float, float], start: date, end: date,
           max_scene_cloud: float = 60.0) -> list[Item]:
    """Escenas que intersectan el bbox entre start y end (inclusive).

    max_scene_cloud filtra por nubosidad de la escena completa (100x100 km); la
    nubosidad real sobre el humedal se evalúa después con la banda SCL.
    """
    s = client().search(
        collections=[config.STAC_COLLECTION],
        bbox=list(bbox),
        datetime=f"{start.isoformat()}T00:00:00Z/{end.isoformat()}T23:59:59Z",
        query={"eo:cloud_cover": {"lt": max_scene_cloud}},
        max_items=None,
    )
    return list(s.items())


def group_by_day(items: list[Item]) -> dict[date, list[Item]]:
    """Agrupa las escenas por día solar (las pasadas sobre España son ~11:00 UTC)."""
    groups: dict[date, list[Item]] = defaultdict(list)
    for it in items:
        groups[it.datetime.date()].append(it)
    return dict(sorted(groups.items()))


def band_scale_offset(item: Item, band: str) -> tuple[float, float]:
    """Escala y offset radiométrico a aplicar a los DN de un asset.

    Desde la baseline 04.00 (ene 2022) ESA añade un offset de -1000 DN a los
    productos L2A. Earth Search ya lo aplica dentro de sus COG y lo indica con la
    propiedad ``earthsearch:boa_offset_applied``; en ese caso, aunque
    ``raster:bands`` siga declarando offset=-0.1, NO hay que restarlo otra vez
    (se comprobó empíricamente: hacerlo deja la mitad del humedal con
    reflectancia negativa). Para escenas anteriores a la 04.00 el offset es 0.
    """
    asset = item.assets[band]
    rb = asset.extra_fields.get("raster:bands") or [{}]
    scale = float(rb[0].get("scale", 0.0001))
    baseline = str(item.properties.get("s2:processing_baseline", "00.00"))
    applied = bool(item.properties.get("earthsearch:boa_offset_applied", False))
    offset = -0.1 if (baseline >= "04.00" and not applied) else 0.0
    return scale, offset
