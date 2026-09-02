"""Carga masiva del histórico de un humedal, en paralelo y reanudable.

Cada fecha se procesa en un proceso aparte: el cuello de botella es la descarga
de los COG desde S3, así que varios procesos avanzan a la vez aunque cada uno
ya use dask internamente. Los resultados se guardan por lotes, de modo que una
interrupción no pierde más que el lote en curso y la siguiente ejecución
continúa donde se quedó (las fechas ya guardadas se omiten).
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Iterator

from pystac import Item
from shapely import wkt as shapely_wkt

from . import stac, store
from .indices import Observation, observe
from .sites import Site, site_geometry

# Doñana carga mosaicos de 3000x2800 px por banda; con más de cuatro procesos
# simultáneos la memoria se vuelve el límite en vez de la red.
WORKERS_BY_SIZE = ((20_000, 4), (5_000, 5), (0, 6))  # (hectáreas mínimas, procesos)
BATCH_DAYS = 12          # fechas por lote guardado
YEAR_CHUNK_DAYS = 180    # las búsquedas STAC se parten para no pedir miles de escenas


def workers_for(site_ha: float) -> int:
    for min_ha, n in WORKERS_BY_SIZE:
        if site_ha >= min_ha:
            return n
    return 4


ATTEMPTS = 3
RETRY_WAIT_S = 4


def _work(args) -> Observation | str:
    """Procesa una fecha en un proceso hijo. Devuelve la observación o un mensaje de error.

    Los fallos vistos en el backfill son de red y transitorios (DNS que no resuelve,
    CURL cortado, warp abortado por una lectura fallida), así que se reintenta antes
    de descartar la fecha: sin esto el histórico salía con cientos de huecos.
    """
    slug, day_iso, item_dicts, geom_wkt = args
    day = date.fromisoformat(day_iso)
    geom = shapely_wkt.loads(geom_wkt)
    last = ""
    for attempt in range(ATTEMPTS):
        try:
            items = [Item.from_dict(d) for d in item_dicts]
            obs, _ = observe(slug, day, items, geom, with_rasters=False)
            return obs
        except Exception as exc:  # noqa: BLE001
            last = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < ATTEMPTS:
                time.sleep(RETRY_WAIT_S * (attempt + 1))
    return f"{day_iso}: {last}"


def search_all(site: Site, geom, start: date, end: date,
               max_scene_cloud: float) -> dict[date, list[Item]]:
    """Busca en tramos de medio año para no agotar la paginación del catálogo."""
    days: dict[date, list[Item]] = {}
    cursor = start
    while cursor <= end:
        stop = min(cursor + timedelta(days=YEAR_CHUNK_DAYS), end)
        items = stac.search(geom.bounds, cursor, stop, max_scene_cloud)
        days.update(stac.group_by_day(items))
        cursor = stop + timedelta(days=1)
    return dict(sorted(days.items()))


def run(site: Site, start: date, end: date, max_scene_cloud: float = 60.0,
        workers: int | None = None, force: bool = False,
        log=print) -> Iterator[tuple[int, int, list[Observation]]]:
    """Genera (hechas, total, lote) tras guardar cada lote."""
    geom = site_geometry(site)
    geom_wkt = geom.wkt
    days = search_all(site, geom, start, end, max_scene_cloud)
    if not force:
        known = store.known_dates(site.slug)
        days = {d: its for d, its in days.items() if d not in known}
    total = len(days)
    if not total:
        log(f"{site.name}: nada que hacer entre {start} y {end}")
        return

    n_workers = workers or workers_for(_site_hectares(site))
    log(f"{site.name}: {total} fechas por procesar con {n_workers} procesos")

    tasks = [(site.slug, d.isoformat(), [it.to_dict() for it in its], geom_wkt)
             for d, its in days.items()]
    done = 0
    batch: list[Observation] = []
    failed: list[str] = []
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {pool.submit(_work, t): t[1] for t in tasks}
        for fut in as_completed(futures):
            done += 1
            result = fut.result()
            if isinstance(result, str):
                log(f"  FALLO {result}")
                failed.append(result.split(":", 1)[0])
            else:
                batch.append(result)
            if len(batch) >= BATCH_DAYS:
                store.upsert(site.slug, batch)
                yield done, total, batch
                batch = []
    if batch:
        store.upsert(site.slug, batch)
        yield done, total, batch
    if failed:
        log(f"  {len(failed)} fechas no se pudieron leer; repite el comando para reintentarlas")


def _site_hectares(site: Site) -> float:
    """Superficie aproximada del sitio, para dimensionar el paralelismo."""
    df = store.load(site.slug)
    if not df.empty and df["site_ha"].notna().any():
        return float(df["site_ha"].dropna().iloc[-1])
    geom = site_geometry(site)
    # Grados cuadrados a hectáreas en latitudes ibéricas, aproximación suficiente.
    return geom.area * 111_000 * 111_000 * 0.79 / 10_000


def cpu_default() -> int:
    return max(2, min(6, (os.cpu_count() or 4) // 2))
