# Vigilancia satelital de humedales protegidos

Mide cada pocos días, con **Sentinel-2**, la superficie de agua, la turbidez y la clorofila de
humedales protegidos españoles (Doñana, Mar Menor, Tablas de Daimiel, l'Albufera, Fuente de Piedra,
Gallocanta) y dispara **alertas** de desecación o eutrofización comparando cada observación con la
serie histórica del mismo humedal en la misma época del año.

## Estado

Prototipo v0.1 (2 de septiembre de 2026). Funciona de extremo a extremo sin ninguna clave de acceso.
Series cargadas: Tablas de Daimiel (jul-sep 2026), Mar Menor (ago 2026), Doñana (finales de ago 2026).

## Uso

```bash
.venv/Scripts/python.exe -m humedales.cli sites
.venv/Scripts/python.exe -m humedales.cli run --site tablas-daimiel --since 2026-06-01
.venv/Scripts/python.exe -m humedales.cli run                 # todos, solo fechas nuevas
.venv/Scripts/python.exe -m humedales.cli report              # informe desde las series guardadas
```

Genera `output/informe_<fecha>.html` (resumen, alertas, gráficas de serie, imagen de la última fecha,
mapa) y `output/alertas_<fecha>.json`. Las series viven en `data/series/<humedal>.csv`, una fila por fecha,
y se amplían de forma incremental: cada ejecución solo procesa las fechas que faltan.

Para construir la referencia histórica basta con `run --since 2017-07-01` (Sentinel-2 L2A disponible
desde mediados de 2017). Coste aproximado: 10-20 s por fecha en un humedal pequeño o mediano
(Tablas, Mar Menor); Doñana tarda más porque abarca cuatro teselas.

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
3. `indices.py`: carga con `odc-stac` las bandas B02, B03, B04, B05, B08, B11, SCL y probabilidad de
   nube recortadas al humedal, en ETRS89/UTM 30N a 20 m, y calcula por fecha:
   - cobertura y fracción nubosa dentro del humedal (clases SCL + probabilidad de nube > 30 %),
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

1. Backfill 2017-2026 de los seis humedales para tener referencia histórica (ejecución larga, una vez).
2. Máscaras de trabajo por humedal (marisma de Doñana, lámina del Mar Menor sin islas) en `data/sites/`.
3. Umbral de agua adaptativo (Otsu) y contraste con la capa Global Surface Water del JRC.
4. Contexto hidrológico: piezómetros de Doñana (CHG/IGME) y aforos SAIH para explicar las alertas.
5. Ampliar el catálogo a la lista Ramsar española (76 sitios) y a las ZEPA de humedal.
6. Notificaciones (correo/Telegram) y ejecución programada semanal.
7. Servicio web con suscripción por humedal, compartiendo infraestructura con el observatorio de alegaciones.

### El caso de las escenas incoherentes

El 11 y el 21 de julio de 2026 en Tablas de Daimiel el MNDWI dio cero hectáreas de agua entre fechas
con 150 y 190 ha, mientras la imagen en color natural mostraba la misma lámina oscura y la clasificación
de ESA seguía marcando unas 85 ha de agua. Las dos escenas son del satélite S2C y traen el infrarrojo
de onda corta (B11) más alto (mediana 0.271 frente a 0.242 el día 16), lo que hunde el índice por debajo
del umbral. Hasta aclarar la causa, esas fechas se marcan `incoherente` y no entran en las alertas:
un cero falso se leería como una desecación total.
