# Vigilancia satelital de humedales protegidos

Mide cada pocos días, con **Sentinel-2**, la superficie de agua, la turbidez y la clorofila de
humedales protegidos españoles (Doñana, Mar Menor, Tablas de Daimiel, l'Albufera, Fuente de Piedra,
Gallocanta) y dispara **alertas** de desecación o eutrofización comparando cada observación con la
serie histórica del mismo humedal en la misma época del año.

## Estado

Prototipo v0.1 (2 de septiembre de 2026). Funciona de extremo a extremo sin ninguna clave de acceso.
Serie histórica completa de Tablas de Daimiel: 475 fechas entre julio de 2017 y septiembre de 2026,
322 válidas. Reproduce la sequía documentada de La Mancha; mediana anual de agua libre en hectáreas:

| 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| 225 | 207 | 86 | 37 | 41 | 26 | 16 | 34 | 72 | 156 |

El resto de humedales está en carga (`backfill`).

## Uso

```bash
.venv/Scripts/python.exe -m humedales.cli sites
.venv/Scripts/python.exe -m humedales.cli run --site tablas-daimiel --since 2026-06-01
.venv/Scripts/python.exe -m humedales.cli run                 # todos, solo fechas nuevas
.venv/Scripts/python.exe -m humedales.cli report              # informe desde las series guardadas
.venv/Scripts/python.exe -m humedales.cli backfill            # histórico completo desde 2017
```

Genera `output/informe_<fecha>.html` (resumen, alertas, gráficas de serie, imagen de la última fecha,
mapa) y `output/alertas_<fecha>.json`. Las series viven en `data/series/<humedal>.csv`, una fila por fecha,
y se amplían de forma incremental: cada ejecución solo procesa las fechas que faltan.

### Backfill del histórico

`backfill` construye la referencia histórica desde julio de 2017, que es cuando empieza Sentinel-2 L2A
en el catálogo. Reparte las fechas entre varios procesos (la descarga desde S3 es el cuello de botella,
no el cálculo), guarda cada doce fechas y omite las que ya están en el CSV, así que es **reanudable**:
si se interrumpe, se repite el mismo comando y continúa donde estaba.

```bash
# Doñana aparte, con menos procesos: sus mosaicos son de 3.000 x 2.800 px por banda
.venv/Scripts/python.exe -m humedales.cli backfill -s donana --workers 4
.venv/Scripts/python.exe -m humedales.cli backfill -s tablas-daimiel -s mar-menor --workers 5
```

Son unas 475-600 fechas por humedal en nueve años, y unos 10 s por fecha en Doñana con cuatro
procesos. Conviene lanzar **un humedal a la vez**: cada proceso abre ya varias descargas en paralelo
y con dos backfills simultáneos se saturaba la red (ver más abajo).

Las fechas que fallan por red se reintentan tres veces dentro del proceso hijo y, si aun así fallan,
se registran con la marca `FALLO` y quedan sin guardar: como el backfill es reanudable, basta repetir
el mismo comando para volver a intentarlas.

## Fuentes

| Fuente | Uso | Acceso |
|---|---|---|
| Earth Search v1 (Element 84, AWS) `sentinel-2-l2a` | catálogo STAC y COG de cada banda; histórico desde 2017 | público, sin clave |
| EEA Natura 2000 (ArcGIS REST) | polígono de cada humedal por código de sitio | público |

Alternativas comprobadas: Microsoft Planetary Computer sirve el mismo producto (STAC público); Copernicus
Data Space exige registro. El WFS de Ramsar (`rsis.ramsar.org/geoserver`) tiene un esquema no estándar
y MITECO solo expone WMS para el Inventario de Zonas Húmedas, por eso los límites salen de Natura 2000.

**Ojo con el offset radiométrico.** Desde la baseline 04.00 (enero 2022) ESA añade -1000 DN a los
productos L2A. Earth Search ya lo aplica dentro de sus COG y lo indica con la propiedad
`earthsearch:boa_offset_applied`, aunque `raster:bands` siga declarando `offset: -0.1`. Restarlo otra
vez deja la mitad del humedal con reflectancia negativa y arruina todos los índices (fue el primer
error del prototipo).

