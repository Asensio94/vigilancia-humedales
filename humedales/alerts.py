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

    # --- Descenso brusco respecto a las semanas anteriores ------------------
    if not site.permanent_water:
        recent = df[(df["date"] >= when - timedelta(days=RECENT_DAYS + CURRENT_DAYS))
                    & (df["date"] < when - timedelta(days=CURRENT_DAYS))]
        if len(recent) >= 2:
            base = float(recent["water_ha"].median())
            if base >= 20 and last["water_ha"] < 0.7 * base:
                alerts.append(Alert(
                    site.slug, when, "descenso_brusco", "media",
                    f"La lámina de agua ha caído a {last['water_ha']:.0f} ha (mediana de {n_cur} obs.) desde una mediana "
                    f"de {base:.0f} ha en los {RECENT_DAYS} días anteriores "
                    f"({100 * (1 - last['water_ha'] / base):.0f} % menos).",
                    float(last["water_ha"]), base))

    # --- Eutrofización: umbral absoluto y desviación del histórico -----------
    ndci = last["ndci_mean"]
    bloom = last["bloom_frac"]
    if pd.notna(ndci):
        bloom_v = float(bloom) if pd.notna(bloom) else 0.0
        if ndci > config.NDCI_BLOOM or bloom_v > config.NDCI_BLOOM_FRAC:
            alerts.append(Alert(
                site.slug, when, "eutrofizacion", "alta",
                f"NDCI medio {ndci:.3f} y {100 * bloom_v:.0f} % de la lámina con NDCI > "
                f"{config.NDCI_BLOOM}: indicios de floración algal.",
                float(ndci), config.NDCI_BLOOM))
        elif len(ref) >= MIN_HISTORY:
            p90 = float(ref["ndci_mean"].quantile(0.90))
            if ndci > p90 + 0.02:
                alerts.append(Alert(
                    site.slug, when, "eutrofizacion", "media",
                    f"NDCI medio {ndci:.3f}, por encima del percentil 90 histórico para estas "
                    f"fechas ({p90:.3f}, n={len(ref)}).", float(ndci), p90))

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
