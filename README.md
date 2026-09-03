# Vigilancia satelital de humedales protegidos

Mide cada pocos días, con **Sentinel-2**, la superficie de agua, la turbidez y la clorofila de
humedales protegidos españoles (Doñana, Mar Menor, Tablas de Daimiel, l'Albufera, Fuente de Piedra,
Gallocanta) y dispara **alertas** de desecación o eutrofización comparando cada observación con la
serie histórica del mismo humedal en la misma época del año.

## Estado

Prototipo v0.1 (3 de septiembre de 2026). Funciona de extremo a extremo sin ninguna clave de acceso, y
los **seis humedales tienen ya el histórico completo** de julio de 2017 a septiembre de 2026, cargado
sin una sola fecha perdida por error de red:

| Humedal | fechas | válidas | agua libre 2017 → 2026 (mediana anual, ha) |
|---|---|---|---|
| Tablas de Daimiel | 475 | 259 | 236 → 248, con el fondo en 26 (2023) |
| Mar Menor | 553 | 357 | 13.336 → 13.184, estable |
| l'Albufera de València | 493 | 350 | 9.129 → 9.072, estable |
| Fuente de Piedra | 960 | 420 | 200 → 1.014, muy variable |
| Gallocanta | 889 | 494 | 441 → 811, con el fondo en 237 (2025) |
| Doñana | 598 | 341 | 7.528 → 11.159, creciendo desde 2024 |

Los dos humedales pequeños salen con casi el doble de fechas porque caen en el solape de varias
órbitas. Las cifras de l'Albufera incluyen el arrozal inundado del sitio Natura 2000, no solo la
laguna, que son unas 2.300 ha: para esa laguna la métrica que importa es la del área inundable.

La serie de Tablas de Daimiel reproduce la sequía documentada de La Mancha y su recuperación; mediana
anual de agua libre en hectáreas:

| 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|
| 236 | 241 | 181 | 88 | 60 | 50 | 26 | 85 | 159 | 248 |

2017 arranca en julio y 2026 acaba en septiembre, así que sus medianas no cubren el año entero; con la
misma ventana de meses en todos los años (enero a septiembre) la serie es 258, 249, 190, 90, 65, 53,
52, 85, 170, 248 ha, es decir la misma forma pero con un 2023 menos extremo, porque lo peor de aquella
sequía fue el otoño. Comparar medianas anuales entre años incompletos es una trampa fácil (ver
*Limitaciones*); las alertas no la pisan porque siempre comparan contra la misma época del año.

El fondo de la sequía en 2023 y la recuperación de 2025-2026 coinciden con el calado medido en el
suelo en la marisma de Doñana (máximos anuales de 0,18 m en 2023 y 1,10 m en 2026), que es una fuente
independiente del satélite: ver *Contexto hidrológico*.

Y hay dos controles de que las hectáreas absolutas significan algo, no solo sus variaciones. El
primero es el Mar Menor, cuya lámina permanente no debería moverse: sale entre 12.950 y 13.340 ha de
mediana anual en nueve años, frente a las 13.500 ha que se citan habitualmente para la laguna. El
segundo es la correlación de 0,94 entre el área inundada de Doñana y el calado medido en el suelo en
la marisma, sobre 168 fechas (ver *Contexto hidrológico*).

## Uso