## Pipeline

1. `sites.py`: catálogo de humedales con sus códigos Natura 2000; descarga y cachea la geometría.
2. `stac.py`: busca escenas por bbox y fecha, agrupa por día solar, decide escala y offset por escena.
3. `indices.py`: carga con `odc-stac` las bandas B02, B03, B04, B05, B08, B11 y SCL recortadas al
   humedal, en ETRS89/UTM 30N a 20 m, y calcula por fecha:
   - cobertura y fracción nubosa dentro del humedal (clases SCL más azul > 0.22),
   - **neblina**: mediana de reflectancia azul de los píxeles válidos > 0.12 descarta la fecha
     (la SCL no detecta calimas finas que inflan el agua detectada x3),
   - **agua libre**: píxeles válidos con MNDWI > 0 y NDVI < 0.15,
   - **vegetación inundada**: MNDWI > 0 y NDVI >= 0.15 (masiega, carrizo, arrozal encharcado),
   - turbidez: NDTI = (B04 - B03)/(B04 + B03) medio sobre el agua libre,
   - clorofila: NDCI = (B05 - B04)/(B05 + B04) medio, percentil 90 y fracción con NDCI > 0.20,
   - también NDWI > 0 y la clase agua de SCL, como contraste,
   - calidad: `ok`, `nublado` (> 20 % nubes), `neblina`, `incoherente` (el agua por índice contradice
     la clase agua de ESA; ver limitaciones), `parcial` (< 95 % cubierto), `sin_datos`.
