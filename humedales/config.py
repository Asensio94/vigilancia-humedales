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

# Control espectral del agua. El agua líquida absorbe con fuerza a partir del rojo,
# así que sobre agua real el infrarrojo cercano queda por debajo del verde y el
# espectro se apaga hacia longitudes de onda largas. Cuando la corrección atmosférica
# sobreestima el aerosol pasa lo contrario: resta de más en el azul, hasta hundirlo a
# cero, e infla el infrarrojo, con lo que el espectro del agua sube en vez de bajar.
# Sobre tierra seca esas escenas coinciden con las buenas, porque el término que se
# resta de más es despreciable frente a una reflectancia alta; el fallo solo se ve
# sobre objetivos oscuros. Medido en Tablas de Daimiel sobre un núcleo fijo de 240 ha:
# escenas buenas nir/verde 0,66-0,83, escenas falladas 1,60 y 2,74.
WATER_SPECTRUM_MIN_HA = 20   # hectáreas mínimas de semilla de agua para poder comprobarlo
WATER_NIR_GREEN_MAX = 1.10   # nir/verde sobre el agua por encima de esto = espectro no acuático
WATER_BLUE_FLOOR = 0.002     # azul mediano sobre el agua por debajo = corrección atmosférica fallida

MNDWI_WATER = 0.0          # umbral de reserva cuando el histograma no permite calcularlo

# Umbral de agua adaptativo (Otsu). El umbral fijo daba por bueno que todos los
# sensores y todas las atmósferas partieran el histograma en el mismo punto, y no
# es así: el infrarrojo de onda corta de Sentinel-2C sale más alto y hunde el
# índice de agua por debajo de cero sobre láminas perfectamente visibles. Otsu
# busca el corte que mejor separa las dos modas del histograma de cada escena.
OTSU_BINS = 256
OTSU_MIN_PIXELS = 500      # con menos píxeles válidos el histograma no es fiable
OTSU_MIN_SEPARABILITY = 0.60   # varianza entre clases / varianza total; por debajo, no hay dos modas
OTSU_THR_MIN = -0.35       # fuera de esta banda el corte no puede ser la orilla
OTSU_THR_MAX = 0.35          # píxel húmedo si MNDWI > 0
NDVI_OPEN_WATER = 0.15     # agua libre si además NDVI < este valor; si no, vegetación inundada
# NDCI (Mishra & Mishra 2012): 0.1 ≈ 25 mg/m³ de clorofila-a (eutrófico), 0.2 ≈ 40,
# 0.3 ≈ 57 (hipereutrófico). Muchos humedales someros españoles viven por encima de
# 0.1 de forma habitual, así que el umbral absoluto se pone en 0.2 y las desviaciones
# menores se detectan por comparación con el histórico del propio humedal.
NDCI_BLOOM = 0.20          # NDCI por encima del cual se considera floración algal
NDCI_BLOOM_FRAC = 0.50     # fracción de agua libre con NDCI > NDCI_BLOOM que dispara alerta
