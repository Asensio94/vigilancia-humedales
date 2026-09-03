"""Carga de bandas recortadas al humedal y cálculo de métricas por fecha."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date

import numpy as np
import xarray as xr
from odc.geo.geom import Geometry
from odc.geo.xr import rasterize  # noqa: F401  (registra el accesor .odc)
from odc.stac import load, configure_rio
from pystac import Item

from . import config
from .stac import band_scale_offset

configure_rio(cloud_defaults=True, aws={"aws_unsigned": True})


@dataclass
class Observation:
    site: str
    date: date
    n_scenes: int
    scenes: str
    coverage: float        # fracción del humedal cubierta por datos (no nodata)
    cloud_frac: float      # fracción nube/sombra/alta prob. de nube sobre la parte cubierta
    valid_frac: float      # fracción del humedal con píxel válido
    blue_median: float     # reflectancia azul mediana en píxeles válidos (detector de neblina)
    mndwi_thr: float       # umbral de agua usado en esta escena
    thr_method: str        # otsu | fijo
    water_nir_green: float | None  # infrarrojo cercano / verde sobre la semilla de agua
    water_blue: float | None       # azul mediano sobre la semilla de agua
    site_ha: float
    water_ha: float        # agua libre: MNDWI > 0 y NDVI bajo (ha)
    water_frac: float      # water_ha / superficie válida
    wet_veg_ha: float      # vegetación inundada/húmeda: MNDWI > 0 y NDVI alto (ha)
    ndwi_water_ha: float   # agua por NDWI > 0 (contraste)
    scl_water_ha: float    # agua según clasificación ESA (contraste)
    ndti_mean: float | None    # turbidez media sobre el agua libre
    ndci_mean: float | None    # clorofila media sobre el agua libre
    ndci_p90: float | None
    bloom_frac: float | None   # fracción del agua libre con NDCI > umbral
    quality: str           # ok | nublado | neblina | espectro_anomalo | incoherente | parcial | sin_datos

    def to_row(self) -> dict:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d


@dataclass
class Rasters:
    """Arrays de la fecha para pintar el informe."""
    rgb: np.ndarray        # (y, x, 3) reflectancia 0-1
    water: np.ndarray      # bool, agua libre
    wet_veg: np.ndarray    # bool, vegetación inundada
    invalid: np.ndarray    # bool (nube/sombra/nodata dentro del humedal)
    inside: np.ndarray     # bool
    ndci: np.ndarray       # float, NaN fuera del agua libre
    geobox: object


def resolution_for(site_slug: str) -> int:
    """Resolución de trabajo del humedal; ver RESOLUTION_BY_SITE en config."""
    return config.RESOLUTION_BY_SITE.get(site_slug, config.RESOLUTION_M)


def load_day(items: list[Item], geom, resolution_m: int | None = None) -> xr.Dataset:
    poly = Geometry(geom, "EPSG:4326")
    ds = load(
        items,
        bands=config.BANDS,
        crs=config.WORK_CRS,
        resolution=resolution_m or config.RESOLUTION_M,
        geopolygon=poly,
        groupby="solar_day",
        resampling={"scl": "nearest", "*": "average"},
        # Con dask la descarga de los COG va en paralelo: Doñana pasó de 185 s a 35 s
        # por fecha frente a la carga secuencial.
        chunks={"x": 1500, "y": 1500},
    )
    return ds.isel(time=0).compute(scheduler="threads", num_workers=config.DASK_THREADS)


def _reflectance(ds: xr.Dataset, item: Item, band: str) -> np.ndarray:
    scale, offset = band_scale_offset(item, band)
    dn = ds[band].values.astype("float32")
    refl = dn * scale + offset
    # Se acota a un mínimo positivo para que los cocientes normalizados queden en [-1, 1].
    refl = np.clip(refl, 1e-4, 1.5)
    refl[dn == 0] = np.nan
    return refl


def _nd(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        return (a - b) / (a + b)


def _otsu(values: np.ndarray) -> tuple[float, float]:
    """Corte de Otsu sobre un histograma y su separabilidad.

    Devuelve (umbral, separabilidad), donde la separabilidad es la fracción de la
    varianza total que explica la partición: cerca de 1 hay dos modas claras
    (agua y tierra), cerca de 0 el histograma es una sola nube y el corte no
    significa nada.
    """
    hist, edges = np.histogram(values, bins=config.OTSU_BINS, range=(-1.0, 1.0))
    total = hist.sum()
    if total == 0:
        return config.MNDWI_WATER, 0.0
    p = hist.astype("float64") / total
    centers = (edges[:-1] + edges[1:]) / 2.0
    w0 = np.cumsum(p)                    # peso de la clase baja (tierra)
    w1 = 1.0 - w0
    m0 = np.cumsum(p * centers)
    mt = m0[-1]
    with np.errstate(invalid="ignore", divide="ignore"):
        between = (mt * w0 - m0) ** 2 / (w0 * w1)
    if not np.isfinite(between).any():
        return config.MNDWI_WATER, 0.0
    k = int(np.nanargmax(between))
    var_total = float(np.sum(p * (centers - mt) ** 2))
    sep = float(between[k] / var_total) if var_total > 0 else 0.0
    return float(centers[k]), sep


def water_threshold(index: np.ndarray, valid: np.ndarray) -> tuple[float, str]:
    """Umbral de agua de esta escena: Otsu si el histograma tiene dos modas, fijo si no."""
    vals = index[valid]
    vals = vals[~np.isnan(vals)]
    if vals.size < config.OTSU_MIN_PIXELS:
        return config.MNDWI_WATER, "fijo"
    thr, sep = _otsu(vals)
    if sep < config.OTSU_MIN_SEPARABILITY:
        return config.MNDWI_WATER, "fijo"      # humedal seco o inundado por completo
    if not config.OTSU_THR_MIN <= thr <= config.OTSU_THR_MAX:
        return config.MNDWI_WATER, "fijo"      # el corte cae donde no puede estar la orilla
    return round(thr, 4), "otsu"


def water_spectrum(G: np.ndarray, NIR: np.ndarray, B: np.ndarray,
                   seed: np.ndarray, pixel_ha: float) -> tuple[float | None, float | None]:
    """Forma del espectro sobre la semilla de agua: cociente infrarrojo/verde y azul mediano.

    Sirve para detectar escenas cuya corrección atmosférica ha fallado sobre los
    objetivos oscuros, que es el defecto que hacía desaparecer láminas de agua
    perfectamente visibles. Ver la nota en config.
    """
    if seed.sum() * pixel_ha < config.WATER_SPECTRUM_MIN_HA:
        return None, None
    g = _stat(np.median, G, seed)
    n = _stat(np.median, NIR, seed)
    b = _stat(np.median, B, seed)
    if g is None or n is None or g <= 0:
        return None, b
    return round(n / g, 3), b


def _stat(fn, arr, mask) -> float | None:
    vals = arr[mask]
    vals = vals[~np.isnan(vals)]
    return None if vals.size == 0 else round(float(fn(vals)), 4)


def observe(site_slug: str, day: date, items: list[Item], geom,
            with_rasters: bool = True) -> tuple[Observation, Rasters | None]:
    resolution_m = resolution_for(site_slug)
    pixel_ha = config.pixel_ha(resolution_m)
    ds = load_day(items, geom, resolution_m)
    inside = rasterize(Geometry(geom, "EPSG:4326"), ds.odc.geobox).values.astype(bool)
    n_site = int(inside.sum())
    site_ha = n_site * pixel_ha

    scl = ds["scl"].values
    nodata = (scl == config.SCL_NODATA) & inside
    covered = inside & ~nodata

    ref = items[0]
    B, G, R, RE, NIR, SWIR = (_reflectance(ds, ref, b)
                              for b in ("blue", "green", "red", "rededge1", "nir", "swir16"))

    # Nube = clase inválida de SCL o píxel muy brillante en el azul (nubes finas que
    # SCL no marca). El agua y el suelo seco quedan muy por debajo de este umbral.
    with np.errstate(invalid="ignore"):
        bright = np.nan_to_num(B) > config.BLUE_CLOUD
    cloud = (np.isin(scl, list(config.SCL_INVALID)) | bright) & inside
    valid = np.isin(scl, list(config.SCL_VALID)) & inside & ~cloud

    coverage = covered.sum() / max(n_site, 1)
    cloud_frac = cloud.sum() / max(covered.sum(), 1)
    valid_frac = valid.sum() / max(n_site, 1)
    mndwi = _nd(G, SWIR)
    ndwi = _nd(G, NIR)
    ndvi = _nd(NIR, R)
    ndti = _nd(R, G)
    ndci = _nd(RE, R)

    mndwi_thr, thr_method = water_threshold(mndwi, valid)
    wet = valid & (mndwi > mndwi_thr)
    water = wet & (ndvi < config.NDVI_OPEN_WATER)
    wet_veg = wet & ~water
    ndwi_water = valid & (ndwi > 0)
    scl_water = inside & (scl == config.SCL_WATER)
    n_water = int(water.sum())

    blue_median = _stat(np.median, B, valid)
    if n_water >= 5:
        ndti_mean = _stat(np.mean, ndti, water)
        ndci_mean = _stat(np.mean, ndci, water)
        ndci_p90 = _stat(lambda v: np.percentile(v, 90), ndci, water)
        bloom_frac = _stat(lambda v: np.mean(v > config.NDCI_BLOOM), ndci, water)
    else:
        ndti_mean = ndci_mean = ndci_p90 = bloom_frac = None

    water_ha = n_water * pixel_ha
    scl_water_ha = int(scl_water.sum()) * pixel_ha
    incoherente = (scl_water_ha >= config.SCL_CHECK_MIN_HA
                   and water_ha < config.SCL_CHECK_RATIO * scl_water_ha)

    # La semilla para el control espectral es la clase agua de la ESA, que es
    # independiente de nuestros índices; si no la hay, se usa el agua propia.
    seed = scl_water & valid
    if seed.sum() * pixel_ha < config.WATER_SPECTRUM_MIN_HA:
        seed = water
    water_nir_green, water_blue = water_spectrum(G, NIR, B, seed, pixel_ha)
    espectro_anomalo = (
        (water_nir_green is not None and water_nir_green > config.WATER_NIR_GREEN_MAX)
        or (water_blue is not None and water_blue < config.WATER_BLUE_FLOOR)
    )

    if coverage < 0.5:
        quality = "sin_datos"
    elif coverage < config.MIN_COVERAGE:
        quality = "parcial"
    elif cloud_frac > config.MAX_CLOUD_FRAC:
        quality = "nublado"
    elif blue_median is not None and blue_median > config.BLUE_HAZE:
        quality = "neblina"
    elif espectro_anomalo:
        quality = "espectro_anomalo"
    elif incoherente:
        quality = "incoherente"
    else:
        quality = "ok"

    obs = Observation(
        site=site_slug, date=day, n_scenes=len(items),
        scenes=";".join(sorted(it.id for it in items)),
        coverage=round(float(coverage), 4), cloud_frac=round(float(cloud_frac), 4),
        valid_frac=round(float(valid_frac), 4),
        blue_median=blue_median if blue_median is not None else float("nan"),
        mndwi_thr=mndwi_thr, thr_method=thr_method,
        water_nir_green=water_nir_green, water_blue=water_blue,
        site_ha=round(site_ha, 1),
        water_ha=round(water_ha, 1),
        water_frac=round(n_water / max(int(valid.sum()), 1), 4),
        wet_veg_ha=round(int(wet_veg.sum()) * pixel_ha, 1),
        ndwi_water_ha=round(int(ndwi_water.sum()) * pixel_ha, 1),
        scl_water_ha=round(scl_water_ha, 1),
        ndti_mean=ndti_mean, ndci_mean=ndci_mean, ndci_p90=ndci_p90, bloom_frac=bloom_frac,
        quality=quality,
    )

    if not with_rasters:
        return obs, None

    rgb = np.dstack([R, G, B])
    rgb = np.clip(np.nan_to_num(rgb) / 0.25, 0, 1)  # estiramiento simple
    ndci_masked = np.where(water, ndci, np.nan)
    rasters = Rasters(rgb=rgb, water=water, wet_veg=wet_veg, invalid=(cloud | nodata),
                      inside=inside, ndci=ndci_masked, geobox=ds.odc.geobox)
    return obs, rasters