4. `store.py`: series CSV por humedal, upsert por fecha.
5. `alerts.py`: el **valor actual** es la mediana de las observaciones `ok` de los últimos 20 días
   (mínimo 2), no la última pasada, para amortiguar el parpadeo entre órbitas. Reglas:
   - **desecación** (alta): agua libre por debajo del percentil 10 de las observaciones de años anteriores
     en ±30 días del mismo día del año (mínimo 5 observaciones de referencia);
   - **descenso brusco** (media): agua libre < 70 % de la mediana de los 45 días previos a la ventana actual;
   - **eutrofización** (alta): NDCI medio > 0.20 (unos 40 mg/m³ de clorofila-a según Mishra & Mishra 2012)
     o > 50 % del agua libre con NDCI > 0.20; (media): NDCI por encima del percentil 90 histórico estacional;
   - **turbidez** (media): NDTI por encima del percentil 90 histórico estacional.
   Las lagunas de agua permanente (Mar Menor, l'Albufera) no generan alertas de superficie.
6. `report.py`: informe HTML autocontenido (imágenes embebidas) con mapa folium.
7. `backfill.py`: carga masiva paralela y reanudable del histórico.

## Limitaciones conocidas

- En humedales someros con vegetación emergente (Tablas de Daimiel) el agua libre detectada oscila
  mucho entre pasadas consecutivas (80 → 200 → 26 ha en diez días de agosto de 2026 con imágenes en
  color natural casi idénticas) y la propia clase agua de ESA oscila igual. Es un límite espectral,
  no un error: el agua bajo vegetación está en el filo del umbral MNDWI. La mediana móvil de las alertas
  lo amortigua; para hectáreas absolutas fiables hará falta un umbral por humedal (Otsu) o un composite.
- NDCI y NDTI son proxies; no están calibrados a mg/m³ ni NTU. Sirven para detectar anomalías,
  no para dar valores absolutos. Las Tablas viven con NDCI ≈ 0.15 de forma habitual en verano.
- Las alertas relativas necesitan histórico: hasta tener varios años de serie solo funcionan las reglas
  absolutas y la de descenso brusco.
- Polígono = sitio Natura 2000 completo. En Doñana incluye pinares y arenas; la métrica "fracción del
  sitio" pierde sentido y sería mejor recortar a la marisma.

## Siguientes pasos

1. Calibrar S2C contra S2A/S2B (desplazamiento de B11 o umbral MNDWI propio) para recuperar un tercio
   de las observaciones desde finales de 2024, que hoy no cuentan para las alertas.
2. Máscaras de trabajo por humedal (marisma de Doñana, lámina del Mar Menor sin islas) en `data/sites/`.
3. Umbral de agua adaptativo (Otsu) y contraste con la capa Global Surface Water del JRC.
4. Contexto hidrológico: piezómetros de Doñana (CHG/IGME) y aforos SAIH para explicar las alertas.
5. Ampliar el catálogo a la lista Ramsar española (76 sitios) y a las ZEPA de humedal.
6. Notificaciones (correo/Telegram) y ejecución programada semanal.
7. Servicio web con suscripción por humedal, compartiendo infraestructura con el observatorio de alegaciones.

### La banda de probabilidad de nube no se puede usar

Earth Search expone un asset `cloud` con la probabilidad de nube de Sen2Cor, pero su URL apunta a
`CLD_20m.jp2` dentro del bucket original `sentinel-s2-l2a`: no es un COG, hay que leer el fichero
entero y ese bucket cobra por petición. Incluirla multiplicaba por diez el tiempo de carga de Doñana
y en una prueba no terminó en diez minutos. Se descartó. Las nubes finas que SCL no marca se detectan
ahora con la propia banda azul: píxel con reflectancia azul > 0.22 se trata como nube, y si la mediana
del humedal pasa de 0.12 la fecha entera se descarta por neblina.

La otra optimización que cambió el orden de magnitud fue cargar con dask (`chunks`) en vez de
secuencialmente: los COG se descargan en paralelo y Doñana pasó de 185 a 35 segundos por fecha.

### Cuidado con la concurrencia: la red es el límite

Dask abre por defecto un hilo por CPU (dieciséis en esta máquina). Con dos backfills simultáneos y
nueve procesos entre ambos, eso pasaba de cien lecturas abiertas contra S3 a la vez, y el sistema
empezaba a devolver `CURL error: Could not resolve host`, `WarpOperationError` y JPEG2000 truncados:
más de trescientas lecturas fallidas y cientos de fechas perdidas, sin ganar velocidad (Doñana bajó
solo de 33 a 31,7 s por fecha con cuatro procesos). Ahora `config.DASK_THREADS` limita los hilos por
proceso a cuatro y el paralelismo real es el número de procesos.

### Sentinel-2C queda fuera de las alertas

Al completar los nueve años de Tablas de Daimiel se vio que el sesgo del 11 y 21 de julio no era
anecdótico, sino sistemático del satélite más nuevo. Por satélite, sobre esa serie:

| Satélite | fechas descartadas por incoherencia | razón agua-índice / agua-ESA |
|---|---|---|
| S2A | 8 % | 0,84 |
| S2B | 3 % | 0,78 |
| S2C | 42 % | 0,47 |

S2C, lanzado en septiembre de 2024, da un infrarrojo de onda corta sistemáticamente más alto, lo que
hunde el MNDWI y hace desaparecer la mitad del agua. Mezclarlo con S2A y S2B produciría desecaciones
falsas, así que `alerts.EXCLUDE_SATELLITES` lo aparta del cálculo hasta calibrar una corrección. Las
fechas siguen en el CSV, solo no puntúan para las alertas.

### El caso de las escenas incoherentes

El 11 y el 21 de julio de 2026 en Tablas de Daimiel el MNDWI dio cero hectáreas de agua entre fechas
con 150 y 190 ha, mientras la imagen en color natural mostraba la misma lámina oscura y la clasificación
de ESA seguía marcando unas 85 ha de agua. Las dos escenas son del satélite S2C y traen el infrarrojo
de onda corta (B11) más alto (mediana 0.271 frente a 0.242 el día 16), lo que hunde el índice por debajo
del umbral. Hasta aclarar la causa, esas fechas se marcan `incoherente` y no entran en las alertas:
un cero falso se leería como una desecación total.
