"""Recorte de la franja marina en los humedales costeros.

El polígono de la red europea de espacios protegidos es la unidad administrativa, y en
un humedal costero esa unidad suele entrar en el mar. El de la Camarga lo hace: sin
recortarlo, la primera medida del 2 de septiembre de 2026 dio 56.542 ha «de agua», de
las que dos tercios eran Mediterráneo abierto. Es el mismo problema que resuelve
`masks.py` con el área inundable, pero al revés y más grave: el mar no distorsiona el
denominador, distorsiona la medida, y lo hace en todas las fechas a la vez.

La línea de costa la da OpenStreetMap, que es la más precisa disponible sin clave, y
trae además lo que hace falta para saber de qué lado está el mar: en OSM los trazos
`natural=coastline` van orientados con **la tierra a la izquierda**, convención que el
propio proyecto valida. Así que basta cortar el polígono por la costa y quedarse con
las piezas que no tengan mar a su lado, sin depender de ninguna capa de batimetría.

No se usa el satélite para decidirlo, aunque sería tentador: el mar es agua en todas
las fechas, pero también lo son una laguna permanente y el cauce de un río, y separar
las tres por contigüidad falla justo donde importa, en las lagunas litorales que un
canal de un píxel de ancho conecta con el mar.
"""
from __future__ import annotations

import json

import requests
from pyproj import Transformer
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import transform, unary_union
from shapely.prepared import prep

from . import config

# Dos servidores porque el principal limita por IP y a veces devuelve 504 en horas
# punta. Overpass rechaza con 406 las peticiones sin agente identificable.
OVERPASS = ("https://overpass-api.de/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter")
UA = "vigilancia-humedales/0.1 (seguimiento de humedales protegidos; codigo abierto)"
TIMEOUT = 180

MARGEN_DEG = 0.05    # se pide algo más de costa que el propio humedal, para cortar de lado a lado
SONDA_M = 250        # a qué distancia del trazo se pincha el lado mar
SONDA_PASO_M = 300   # separación entre sondas a lo largo de la costa
CORTE_M = 15         # semiancho del corte; la orilla pierde 15 m y el mar entero se va
MIN_SONDAS = 5       # sondas de mar dentro de una pieza para poder llamarla mar


def _via_es_costa(bounds) -> str:
    minx, miny, maxx, maxy = bounds
    caja = (f"{miny - MARGEN_DEG},{minx - MARGEN_DEG},"
            f"{maxy + MARGEN_DEG},{maxx + MARGEN_DEG}")
    return f'[out:json][timeout:120];\nway["natural"="coastline"]({caja});\nout geom;'


def lineas_de_costa(slug: str, bounds, refresh: bool = False) -> list[LineString]:
    """Trazos de costa alrededor del humedal, en EPSG:4326 y cacheados en disco.

    Se respeta el orden de los nodos tal como viene de OSM: es lo que dice dónde está
    el mar, así que no se puede normalizar ni simplificar el trazo.
    """
    ruta = config.SITES_DIR / f"{slug}_costa.geojson"
    if ruta.exists() and not refresh:
        with ruta.open(encoding="utf-8") as fh:
            return [shape(g) for g in json.load(fh)["geometries"]]

    error = None
    for url in OVERPASS:
        try:
            r = requests.post(url, data={"data": _via_es_costa(bounds)},
                              headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
            elementos = r.json()["elements"]
            break
        except Exception as exc:  # noqa: BLE001
            error = exc
    else:
        raise RuntimeError(f"no se pudo obtener la línea de costa de OSM: {error}")

    lineas = [LineString([(n["lon"], n["lat"]) for n in e["geometry"]])
              for e in elementos
              if e.get("type") == "way" and len(e.get("geometry") or ()) > 1]
    with ruta.open("w", encoding="utf-8") as fh:
        json.dump({"type": "GeometryCollection",
                   "geometries": [mapping(l) for l in lineas]}, fh)
    return lineas


def sondas(lineas: list[LineString]) -> tuple[list[Point], list[Point]]:
    """Pares de puntos a un lado y otro de la costa, uno cada SONDA_PASO_M.

    La normal a la derecha del avance del trazo apunta al mar por la convención de OSM,
    y la de la izquierda a la tierra. Se pinchan los dos lados porque la convención se
    incumple de vez en cuando y algún trazo apunta al revés: con un solo lado, cinco
    sondas equivocadas bastaban para dar por mar las 77.000 ha del delta entero.
    Comparando los dos lados, esas cinco pierden contra las cuatrocientas correctas.
    Las líneas tienen que venir ya en un sistema en metros.
    """
    mar: list[Point] = []
    tierra: list[Point] = []
    for linea in lineas:
        recorrido = 0.0
        coords = list(linea.coords)
        for (x1, y1), (x2, y2) in zip(coords, coords[1:]):
            dx, dy = x2 - x1, y2 - y1
            largo = (dx * dx + dy * dy) ** 0.5
            if largo == 0:
                continue
            recorrido += largo
            if recorrido < SONDA_PASO_M:
                continue
            recorrido = 0.0
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            nx, ny = dy / largo * SONDA_M, -dx / largo * SONDA_M   # normal a la derecha
            mar.append(Point(mx + nx, my + ny))
            tierra.append(Point(mx - nx, my - ny))
    return mar, tierra


def recortar_mar(geom, slug: str, crs: str, log=print, refresh: bool = False):
    """Devuelve el humedal sin su franja de mar, o el mismo si no toca la costa."""
    lineas = lineas_de_costa(slug, geom.bounds, refresh=refresh)
    if not lineas:
        log(f"  {slug}: no hay costa alrededor, no se recorta nada")
        return geom

    a_metros = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    a_grados = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
    poly_m = transform(a_metros, geom)
    lineas_m = [transform(a_metros, l) for l in lineas]

    piezas = poly_m.difference(unary_union(lineas_m).buffer(CORTE_M))
    trozos = list(getattr(piezas, "geoms", [piezas]))
    if len(trozos) == 1:
        log(f"  {slug}: la costa no parte el polígono, no se recorta nada")
        return geom

    s_mar, s_tierra = sondas(lineas_m)
    tierra, mar_ha = [], 0.0
    for trozo in trozos:
        preparado = prep(trozo)
        n_mar = sum(1 for p in s_mar if preparado.contains(p))
        n_tierra = sum(1 for p in s_tierra if preparado.contains(p))
        if n_mar >= MIN_SONDAS and n_mar > n_tierra:
            mar_ha += trozo.area / 10_000
        else:
            tierra.append(trozo)
    if not tierra:
        raise RuntimeError(f"{slug}: el recorte de costa se llevaría el humedal entero")
    if mar_ha == 0:
        log(f"  {slug}: ninguna pieza tiene mar al lado, no se recorta nada")
        return geom

    # El separador se cambia solo en el número: aplicarlo a la frase entera se
    # llevaría también la coma gramatical de "piezas, sondas".
    ha = f"{mar_ha:,.0f}".replace(",", ".")
    log(f"  {slug}: se recortan {ha} ha de mar "
        f"({len(trozos) - len(tierra)} de {len(trozos)} piezas, {len(s_mar)} sondas)")
    return transform(a_grados, unary_union(tierra))
