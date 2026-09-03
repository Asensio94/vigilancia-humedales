"""Contexto hidrológico medido en el suelo, para explicar las alertas.

El satélite dice cuánta superficie hay inundada, no por qué. Una desecación puede
venir de que no ha llovido, de que el acuífero ha bajado o de que alguien ha abierto
una compuerta, y la respuesta cambia según el caso.

De momento la única red española de humedales con datos abiertos, series largas y una
interfaz consultable por programa es la de la Estación Biológica de Doñana: ocho
estaciones automáticas dentro de la marisma, cinco de ellas con nivel de agua, más
lluvia y meteorología, con licencia CC BY 4.0. Publica media diaria desde 2022 y
medidas cada cinco minutos desde 2020.

Lo que se buscó y no sirve todavía:
- Piezómetros del acuífero Almonte-Marismas: la red oficial de la Confederación
  Hidrográfica del Guadalquivir tiene 195 puntos, pero solo se publican como
  visor y mapas, sin servicio de descarga por programa.
- Piezometría de la Mancha Occidental, que es lo que explicaría las Tablas de
  Daimiel: la Confederación Hidrográfica del Guadiana publica datos mensuales,
  pero su catálogo de datos abiertos está en construcción y solo expone mapas.
- Aforos: el anuario nacional se publica por descarga manual, no por servicio.
Cuando alguna de las tres abra un servicio consultable, encaja en este módulo sin
tocar nada más: basta añadir otra fuente con la misma forma.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from datetime import date, timedelta

import pandas as pd
from shapely.geometry import Point

from . import config
from .sites import SITES, Site, site_geometry

API = "https://datos-automaticos.icts-donana.es/api/v1"
SOURCE = "ICTS-Doñana (Estación Biológica de Doñana, CSIC) — CC BY 4.0"
TIMEOUT = 90
PAGE_LIMIT = 20          # tope de páginas por serie, por si la paginación se descontrola
# El portal limita a 100 peticiones por hora y dirección. Recorrer el catálogo cuesta
# unas 30 y cada serie diaria una o dos, así que todo lo que se puede decidir una vez
# se guarda en disco: el catálogo de estaciones, el sensor elegido por variable y las
# propias series, que solo se piden desde la última fecha que ya se tiene.
RATE_LIMIT_HINT = ("El portal de la ICTS-Doñana admite 100 peticiones por hora y dirección. "
                   "Espera una hora o pide un límite mayor al equipo de Hidromet.")
VARIABLES = ("waterLevel", "rainfallAccumulated")


def _dir():
    d = config.DATA_DIR / "hydro"
    d.mkdir(parents=True, exist_ok=True)
    return d


class RateLimited(RuntimeError):
    """El portal ha rechazado la petición por exceso de consultas."""


# Humedales cuya última serie se sirvió desde la caché por haber agotado el límite.
_LIMITED: set[str] = set()


def _open(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimited(RATE_LIMIT_HINT) from exc
        raise


def _get(path: str, **params) -> dict:
    url = f"{API}/{path.strip('/')}/"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    return _open(url)


@dataclass
class Station:
    station_id: int
    name: str
    latitude: float
    longitude: float
    site: str | None          # humedal que la contiene, si alguno
    variable: str
    acronym: str              # instrumento, p. ej. WaterLevelMestech
    method: str               # calc_procedure_method
    aggr: str                 # aggr_method: Average para niveles, Totalize para lluvia
    daily_from: str | None
    daily_to: str | None
    unit: str | None = None


def _site_for(lat: float, lon: float) -> str | None:
    p = Point(lon, lat)
    for s in SITES.values():
        try:
            if site_geometry(s).contains(p):
                return s.slug
        except Exception:  # noqa: BLE001
            continue
    return None


def discover(variables: tuple[str, ...] = VARIABLES, refresh: bool = False) -> list[Station]:
    """Recorre el catálogo y guarda qué estación mide qué, y desde cuándo."""
    cache = _dir() / "stations.json"
    if cache.exists() and not refresh:
        return [Station(**d) for d in json.loads(cache.read_text(encoding="utf-8"))]

    found: list[Station] = []
    for st in _get("catalog/stations")["stations"]:
        sid = st["station_id"]
        site = _site_for(st["latitude"], st["longitude"])
        groups = _get("catalog/variables", station=sid)["variable_groups"]
        available = {v["variable"] for g in groups for v in g["variables"]}
        for var in variables:
            if var not in available:
                continue
            for ins in _get("catalog/instruments", station=sid, variable=var)["instruments"]:
                acr = ins["instrument"]
                qp = _get("catalog/query-params", station=sid, variable=var, instrument=acr)
                for combo in qp["combinations"]:
                    daily = combo.get("date_ranges", {}).get("daily") or {}
                    found.append(Station(
                        station_id=sid, name=st["name"], latitude=st["latitude"],
                        longitude=st["longitude"], site=site, variable=var, acronym=acr,
                        method=combo["calc_procedure_method"],
                        aggr=combo.get("aggr_method") or combo["calc_procedure_method"],
                        daily_from=daily.get("from"), daily_to=daily.get("to")))
                    break   # una combinación por instrumento basta
    cache.write_text(json.dumps([asdict(s) for s in found], indent=2, ensure_ascii=False),
                     encoding="utf-8")
    return found


def _series_path(st: Station):
    return _dir() / f"{st.station_id}_{st.variable}_{st.acronym}.csv"


def fetch(st: Station, start: date, end: date) -> pd.DataFrame:
    """Media diaria de una estación y variable. Guarda en caché y solo pide lo que falta."""
    p = _series_path(st)
    have = pd.DataFrame(columns=["date", "value"])
    if p.exists():
        have = pd.read_csv(p, parse_dates=["date"])
        have["value"] = pd.to_numeric(have["value"], errors="coerce")
        if not have.empty:
            # Se pide solo desde el día siguiente al último que ya se tiene: sin esto
            # cada lectura de una serie al día gastaba una petición para no traer nada.
            start = max(start, have["date"].max().date() + timedelta(days=1))

    rows: list[dict] = []
    if start <= end:
        params = dict(place=st.station_id, variable=st.variable, acronym=st.acronym,
                      calc_procedure_method=st.method, aggr_method=st.aggr,
                      start_date=start.isoformat(), end_date=end.isoformat())
        page, url = 1, None
        while page <= PAGE_LIMIT:
            try:
                d = _get("daily", **params) if url is None else _open(url)
            except urllib.error.HTTPError:
                break   # combinación sin datos en ese tramo
            rows += d.get("results", [])
            st.unit = (d.get("metadata") or {}).get("unit", st.unit)
            url = (d.get("pagination") or {}).get("next")
            if not url:
                break
            page += 1

    if rows:
        new = pd.DataFrame(rows)
        new["date"] = pd.to_datetime(new["date"])
        new["value"] = pd.to_numeric(new["value"], errors="coerce")
        out = (pd.concat([have, new[["date", "value"]]])
               .dropna(subset=["date"]).drop_duplicates("date", keep="last")
               .sort_values("date").reset_index(drop=True))
        out["value"] = pd.to_numeric(out["value"], errors="coerce")
        out.to_csv(p, index=False)
        return out
    return have


def choose_instrument(site: Site, variable: str, start: date, end: date) -> str | None:
    """Elige el modelo de sensor con mejor cobertura en el conjunto del humedal.

    Varias estaciones llevan dos sensores midiendo lo mismo, y no son intercambiables:
    en Doñana los Mobrey dan calado sobre el fondo de la marisma, entre 0 y 1,35 m, en
    las cinco estaciones y casi todos los días desde 2022, mientras que los Mestech
    mezclan referencias (algunos saltan a 13-14 m, que es altura sobre un plano de
    referencia) y tienen años enteros sin servicio. Mezclarlos daría una serie sin
    sentido físico, así que se usa un solo modelo, el que cubre más estaciones y más
    días. La decisión se toma con los datos, no por nombre de fabricante.

    Puntuar cuesta una petición por estación, y el portal solo admite cien por hora, así
    que la elección se guarda en `data/hydro/instruments.json` y no se repite. Cuando el
    límite ya está agotado se puede sembrar ese fichero a mano si los metadatos bastan
    para decidir: la lluvia de Doñana está fijada así al VaisalaMeteo, que es el único
    modelo presente en siete de las ocho estaciones y llega hasta hoy.
    """
    cache = _dir() / "instruments.json"
    chosen = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    key = f"{site.slug}|{variable}"
    if key in chosen:
        return chosen[key]

    stations = [st for st in discover() if st.site == site.slug and st.variable == variable]
    score: dict[str, tuple[int, int]] = {}
    for st in stations:
        df = fetch(st, start, end)
        days = int(df["value"].notna().sum()) if not df.empty else 0
        n_st, n_days = score.get(st.acronym, (0, 0))
        score[st.acronym] = (n_st + (1 if days >= 365 else 0), n_days + days)
    if not score:
        return None
    best = max(score, key=lambda a: score[a])
    chosen[key] = best
    cache.write_text(json.dumps(chosen, indent=2, ensure_ascii=False), encoding="utf-8")
    return best


def fetch_cached(st: Station) -> pd.DataFrame:
    """Lo que ya está en disco, sin tocar la red."""
    p = _series_path(st)
    if not p.exists():
        return pd.DataFrame(columns=["date", "value"])
    df = pd.read_csv(p, parse_dates=["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df


def series(site: Site, variable: str, start: date, end: date) -> pd.DataFrame:
    """Tabla ancha: una columna por estación del humedal, todas con el mismo sensor."""
    acr = choose_instrument(site, variable, start, end)
    if acr is None:
        return pd.DataFrame()
    cols, limited = {}, False
    for st in discover():
        if st.site != site.slug or st.variable != variable or st.acronym != acr:
            continue
        try:
            df = fetch(st, start, end)
        except RateLimited:
            # Mejor un informe con la serie guardada y un aviso que ningún informe.
            limited = True
            df = fetch_cached(st)
        if not df.empty and df["value"].notna().sum() > 0:
            cols[st.name] = df.set_index("date")["value"]
    # pandas no conserva attrs al agregar entre columnas, y el informe necesita saber
    # si lo que está pintando llega hasta hoy o se quedó en la última descarga. Se
    # registra antes de la salida en vacío: quedarse sin serie por el límite es
    # justo el caso que hay que avisar.
    if limited:
        _LIMITED.add(site.slug)
    if not cols:
        return pd.DataFrame()
    out = pd.DataFrame(cols).sort_index()
    out.attrs["instrument"] = acr
    out.attrs["source"] = SOURCE
    out.attrs["stale"] = limited
    return out


def marsh_level(site: Site, start: date, end: date) -> pd.Series:
    """Un solo indicador del humedal: mediana del calado entre estaciones."""
    df = series(site, "waterLevel", start, end)
    if df.empty:
        return pd.Series(dtype="float64")
    return df.median(axis=1, skipna=True)


def rainfall(site: Site, start: date, end: date) -> pd.Series:
    """Lluvia diaria media entre estaciones, en milímetros."""
    df = series(site, "rainfallAccumulated", start, end)
    if df.empty:
        return pd.Series(dtype="float64")
    return df.mean(axis=1, skipna=True)


def has_context(slug: str) -> bool:
    return any(s.site == slug for s in discover())


def was_limited(slug: str) -> bool:
    """True si la última lectura de este humedal se sirvió desde la caché por el límite."""
    return slug in _LIMITED
