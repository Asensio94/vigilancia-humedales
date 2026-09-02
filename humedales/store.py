"""Series históricas por humedal en CSV (una fila por fecha)."""
from __future__ import annotations

import pandas as pd

from . import config
from .indices import Observation

COLUMNS = ["site", "date", "n_scenes", "scenes", "coverage", "cloud_frac", "valid_frac",
           "blue_median", "site_ha", "water_ha", "water_frac", "wet_veg_ha", "ndwi_water_ha", "scl_water_ha",
           "ndti_mean", "ndci_mean", "ndci_p90", "bloom_frac", "quality", "processed_at"]

NUMERIC = ["coverage", "cloud_frac", "valid_frac", "blue_median", "site_ha", "water_ha",
           "water_frac", "wet_veg_ha", "ndwi_water_ha", "scl_water_ha", "ndti_mean",
           "ndci_mean", "ndci_p90", "bloom_frac"]


def path(slug: str):
    return config.SERIES_DIR / f"{slug}.csv"


def load(slug: str) -> pd.DataFrame:
    p = path(slug)
    if not p.exists():
        return pd.DataFrame(columns=COLUMNS)
    df = pd.read_csv(p, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for col in NUMERIC:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def upsert(slug: str, observations: list[Observation]) -> pd.DataFrame:
    df = load(slug)
    now = pd.Timestamp.utcnow().isoformat(timespec="seconds")
    rows = []
    for o in observations:
        r = o.to_row()
        r["processed_at"] = now
        rows.append(r)
    new = pd.DataFrame(rows, columns=COLUMNS)
    new["date"] = pd.to_datetime(new["date"]).dt.date
    # Las métricas pueden llegar como None (sin agua suficiente); sin este casteo la
    # columna queda de tipo object y pandas la descarta al calcular medianas.
    for col in NUMERIC:
        new[col] = pd.to_numeric(new[col], errors="coerce")
    if not df.empty:
        df = df[~df["date"].isin(set(new["date"]))]
    out = pd.concat([df, new], ignore_index=True).sort_values("date")
    out.to_csv(path(slug), index=False)
    return out


def known_dates(slug: str) -> set:
    df = load(slug)
    return set(df["date"]) if not df.empty else set()
