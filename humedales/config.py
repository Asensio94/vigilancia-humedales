from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SITES_DIR = DATA_DIR / "sites"
SERIES_DIR = DATA_DIR / "series"
OUTPUT_DIR = ROOT / "output"
IMG_DIR = OUTPUT_DIR / "img"

for _d in (SITES_DIR, SERIES_DIR, OUTPUT_DIR, IMG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Catálogo STAC público (sin clave) con Sentinel-2 L2A en COG. Histórico desde 2017.
STAC_URL = "https://earth-search.aws.element84.com/v1"
STAC_COLLECTION = "sentinel-2-l2a"

# Límites de espacios protegidos: Natura 2000 (EEA, ArcGIS REST).
NATURA_URL = (
    "https://bio.discomap.eea.europa.eu/arcgis/rest/services/"
    "ProtectedSites/Natura2000Sites/MapServer/0/query"
)

# Sistema de referencia y resolución de trabajo. ETRS89 / UTM 30N cubre toda la
# península (los sitios en huso 29 se reproyectan). 20 m es la resolución nativa
# de SCL, B05 y B11, así que no se inventa detalle.
WORK_CRS = "EPSG:25830"
RESOLUTION_M = 20
PIXEL_HA = (RESOLUTION_M**2) / 10_000  # 0.04 ha por píxel a 20 m

# Bandas Sentinel-2 (nombres Earth Search) → uso
# La banda `cloud` (probabilidad de nube de Sen2Cor) se descartó a propósito: en Earth
# Search apunta a CLD_20m.jp2 en el bucket original `sentinel-s2-l2a`, que no es COG y
# es de pago por peticiones. Leerla multiplicaba por diez el tiempo de carga de Doñana
# y a veces no terminaba. Las nubes finas se detectan con la banda azul (BLUE_CLOUD).
BANDS = ["blue", "green", "red", "rededge1", "nir", "swir16", "scl"]

# Hilos de descarga por proceso. Dask usa por defecto un hilo por CPU (16 aquí), y
# con varios procesos de backfill en marcha eso pasaba de cien peticiones
# simultáneas a S3: el DNS dejaba de resolver y se perdían fechas enteras.
DASK_THREADS = 4

# Clases SCL (Scene Classification Layer)
SCL_NODATA = 0
SCL_INVALID = {1, 3, 8, 9, 10}  # saturado, sombra de nube, nube media, nube alta, cirro
SCL_VALID = {2, 4, 5, 6, 7, 11}  # oscuro, vegetación, suelo, agua, sin clasificar, nieve
SCL_WATER = 6

# Umbrales de calidad de una observación
MAX_CLOUD_FRAC = 0.20      # fracción nubosa dentro del humedal para considerar la fecha
MIN_COVERAGE = 0.95        # fracción del humedal cubierta por las escenas del día
BLUE_CLOUD = 0.22          # reflectancia azul por encima de la cual el píxel se trata como nube
BLUE_HAZE = 0.12           # reflectancia azul mediana del sitio por encima de la cual se asume neblina

# Umbrales de índices
# Control de coherencia entre el agua por índice y la clase agua de ESA. Algunas
# escenas (vistas 2026-07-11 y 2026-07-21 en Tablas de Daimiel, ambas S2C) traen el
# SWIR sistemáticamente más alto y hunden el MNDWI sobre la lámina, que en color
# natural sigue estando ahí. Sin este control la fecha entra como una desecación falsa.
SCL_CHECK_MIN_HA = 50      # solo se comprueba si SCL ve al menos esta agua
SCL_CHECK_RATIO = 0.25     # agua por índice por debajo de esta fracción de la de SCL = incoherente

MNDWI_WATER = 0.0          # píxel húmedo si MNDWI > 0
NDVI_OPEN_WATER = 0.15     # agua libre si además NDVI < este valor; si no, vegetación inundada
# NDCI (Mishra & Mishra 2012): 0.1 ≈ 25 mg/m³ de clorofila-a (eutrófico), 0.2 ≈ 40,
# 0.3 ≈ 57 (hipereutrófico). Muchos humedales someros españoles viven por encima de
# 0.1 de forma habitual, así que el umbral absoluto se pone en 0.2 y las desviaciones
# menores se detectan por comparación con el histórico del propio humedal.
NDCI_BLOOM = 0.20          # NDCI por encima del cual se considera floración algal
NDCI_BLOOM_FRAC = 0.50     # fracción de agua libre con NDCI > NDCI_BLOOM que dispara alerta