```bash
.venv/Scripts/python.exe -m humedales.cli sites
.venv/Scripts/python.exe -m humedales.cli run --site tablas-daimiel --since 2026-06-01
.venv/Scripts/python.exe -m humedales.cli run                 # todos, solo fechas nuevas
.venv/Scripts/python.exe -m humedales.cli report              # informe desde las series guardadas
.venv/Scripts/python.exe -m humedales.cli backfill            # histórico completo desde 2017
.venv/Scripts/python.exe -m humedales.cli mask                # mide el área inundable de cada humedal
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

Son unas 475-600 fechas por humedal en nueve años, unos 3 s por fecha en los humedales pequeños con
cinco procesos y unos 25 s en Doñana, que necesita 4,5 escenas por fecha. Conviene lanzar **un humedal
a la vez**: cada proceso abre ya varias descargas en paralelo y con dos backfills simultáneos se
saturaba la red (ver más abajo).

Las fechas que fallan por red se reintentan tres veces dentro del proceso hijo y, si aun así fallan,
se registran con la marca `FALLO` y quedan sin guardar: como el backfill es reanudable, basta repetir
el mismo comando para volver a intentarlas.

## Fuentes

| Fuente | Uso | Acceso |
|---|---|---|
| Earth Search v1 (Element 84, AWS) `sentinel-2-l2a` | catálogo STAC y COG de cada banda; histórico desde 2017 | público, sin clave |
| EEA Natura 2000 (ArcGIS REST) | polígono de cada humedal por código de sitio | público |
| ICTS-Doñana Hidromet (`datos-automaticos.icts-donana.es`) | calado diario de la marisma y lluvia, medidos en el suelo | público, CC BY 4.0, 100 peticiones/hora por IP |

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
   humedal, en ETRS89/UTM 30N a 20 m (40 m en Doñana, ver *Resolución por humedal*), y calcula por fecha:
   - cobertura y fracción nubosa dentro del humedal (clases SCL más azul > 0.22),
   - **neblina**: mediana de reflectancia azul de los píxeles válidos > 0.12 descarta la fecha
     (la SCL no detecta calimas finas que inflan el agua detectada x3),
   - **umbral de agua adaptativo**: el corte de MNDWI se calcula en cada fecha con el método de Otsu
     sobre el histograma del propio humedal, en vez de fijarlo en cero (ver *El umbral fijo era el
     problema*),
   - **agua libre**: píxeles válidos con MNDWI por encima de ese umbral y NDVI < 0.15,
   - **vegetación inundada**: MNDWI por encima del umbral y NDVI >= 0.15 (masiega, carrizo, arrozal),
   - turbidez: NDTI = (B04 - B03)/(B04 + B03) medio sobre el agua libre,
   - clorofila: NDCI = (B05 - B04)/(B05 + B04) medio, percentil 90 y fracción con NDCI > 0.20,
   - también NDWI > 0 y la clase agua de SCL, como contraste,
   - **forma del espectro sobre el agua**: cociente infrarrojo/verde y azul mediano sobre una semilla
     de agua, para detectar correcciones atmosféricas fallidas (ver *Cuando la atmósfera se corrige mal*),
   - calidad: `ok`, `nublado` (> 20 % nubes), `neblina`, `espectro_anomalo`, `incoherente` (el agua por
     índice contradice la clase agua de ESA), `parcial` (< 95 % cubierto), `sin_datos`.
4. `store.py`: series CSV por humedal, upsert por fecha.
5. `alerts.py`: el **valor actual** es la mediana de las observaciones `ok` de los últimos 20 días
   (mínimo 2), no la última pasada, para amortiguar el parpadeo entre órbitas. Reglas:
   - **desecación** (alta): agua libre por debajo del percentil 10 de las observaciones de años anteriores
     en ±30 días del mismo día del año (mínimo 5 observaciones de referencia);
   - **descenso brusco** (media): agua libre < 70 % de la mediana de los 45 días previos a la ventana
     actual, **y** además una caída peor que el 90 % de las caídas registradas en esa misma época del
     año (ver *Una laguna que se seca cada verano no es noticia*);
   - **eutrofización**: el **pico** de NDCI de la ventana actual por encima del percentil 90 de los
     picos de esa misma época del año en años anteriores, más un margen de 0,02. La gravedad la gradúa
     el umbral de literatura (0,20): alta si además lo supera, media si no (ver *El umbral de clorofila
     de la literatura no sirve aquí*);
   - **turbidez** (media): NDTI por encima del percentil 90 histórico estacional.
   Las lagunas de agua permanente (Mar Menor, l'Albufera) no generan alertas de superficie.
6. `masks.py`: mide el **área inundable** de cada humedal acumulando el agua detectada en fechas
   limpias de los meses húmedos (diciembre a abril), una por año y mes. Es el denominador con sentido
   hidrológico de la métrica "fracción inundada": el polígono Natura 2000 es administrativo.
7. `hydro.py`: contexto hidrológico medido en el suelo (calado de la marisma y lluvia) desde la API
   de la ICTS-Doñana, para contrastar las alertas con una fuente que no es el satélite.
8. `report.py`: informe HTML autocontenido (imágenes embebidas) con mapa folium; añade un cuarto panel
   con el calado y la lluvia en los humedales que tienen estaciones de campo.
9. `backfill.py`: carga masiva paralela y reanudable del histórico.

## Limitaciones conocidas

- En humedales someros con vegetación emergente (Tablas de Daimiel) el agua libre detectada oscila
  mucho entre pasadas consecutivas (80 → 200 → 26 ha en diez días de agosto de 2026 con imágenes en
  color natural casi idénticas) y la propia clase agua de ESA oscila igual. Es un límite espectral,
  no un error: el agua bajo vegetación está en el filo del umbral MNDWI. El umbral adaptativo y la
  mediana móvil de las alertas lo amortiguan, pero no lo eliminan; para hectáreas absolutas fiables
  haría falta un composite de varias pasadas.
- NDCI y NDTI son proxies; no están calibrados a mg/m³ ni NTU, y sus umbrales de literatura no valen
  en lagunas someras y salinas. Sirven para detectar anomalías,
  no para dar valores absolutos. Las Tablas viven con NDCI ≈ 0.15 de forma habitual en verano.
- Las alertas relativas necesitan histórico: hasta tener varios años de serie solo funcionan las reglas
  absolutas y la de descenso brusco.
- El contexto hidrológico medido en el suelo solo existe en Doñana, y la lluvia solo desde 2022. En el
  resto de humedales las alertas se quedan sin explicación de campo.
- Las correcciones atmosféricas fallidas se detectan, pero no se corrigen: esas fechas se pierden. En
  Tablas de Daimiel son 97 de 475, la mayoría de S2C.
- **Las medianas anuales no son comparables si el año está incompleto.** En el Mar Menor la mediana
  anual de NDCI parecía subir de forma sostenida hasta 2026, y con la misma ventana de meses en todos
  los años la tendencia desaparece: era el otoño que falta en 2026, no clorofila. Tampoco era deriva de
  sensor (la subida aparente salía igual en S2A y en S2B). Cualquier lectura entre años tiene que
  fijar la ventana estacional; las alertas ya lo hacen, la vista de la serie no.

## Siguientes pasos

1. Terminar el histórico de los seis humedales y medir su área inundable (`mask`).
2. Ampliar el catálogo a la lista Ramsar española (76 sitios) y a las ZEPA de humedal.
3. Notificaciones (correo/Telegram) y ejecución programada semanal.
4. Contraste con la capa Global Surface Water del JRC como validación externa del área inundable.
5. Recuperar las fechas de espectro anómalo con una corrección atmosférica propia (DOS o similar)
   en vez de descartarlas.
6. Servicio web con suscripción por humedal, compartiendo infraestructura con el observatorio de alegaciones.

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

### El umbral fijo era el problema

MNDWI > 0 es el criterio de manual, pero el cero no es la orilla: depende de la turbidez, de la
profundidad, del ángulo solar y de cuánta vegetación emerge del agua. Sobre los nueve años de Tablas
de Daimiel el umbral fijo detectaba sistemáticamente menos agua que la clasificación de la ESA
(razón 0,85 en S2A y 0,86 en S2B). Ahora el corte se calcula en cada fecha con el método de Otsu
sobre el histograma de MNDWI del propio humedal, con tres guardas: hacen falta 500 píxeles válidos,
la separación entre las dos poblaciones tiene que explicar el 60 % de la varianza (si el humedal está
seco o inundado del todo no hay dos poblaciones que separar) y el corte tiene que caer entre -0,35 y
0,35. Si alguna falla se vuelve al cero fijo. La concordancia con la ESA pasó a 1,09 en S2A y 1,00 en
S2B, y las medianas anuales quedaron un 15-70 % más altas, con la forma de la sequía más marcada.

### Cuando la atmósfera se corrige mal (y por qué S2C parecía el culpable)

Sentinel-2C, lanzado en septiembre de 2024, detectaba la mitad de agua que la ESA (razón 0,47 frente
a 0,85 de S2A y 0,86 de S2B) y el 42 % de sus fechas se descartaban por incoherencia. Parecía un sesgo
del sensor en el infrarrojo de onda corta, así que el satélite quedó vetado en las alertas. Era una
conclusión equivocada, y dos comprobaciones lo demostraron: el sesgo no venía de la nubosidad (en las
escenas con menos del 2 % de nube S2C seguía dando la razón más baja, y era el satélite con menos
nube y menos neblina de los tres), y medido sobre un núcleo fijo de 240 ha de agua se veía que las
escenas malas de los tres satélites compartían la misma firma.

La firma es física: el agua líquida absorbe con fuerza a partir del rojo, así que sobre agua real el
infrarrojo cercano tiene que quedar por debajo del verde. En las escenas buenas el cociente
infrarrojo/verde vale 0,63-0,67 en los tres satélites; en las malas, 1,17-1,26 en los tres. Un
espectro que sube con el azul hundido no es agua vista mal, es una corrección atmosférica que ha
sobreestimado el aerosol. Es un fallo del procesado de la ESA, mucho más frecuente en S2C, no un
sesgo de calibración.

El control está en `indices.py`: sobre una semilla de agua independiente de nuestros índices (la clase
agua de la ESA, o la propia si no la hay) se mide el cociente infrarrojo/verde y el azul mediano, y la
fecha se marca `espectro_anomalo` si el cociente pasa de 1,10 o el azul baja de 0,002. Con eso el veto
al satélite desaparece (`alerts.EXCLUDE_SATELLITES` está vacío) y las escenas buenas de S2C entran en
las alertas: su concordancia con la ESA es 0,92. En Tablas de Daimiel el cambio movió 97 fechas a
`espectro_anomalo` y bajó las `incoherente` de 41 a 7.

Atacar la causa en vez del síntoma es lo que permitió recuperar el satélite en vez de perderlo.

### El umbral de clorofila de la literatura no sirve aquí

Con las series completas se vio que la alerta de eutrofización, que es la mitad del propósito del
proyecto, **no había disparado ni una vez en 2.221 observaciones**. Dos causas, las dos instructivas.

La primera: el valor que se evaluaba era la mediana de la ventana de veinte días, que se introdujo
para amortiguar el parpadeo de la lámina de agua entre pasadas. Con la clorofila es al revés, porque
una floración algal dura días y una mediana de tres semanas la borra. Por fecha suelta Gallocanta
llega a NDCI 0,514 con el 99 % de su lámina por encima del umbral, y Fuente de Piedra a 0,429; la
mediana de veinte días no pasa de 0,200 en ningún humedal ni una sola vez. Cada variable necesita su
estadístico: mediana para la superficie, pico para la clorofila.

La segunda: el umbral de 0,20 (unos 40 mg/m³ de clorofila-a según Mishra & Mishra 2012) se calibró en
aguas continentales profundas y **no es transferible** a lagunas someras y salinas con fondo claro,
donde el índice está inflado de forma crónica. Usarlo para disparar da todo o nada: con el pico en vez
de la mediana, Gallocanta alertaría en **494 de sus 494 fechas** y Fuente de Piedra en 338 de 420.

La regla que sí funciona compara el pico actual con los **picos** de la misma época del año en años
anteriores. Y aquí hubo un error estadístico propio que conviene no repetir: comparar el máximo de una
ventana de ocho observaciones contra el percentil 95 de observaciones sueltas lo supera por pura
construcción una vez de cada tres (1 - 0,95⁸ = 34 %), y con eso la regla disparaba en el 40-70 % de las
fechas. Hay que comparar el estadístico con la distribución del mismo estadístico. Con los picos
históricos de la época, los avisos bajan al 3-15 % de las fechas y caen donde deben:

| Humedal | años con aviso de eutrofización |
|---|---|
| Mar Menor | 2019, 2020, 2021, 2024 |
| l'Albufera de València | 2019 a 2026, casi todos los años |
| Tablas de Daimiel | 2019 (11 avisos altos), 2020, 2025 |
| Gallocanta | 2020, 2021 (24), 2022, 2024, 2025, 2026 |
| Fuente de Piedra | 2018 a 2024, y 2026 |
| Doñana | 2020, 2025, 2026 |

Los dos años en que salta el Mar Menor son 2019 y 2021, sus dos crisis anóxicas documentadas, y salta
sin necesidad del umbral absoluto: sus aguas son más claras y su NDCI nunca llega a 0,20, pero la
anomalía frente a su propia época del año sí se ve. l'Albufera avisa casi todos los años, lo que es
coherente con una eutrofización crónica, y hoy tiene el único aviso activo del informe (pico 0,182
frente a 0,110 habitual). Gallocanta, en cambio, no avisa pese a su NDCI de 0,231 de septiembre de
2026: allí eso es simplemente septiembre.

### Una laguna que se seca cada verano no es noticia

Al cargar el histórico de los seis humedales apareció el defecto de la regla de descenso brusco: como
solo comparaba con las semanas anteriores, avisaba de la desecación estival de siempre. Con las series
completas disparaba en 100 de las 494 fechas de Gallocanta, y 28 de los 44 disparos de Tablas de
Daimiel eran de agosto. Una alerta que salta cada verano no la lee nadie.

Ahora la caída se compara además con lo que cae la lámina en esa misma época del año en años
anteriores, y solo salta si es peor que el 90 % de ellas. Desde 2022, cuando ya hay histórico con el
que comparar:

| Humedal | disparos antes | ahora | años en que salta |
|---|---|---|---|
| Fuente de Piedra | 9 | 3 | 2026 |
| Gallocanta | 20 | 8 | 2025 |
| Tablas de Daimiel | 19 | 9 | 2022, 2023 |
| Doñana | 9 | 9 | 2023, 2025, 2026 |

Un tercio de los avisos, y concentrados donde deben: Gallocanta salta en 2025, que es su año más seco
de la serie (mediana de 237 ha), y Tablas de Daimiel en 2022 y 2023, el fondo de la sequía de La
Mancha. En Doñana no cambia nada porque sus caídas ya eran atípicas. La alerta que Fuente de Piedra
tenía activa en septiembre de 2026 desaparece: había caído de 1.100 a 330 ha, pero no más deprisa que
en otros agostos.

Los primeros años de cada serie siguen dando avisos que en régimen no darían, porque no hay con qué
comparar; el mensaje de la alerta lo dice cuando le pasa.

### Resolución por humedal

Doñana ocupa 128.000 ha del polígono Natura 2000 a caballo de dos husos UTM, así que cada fecha son
4,5 escenas y unos 500 MB a 20 m: el histórico completo iba camino de casi seis horas, con lecturas
truncadas por saturar el ancho de banda. A 40 m el volumen se divide por cuatro y para láminas de esa
escala no se pierde nada útil (0,16 ha por píxel). En humedales pequeños y fragmentados como las Tablas
la resolución fina sí importa, y ahí se mantienen los 20 m: `config.RESOLUTION_BY_SITE`.

### El área inundable como denominador

"Fracción del sitio" no significa nada cuando el sitio es un límite administrativo: el polígono de
Doñana incluye pinares, arenas y cultivos, y la marisma nunca va a inundar el 100 %. El comando `mask`
acumula el agua detectada (libre y bajo vegetación) en fechas limpias de los meses húmedos, una por
año y mes, y de ahí saca dos superficies: la **inundable**, con agua en alguna fecha, y la
**permanente**, con agua en el 90 % de ellas. El informe usa la inundable como denominador cuando
existe y cae al polígono cuando no, así que la métrica mejora sin recalcular ninguna serie: son
constantes del humedal, no columnas de cada fecha.

### Contexto hidrológico: el calado de la marisma

Las alertas dicen que el agua baja, pero no por qué. La ICTS-Doñana (Estación Biológica de Doñana,
CSIC) publica en abierto el calado diario de la marisma y la lluvia de sus estaciones automáticas, y
`hydro.py` los descarga, los cachea en `data/hydro/` y los pinta como cuarto panel del informe. Es una
medida hecha en el suelo, independiente del satélite, y confirma la serie: máximos anuales de calado
de 0,24 m en 2022, 0,18 en 2023, 0,38 en 2024, 1,00 en 2025 y 1,10 m en 2026, es decir el mismo fondo
de sequía en 2023 y la misma recuperación que ve Sentinel-2.

**La validación cruzada sale bien.** Sobre las 168 fechas en que hay a la vez observación válida de
Sentinel-2 y calado medido en la marisma (2022-2026), la correlación entre el área inundada total
(agua libre más vegetación inundada) y el calado es de 0,94 (Pearson; 0,78 de Spearman). Y la relación
es monótona por tramos de calado, que es lo que de verdad importa para una alerta:

| Calado medido en la marisma | Agua libre (ha) | Área inundada (ha) | fechas |
|---|---|---|---|
| menos de 5 cm | 8.058 | 8.386 | 73 |
| 5 a 20 cm | 8.999 | 9.835 | 53 |
| 20 a 50 cm | 10.444 | 12.812 | 24 |
| más de 50 cm | 18.085 | 28.413 | 18 |

Que con la marisma casi seca el satélite siga viendo 8.000 ha no es un error: el polígono incluye
lucios permanentes, salinas y el estuario del Guadalquivir, mientras la estación mide en un punto de
la marisma. Lo que valida el método es que la señal suba con el calado, y que la vegetación inundada
sea la que más se mueve, porque es la parte de la marisma que se encharca y se seca.

Tres cosas que costaron encontrar:

- **La lluvia acumulada necesita otro método de agregación.** Con `Average` la serie vuelve vacía; hay
  que pedir `Totalize` en `calc_procedure_method` y en `aggr_method`.
- **Cada estación tiene dos sensores de nivel con referencias distintas.** El Mestech da altura sobre
  el datum (13,19-14,8 m, con años enteros sin datos) y el Mobrey da calado sobre el fondo (0-1,35 m,
  casi completo). `choose_instrument` elige por cobertura real, no por nombre, y guarda la elección en
  `data/hydro/instruments.json` para no repetir el cálculo.
- **El portal admite 100 peticiones por hora y dirección.** Al agotarlo devuelve HTTP 429, así que
  `series` cae a lo que haya en disco y marca el resultado como viejo en vez de romper el informe.
  Cada descarga pide solo desde el día siguiente al último guardado.

Los piezómetros públicos no sirven todavía: la red Almonte-Marismas de la Confederación del
Guadalquivir tiene 195 puntos oficiales pero solo visor, el catálogo de la Mancha Occidental está en
construcción y el anuario de aforos nacional solo se descarga a mano.

### El caso de las escenas incoherentes

El 11 y el 21 de julio de 2026 en Tablas de Daimiel el MNDWI dio cero hectáreas de agua entre fechas
con 150 y 190 ha, mientras la imagen en color natural mostraba la misma lámina oscura y la clasificación
de ESA seguía marcando unas 85 ha de agua. Fue el hilo del que salieron el umbral adaptativo y el
control espectral: las dos escenas son de S2C y traen el infrarrojo de onda corta alto (mediana 0.271
frente a 0.242 el día 16), pero la causa no era el sensor sino la corrección atmosférica. Hoy esas dos
fechas se descartan por `espectro_anomalo`, que nombra el motivo real, y el resto de fechas de S2C
cuentan con normalidad.
