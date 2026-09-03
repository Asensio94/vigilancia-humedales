"""Reglas de alerta sobre la serie de un humedal.

Dos familias de reglas:
- Relativas al histórico: la última observación se compara con la distribución
  de observaciones de la misma época del año (±30 días) en años anteriores.
- Absolutas: umbrales de literatura (NDCI > 0.20 indica floración algal intensa).
Solo se evalúan observaciones con calidad "ok" y de satélites comparables entre sí
(ver EXCLUDE_SATELLITES).
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta

import pandas as pd

from . import config
from .sites import Site

MIN_HISTORY = 5          # observaciones mínimas para construir una referencia
SEASON_WINDOW_DAYS = 30  # ventana estacional ±días
RECENT_DAYS = 45         # ventana para detectar cambios bruscos
CURRENT_DAYS = 20        # el "valor actual" es la mediana de las observaciones ok de estos días
CURRENT_MIN_OBS = 2      # ...si hay al menos estas; si no, la última observación

# Ningún satélite queda vetado. Sentinel-2C lo estuvo mientras el sesgo parecía suyo:
# detectaba la mitad de agua que la clasificación de la ESA (razón 0,47 frente a 0,85
# de S2A y S2B). Al medirlo sobre un núcleo fijo de agua se vio que no era un sesgo de
# sensor sino una corrección atmosférica fallida, que afecta a los tres satélites con
# la misma firma espectral y solo es mucho más frecuente en S2C. El control espectral
# de indices.py la detecta por su causa, así que las escenas buenas de S2C ya entran:
# su concordancia con la ESA es 0,92, la de S2A 1,09 y la de S2B 1,00.
EXCLUDE_SATELLITES: tuple[str, ...] = ()


def usable(series: pd.DataFrame) -> pd.DataFrame:
    """Observaciones válidas y comparables entre sí."""
    df = series[series["quality"] == "ok"]
    if "scenes" in df and EXCLUDE_SATELLITES:
        sat = df["scenes"].str.slice(0, 3)
        df = df[~sat.isin(EXCLUDE_SATELLITES)]
    return df.sort_values("date")


@dataclass
class Alert:
    site: str
    date: date
    kind: str        # desecacion | descenso_brusco | eutrofizacion | turbidez
    severity: str    # alta | media
    message: str
    value: float | None
    reference: float | None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d


def _doy_distance(dates: pd.Series, when: date) -> pd.Series:
    a = pd.to_datetime(dates).dt.dayofyear
    b = pd.Timestamp(when).dayofyear
    diff = (a - b).abs()
    return pd.concat([diff, 365 - diff], axis=1).min(axis=1)


DROP_RATIO = 0.70            # caída mínima para considerar un descenso brusco
DROP_MIN_HA = 20             # por debajo de esto los porcentajes no significan nada
DROP_SEASON_PERCENTILE = 0.10   # y además tiene que ser peor que el 90 % de las caídas de la época
DROP_MIN_SEASON_REF = 5      # mínimo de caídas históricas para poder comparar


def drop_ratio(df: pd.DataFrame, when: date) -> tuple[float | None, float, float]:
    """Cociente entre la lámina actual y la de las semanas anteriores, en una fecha dada.

    Devuelve (cociente, valor actual, base). El cociente es None si no hay suficientes
    observaciones a los dos lados de la ventana.
    """
    cur = df[(df["date"] >= when - timedelta(days=CURRENT_DAYS)) & (df["date"] <= when)]
    prev = df[(df["date"] >= when - timedelta(days=RECENT_DAYS + CURRENT_DAYS))
              & (df["date"] < when - timedelta(days=CURRENT_DAYS))]
    if len(cur) < CURRENT_MIN_OBS or len(prev) < 2:
        return None, 0.0, 0.0
    last = float(pd.to_numeric(cur["water_ha"], errors="coerce").median())
    base = float(pd.to_numeric(prev["water_ha"], errors="coerce").median())
    if base < DROP_MIN_HA:
        return None, last, base
    return last / base, last, base


def seasonal_drop_ratio(df: pd.DataFrame, when: date) -> tuple[float | None, int]:
    """Cuánto suele caer la lámina en esta época del año, en años anteriores.

    Sin esto la regla de descenso brusco avisa de la desecación estival de siempre: en
    Gallocanta disparaba en 100 de 494 fechas, casi todas entre mayo y septiembre, y en
    Tablas de Daimiel 28 de sus 44 disparos eran de agosto. Una laguna endorreica que se
    seca cada verano no es una noticia; lo es que se seque antes o más deprisa que de
    costumbre. Se devuelve el percentil de las caídas históricas de estas fechas, así que
    solo salta lo que es peor que el 90 % de los años.
    """
    hist = df[df["date"] < when - timedelta(days=SEASON_WINDOW_DAYS)]
    if hist.empty:
        return None, 0
    same_season = hist[_doy_distance(hist["date"], when) <= SEASON_WINDOW_DAYS]
    ratios = [r for d in same_season["date"] if (r := drop_ratio(df, d)[0]) is not None]
    if len(ratios) < DROP_MIN_SEASON_REF:
        return None, len(ratios)
    return float(pd.Series(ratios).quantile(DROP_SEASON_PERCENTILE)), len(ratios)


BLOOM_PERCENTILE = 0.90      # percentil de los picos históricos de la época a superar
BLOOM_MARGIN = 0.02          # margen sobre ese percentil, para no saltar por el ruido


def window_peak(df: pd.DataFrame, when: date, col: str = "ndci_mean") -> float | None:
    """Valor máximo de la ventana reciente. Para la clorofila el pico es la señal.

    La lámina de agua se mide con la mediana de la ventana, porque su parpadeo entre
    pasadas es un artefacto espectral. Con la clorofila es al revés: una floración algal
    dura días, así que la mediana de tres semanas la borra. Medido sobre los seis
    humedales, la mediana de veinte días no supera nunca el umbral de floración de la
    literatura (0,20), ni una vez en 2.221 observaciones, mientras que por fecha
    Gallocanta llega a 0,514 con el 99 % de la lámina por encima del umbral.
    """
    cur = df[(df["date"] >= when - timedelta(days=CURRENT_DAYS)) & (df["date"] <= when)]
    if len(cur) < CURRENT_MIN_OBS:
        return None
    v = pd.to_numeric(cur[col], errors="coerce")
    return None if v.isna().all() else float(v.max())


def seasonal_peak(df: pd.DataFrame, when: date, col: str = "ndci_mean") -> tuple[float | None, int]:
    """Percentil de los picos de clorofila de esta época del año en años anteriores.

    Hay que comparar picos con picos. Contrastar el máximo de una ventana de ocho
    observaciones contra el percentil 95 de observaciones sueltas lo supera por pura
    construcción una vez de cada tres, y así la regla disparaba en el 40-70 % de las
    fechas. Con la distribución de los picos históricos de la misma época baja al 3-15 %,
    y los avisos caen donde tienen que caer: en el Mar Menor, en 2019 y 2021.
    """
    ref = seasonal_reference(df, when)
    peaks = [p for d in ref["date"] if (p := window_peak(df, d, col)) is not None]
    if len(peaks) < MIN_HISTORY:
        return None, len(peaks)
    return float(pd.Series(peaks).quantile(BLOOM_PERCENTILE)), len(peaks)


def seasonal_reference(df: pd.DataFrame, when: date) -> pd.DataFrame:
    """Observaciones ok de años anteriores dentro de ±SEASON_WINDOW_DAYS del día del año."""
    hist = df[df["date"] < when - timedelta(days=SEASON_WINDOW_DAYS)]
    if hist.empty:
        return hist
    return hist[_doy_distance(hist["date"], when) <= SEASON_WINDOW_DAYS]


def evaluate(site: Site, series: pd.DataFrame) -> list[Alert]:
    df = usable(series)
    if df.empty:
        return []
    when = df.iloc[-1]["date"]
    # Valor actual: mediana de las observaciones recientes. Amortigua el parpadeo
    # entre pasadas que sufren los humedales someros con vegetación emergente
    # (Tablas de Daimiel: la lámina detectada puede variar x3 en diez días).
    cur = df[df["date"] >= when - timedelta(days=CURRENT_DAYS)]
    if len(cur) >= CURRENT_MIN_OBS:
        cols = ["water_ha", "ndci_mean", "ndti_mean", "bloom_frac"]
        last = cur[cols].apply(pd.to_numeric, errors="coerce").median()
        n_cur = len(cur)
    else:
        last = df.iloc[-1]
        n_cur = 1
    alerts: list[Alert] = []
    ref = seasonal_reference(df, when)  # ya excluye los últimos SEASON_WINDOW_DAYS (> CURRENT_DAYS)

    # --- Desecación respecto al histórico estacional -----------------------
    if not site.permanent_water and len(ref) >= MIN_HISTORY:
        p10 = float(ref["water_ha"].quantile(0.10))
        med = float(ref["water_ha"].median())
        if last["water_ha"] < p10 and med > 0:
            alerts.append(Alert(
                site.slug, when, "desecacion", "alta",
                f"Lámina de agua de {last['water_ha']:.0f} ha (mediana de {n_cur} obs.), por debajo del percentil 10 "
                f"histórico para estas fechas ({p10:.0f} ha; mediana {med:.0f} ha, n={len(ref)}).",
                float(last["water_ha"]), p10))

    # --- Descenso brusco, comparado con lo que cae de normal en esta época ---
    if not site.permanent_water:
        ratio, cur_ha, base = drop_ratio(df, when)
        if ratio is not None and ratio < DROP_RATIO:
            season, n_ref = seasonal_drop_ratio(df, when)
            usual = season is not None and ratio >= season
            if not usual:
                extra = (f" Lo habitual en estas fechas es caer a lo sumo un "
                         f"{100 * (1 - season):.0f} % (n={n_ref})." if season is not None else
                         " Todavía no hay histórico de esta época con el que comparar la caída.")
                alerts.append(Alert(
                    site.slug, when, "descenso_brusco", "media",
                    f"La lámina de agua ha caído a {cur_ha:.0f} ha (mediana de {n_cur} obs.) desde una "
                    f"mediana de {base:.0f} ha en los {RECENT_DAYS} días anteriores "
                    f"({100 * (1 - ratio):.0f} % menos).{extra}",
                    cur_ha, base))

    # --- Eutrofización: pico de clorofila contra los picos de la misma época ---
    # El umbral absoluto de la literatura (NDCI > 0.20, unos 40 mg/m³ de clorofila-a según
    # Mishra & Mishra 2012) no es transferible a estas lagunas: se calibró en aguas
    # continentales profundas, y en lagunas someras y salinas con fondo claro el índice
    # está inflado de forma crónica. Usarlo para disparar da todo o nada: Gallocanta lo
    # supera en el 100 % de sus 494 fechas. Así que aquí dispara la anomalía frente al
    # propio humedal, y el umbral de literatura solo gradúa la gravedad.
    peak = window_peak(df, when)
    if peak is not None:
        season_peak, n_peaks = seasonal_peak(df, when)
        bloom_v = float(bloom_frac) if pd.notna(bloom_frac := last["bloom_frac"]) else 0.0
        if season_peak is not None and peak > season_peak + BLOOM_MARGIN:
            severity = "alta" if peak > config.NDCI_BLOOM else "media"
            alerts.append(Alert(
                site.slug, when, "eutrofizacion", severity,
                f"Pico de NDCI {peak:.3f} en los últimos {CURRENT_DAYS} días, por encima de los "
                f"picos habituales en estas fechas ({season_peak:.3f} es el percentil "
                f"{100 * BLOOM_PERCENTILE:.0f} de {n_peaks} ventanas de años anteriores)"
                + (f", con el {100 * bloom_v:.0f} % de la lámina por encima de "
                   f"{config.NDCI_BLOOM}" if bloom_v > 0.1 else "")
                + (". Supera además el umbral de floración algal de la literatura."
                   if peak > config.NDCI_BLOOM else "."),
                peak, season_peak))

    # --- Turbidez respecto al histórico ---------------------------------------
    ndti = last["ndti_mean"]
    if pd.notna(ndti) and len(ref) >= MIN_HISTORY:
        p90 = float(ref["ndti_mean"].quantile(0.90))
        if ndti > p90 + 0.02:
            alerts.append(Alert(
                site.slug, when, "turbidez", "media",
                f"NDTI medio {ndti:.3f}, por encima del percentil 90 histórico para estas "
                f"fechas ({p90:.3f}, n={len(ref)}).", float(ndti), p90))

    return alerts
