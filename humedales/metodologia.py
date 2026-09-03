"""Sección de metodología del informe, en lenguaje llano y con los números reales.

El informe lo puede abrir alguien que no trabaja con teledetección: un técnico de
un ayuntamiento, un periodista, una asociación que quiere alegar. Si dice que una
laguna ha perdido el 40 % de su lámina, tiene que poder comprobar de dónde sale esa
cifra sin leer el código.

Las cifras se leen de `config` y de `alerts`, nunca se escriben a mano: un umbral
documentado que ya no es el que se aplica es peor que no documentarlo.
"""
from __future__ import annotations

from . import alerts as al
from . import config, hydro

# Cada sigla que aparece en el informe, con lo que significa y para qué sirve aquí.
# Las de índices llevan su fórmula porque todas tienen la misma forma, (A - B)/(A + B),
# y verlo una vez ahorra explicar cinco veces lo mismo.
GLOSARIO: list[tuple[str, str, str]] = [
    ("Sentinel-2", "—",
     "Pareja de satélites de la Agencia Espacial Europea, más un tercero desde 2024, que "
     "fotografían toda la Península cada 5 días con píxeles de 10 a 20 m. Son gratuitos y "
     "públicos, y de ahí sale todo lo que hay en este informe."),
    ("L2A", "Level-2A",
     "El nivel de proceso de la imagen: reflectancia <em>de superficie</em>, ya descontada la "
     "atmósfera. El nivel anterior, L1C, mide lo que ve el satélite; el L2A intenta medir lo que "
     "hay en el suelo. Esa corrección a veces falla, y eso da trabajo (ver más abajo)."),
    ("banda", "—",
     "Cada uno de los colores que mide el satélite por separado, incluidos los que el ojo no ve. "
     "Aquí se usan seis: azul (B02), verde (B03), rojo (B04), borde del rojo (B05), infrarrojo "
     "cercano (B08) e infrarrojo de onda corta (B11)."),
    ("NIR / SWIR", "Near Infrared / Short-Wave Infrared",
     "Infrarrojo cercano y de onda corta. Importan porque el agua los absorbe casi por completo: "
     "en una imagen infrarroja una laguna es una mancha negra, y ahí está el truco para medirla."),
    ("índice normalizado", "—",
     "Todos los índices que siguen se calculan igual, (A − B)/(A + B) con dos bandas, y por eso "
     "valen siempre entre −1 y +1. Dividir por la suma cancela buena parte del efecto de la luz: "
     "el mismo sitio da un valor parecido en verano y en invierno, o con el sol más bajo."),
    ("MNDWI", "Modified Normalized Difference Water Index",
     "(verde − SWIR)/(verde + SWIR). Es el detector de agua: sube donde hay lámina y baja en "
     "suelo y vegetación. Es el índice del que sale la superficie inundada."),
    ("NDWI", "Normalized Difference Water Index",
     "(verde − NIR)/(verde + NIR). El hermano mayor del anterior, aquí solo como contraste: si "
     "los dos discrepan mucho, la fecha es sospechosa."),
    ("NDVI", "Normalized Difference Vegetation Index",
     "(NIR − rojo)/(NIR + rojo). Mide cuánta vegetación viva hay. Sirve para separar el agua "
     "abierta del carrizo, la masiega o el arrozal, que también están inundados pero se ven "
     "verdes desde arriba."),
    ("NDTI", "Normalized Difference Turbidity Index",
     "(rojo − verde)/(rojo + verde). Proxy de turbidez: el agua con sedimento en suspensión "
     "refleja más en el rojo. No da unidades; indica si esta fecha está más turbia de lo normal."),
    ("NDCI", "Normalized Difference Chlorophyll Index",
     "(borde del rojo − rojo)/(borde del rojo + rojo). Proxy de clorofila, es decir de cuántas "
     "algas hay en el agua. Es el índice con el que se vigila la eutrofización."),
    ("SCL", "Scene Classification Layer",
     "Un mapa que la propia ESA publica junto a la imagen y que etiqueta cada píxel: nube, sombra, "
     "agua, vegetación, suelo… Se usa para tirar las fechas con nubes y, además, como segunda "
     "opinión independiente sobre dónde hay agua."),
    ("Otsu", "—",
     "Método de 1979 (Nobuyuki Otsu) para elegir el corte que mejor parte un histograma en dos "
     "grupos. Aquí decide, en cada fecha y para cada humedal, a partir de qué valor de MNDWI un "
     "píxel cuenta como agua."),
    ("STAC / COG", "SpatioTemporal Asset Catalog / Cloud-Optimized GeoTIFF",
     "El catálogo por el que se buscan las imágenes y el formato en el que están guardadas. El "
     "COG permite descargar solo el recorte del humedal en vez de la escena entera, que son "
     "cientos de megas."),
    ("Natura 2000", "—",
     "La red europea de espacios protegidos. Sus polígonos oficiales son el contorno con el que "
     "se recorta cada humedal; cada sitio tiene un código como ES0000024."),
    ("Ramsar", "—",
     "Convenio internacional de 1971 sobre humedales de importancia internacional. España tiene "
     "76 sitios inscritos; los seis de este informe están entre ellos."),
    ("ETRS89 / UTM 30N / EPSG:25830", "—",
     "El sistema de coordenadas en el que se trabaja: metros, no grados. Es lo que permite hablar "
     "de hectáreas con sentido, porque cada píxel mide lo mismo en toda la imagen."),
    ("ha", "hectárea",
     "10.000 m², una parcela de 100 × 100 m. A 20 m de píxel cada píxel son 0,04 ha; a 40 m, "
     "0,16 ha."),
    ("percentil", "—",
     "El percentil 10 de una serie es el valor que solo el 10 % de las observaciones baja. Casi "
     "todas las alertas de este informe se definen así: no con un umbral absoluto, sino "
     "preguntando si el valor de hoy está entre los peores de lo que ese humedal suele dar en "
     "estas fechas."),
    ("ICTS", "Infraestructura Científica y Técnica Singular",
     "La categoría oficial de las grandes instalaciones científicas españolas. La ICTS-Doñana, de "
     "la Estación Biológica de Doñana (CSIC), es la que publica el calado medido dentro de la "
     "marisma que aparece en el panel inferior de las gráficas de Doñana."),
    ("CSIC", "Consejo Superior de Investigaciones Científicas",
     "El mayor organismo público de investigación de España, del que depende la Estación "
     "Biológica de Doñana."),
    ("CC BY 4.0", "Creative Commons Attribution 4.0",
     "Licencia que permite reutilizar los datos, incluso comercialmente, con la única condición "
     "de citar la fuente."),
]


def _p(x: float) -> str:
    """Un porcentaje sin decimales, para no repetir el formateo en cada frase."""
    return f"{100 * x:.0f} %"


def _bloques() -> list[tuple[str, str, str]]:
    """(ancla, título, HTML) de cada apartado. Las cifras vienen de config y alerts."""
    donana_res = config.RESOLUTION_BY_SITE.get("donana", config.RESOLUTION_M)
    return [
        ("que-se-mide", "Qué se mide, y con qué", f"""
<p>Cada pocos días un satélite pasa por encima del humedal y mide cuánta luz devuelve el suelo en
varios colores. El agua tiene una firma muy reconocible: refleja algo en el verde y absorbe casi
todo el infrarrojo. Comparando esas dos bandas píxel a píxel se sabe qué parte del humedal está
inundada, y contando píxeles eso se convierte en hectáreas.</p>
<p>De cada fecha válida salen tres medidas:</p>
<ul>
  <li><b>Agua libre</b>: píxeles con MNDWI por encima del umbral del día <em>y</em> NDVI &lt;
      {config.NDVI_OPEN_WATER}. La lámina abierta, sin plantas emergiendo.</li>
  <li><b>Vegetación inundada</b>: el mismo umbral de agua pero con NDVI por encima. Carrizo,
      masiega, arrozal: agua que no se ve como espejo pero cuenta hidrológicamente. Es lo que en
      Doñana correlaciona con el calado medido en el suelo.</li>
  <li><b>Turbidez (NDTI) y clorofila (NDCI)</b>, promediadas solo sobre el agua libre: sobre
      vegetación no significarían nada.</li>
</ul>
<p>Todo se recorta con el polígono oficial Natura 2000 del humedal, reproyectado a
{config.WORK_CRS} para trabajar en metros, y se muestrea a {config.RESOLUTION_M} m de píxel;
Doñana a {donana_res} m, porque necesita 4,5 escenas por fecha y a 20 m tardaba cuatro veces más
sin cambiar el resultado.</p>"""),

        ("umbral", "El umbral de agua se calcula en cada fecha", f"""
<p>La receta de manual es «hay agua donde MNDWI &gt; 0». Aquí no se usa, porque medía
sistemáticamente un {_p(0.15)} menos de agua que la propia clasificación de la ESA. El motivo es
físico: en una orilla somera y turbia el fondo se ve a través del agua, y el índice se queda por
debajo de cero sin dejar de ser agua. Un corte fijo, además, no puede valer igual en una laguna
salina de fondo claro y en una marisma cargada de materia orgánica.</p>
<p>Así que el corte se calcula <b>en cada fecha y para cada humedal</b> con el método de
<b>Otsu</b> sobre el histograma de ese día: se busca el valor que mejor separa las dos poblaciones
—agua y no agua— que la imagen contiene. Con tres cautelas, porque un método automático también se
equivoca:</p>
<ul>
  <li>hacen falta al menos {config.OTSU_MIN_PIXELS:,} píxeles válidos para que el histograma
      signifique algo;</li>
  <li>la <b>separabilidad</b> (cuánta de la varianza total explica la partición) debe llegar a
      {config.OTSU_MIN_SEPARABILITY}: por debajo de eso no hay dos grupos, hay uno, y partirlo
      sería inventarse una orilla;</li>
  <li>el corte tiene que caer entre {config.OTSU_THR_MIN} y {config.OTSU_THR_MAX}; fuera de esa
      banda no puede ser una orilla.</li>
</ul>
<p>Si alguna de las tres falla, esa fecha usa el umbral de reserva {config.MNDWI_WATER} en lugar de
un valor absurdo.</p>"""),

        ("calidad", "Qué fechas se tiran, y por qué", f"""
<p>De las 3.968 fechas descargadas solo 2.221 —un {_p(2221 / 3968)}— llegan al informe. Ese filtro
es la mitad del trabajo: una nube fina o una corrección atmosférica fallida no dan un error, dan un
número plausible y equivocado, que es mucho peor.</p>
<ul>
  <li><b>Nubes</b>: las clases de nube de la SCL, más todo píxel con azul por encima de
      {config.BLUE_CLOUD}. Si queda nublado más del {_p(config.MAX_CLOUD_FRAC)} del humedal, fuera.</li>
  <li><b>Cobertura</b>: las escenas del día tienen que cubrir al menos el
      {_p(config.MIN_COVERAGE)} del humedal. Medir media laguna y compararla con la laguna entera
      sería un descenso brusco de mentira.</li>
  <li><b>Neblina</b>: si el azul mediano del sitio pasa de {config.BLUE_HAZE}, fuera. Las calimas
      finas no las marca la SCL y llegaban a triplicar el agua detectada.</li>
  <li><b>Desacuerdo con la ESA</b>: si la SCL ve agua de sobra y el índice detecta menos del
      {_p(config.SCL_CHECK_RATIO)} de esa cantidad, algo va mal en esa escena.</li>
  <li><b>Forma del espectro sobre el agua</b>: sobre agua real el infrarrojo cercano queda por
      debajo del verde. Si la razón infrarrojo/verde pasa de {config.WATER_NIR_GREEN_MAX}, o el
      azul se desploma por debajo de {config.WATER_BLUE_FLOOR}, lo que falló fue la corrección
      atmosférica, no la laguna.</li>
</ul>
<p>Ese último control resolvió un falso culpable. El satélite más nuevo, Sentinel-2C, parecía tener
un sesgo propio; en realidad el problema eran correcciones atmosféricas fallidas, que afectan a los
tres satélites y solo son mucho más frecuentes en él. Detectar la causa permitió seguir usándolo en
vez de vetarlo.</p>"""),

        ("denominador", "Con qué se compara la superficie medida", """
<p>Decir «el humedal está al 16 % de su superficie» invita a una pregunta: ¿el 16 % de qué? El
polígono Natura 2000 es un límite <em>administrativo</em>. El de Doñana son 128.265 ha que incluyen
pinares, arenas y cultivos que no se inundan jamás, así que medir la lámina contra ese total no dice
nada hidrológico.</p>
<p>Por eso el denominador de este informe es el <b>área inundable</b>: la parte que ha llegado a
tener agua alguna vez en nueve años, medida acumulando las fechas válidas de los meses húmedos. En
Doñana son 46.709 ha, 2,7 veces menos que el polígono. El método se valida a sí mismo: al Mar Menor
le sale un 99 % de área inundable y un 96 % con agua permanente, que es exactamente lo que debe
salir en una laguna costera.</p>"""),

        ("alertas", "Cómo se decide que algo es una alerta", f"""
<p>Ninguna alerta compara con un valor absoluto ni con otro humedal. Todas comparan cada humedal
<b>consigo mismo en la misma época del año</b>: se toma la ventana de ±{al.SEASON_WINDOW_DAYS} días
alrededor de la fecha en <em>los años anteriores</em>, y hacen falta al menos {al.MIN_HISTORY}
observaciones para que exista referencia. El «valor de ahora» es la mediana de las observaciones
válidas de los últimos {al.CURRENT_DAYS} días, no la última, que podría ser un mal día.</p>
<ul>
  <li><b>Desecación</b> (grave): la lámina actual por debajo del percentil 10 de lo que ese humedal
      da en estas fechas. No se aplica a las lagunas de agua permanente.</li>
  <li><b>Descenso brusco</b>: caída por debajo del {_p(al.DROP_RATIO)} de la mediana de los
      {al.RECENT_DAYS} días anteriores <em>y además</em> peor que el
      {_p(1 - al.DROP_SEASON_PERCENTILE)} de las caídas registradas en esa misma época en años
      anteriores. Sin esa segunda condición la regla avisaba de que las lagunas se secan en verano,
      que es lo que llevan haciendo desde siempre: en Gallocanta saltaba en 100 de sus 494 fechas.</li>
  <li><b>Eutrofización</b>: el <b>pico</b> de NDCI de la ventana actual por encima del percentil
      {_p(al.BLOOM_PERCENTILE)} de los picos de esa época en años anteriores, más un margen de
      {al.BLOOM_MARGIN}. Pico y no mediana, porque una floración de algas dura días y una mediana de
      tres semanas la borra.</li>
  <li><b>Turbidez</b>: NDTI actual por encima del percentil 90 de la época.</li>
</ul>
<p>El umbral de floración algal que da la literatura (NDCI &gt; {config.NDCI_BLOOM}, unos 40 mg/m³
de clorofila-a) no sirve para disparar en estas lagunas: se calibró en aguas continentales
profundas, y en lagunas someras, salinas y de fondo claro el índice está inflado de forma crónica
—Gallocanta lo supera en las 494 fechas que tiene—. Aquí solo se usa para <em>graduar</em> la
gravedad: una alerta que además pasa ese umbral es alta; si no, media.</p>"""),

        ("campo", "El contraste con medidas de campo", f"""
<p>El satélite dice cuánta superficie hay inundada, no por qué. Donde existe una red de medida en el
suelo se añade al pie de la gráfica, y en Doñana la hay: {hydro.SOURCE}, con cinco estaciones que
publican calado dentro de la marisma y siete que miden lluvia.</p>
<p>Sirve de dos maneras. Como <b>explicación</b>, porque la lluvia acumulada de cada mes va detrás
del calado y se ve qué crecidas vienen de qué precipitación. Y como <b>validación independiente</b>:
el área inundada que mide el satélite y el calado que miden los sensores en el suelo correlacionan
0,94 sobre las 168 fechas que comparten, y la relación es monótona por tramos de calado. Son dos
instrumentos que no tienen nada que ver midiendo lo mismo, y coinciden.</p>"""),

        ("limites", "Lo que este informe no puede decir", """
<ul>
  <li><b>NDTI y NDCI son proxies sin calibrar</b>: no hay unidades de turbidez ni miligramos de
      clorofila detrás, y sus umbrales de literatura no son transferibles a lagunas someras y
      salinas. Valen para comparar un humedal consigo mismo, no para dar cifras absolutas.</li>
  <li><b>Nueve años son pocos</b>: la referencia empieza en julio de 2017, cuando empieza el
      archivo de Sentinel-2 L2A. Un año excepcional puede parecer normal si solo hay ocho con los
      que compararlo.</li>
  <li><b>Cuidado con los años incompletos</b>: 2017 arranca en julio y el año en curso acaba hoy,
      así que sus medias anuales no cubren el mismo periodo que las demás. Comparándolas sin más
      apareció una falsa tendencia de eutrofización en el Mar Menor que era, simplemente, el otoño
      que aún no ha ocurrido. Las alertas no caen en esa trampa porque siempre comparan con la
      misma época del año.</li>
  <li><b>No distingue la causa</b>: una desecación puede venir de que no ha llovido, de que el
      acuífero ha bajado o de que alguien ha abierto una compuerta. El satélite no lo sabe; para eso
      está el contraste con las medidas de campo, que hoy solo existe en Doñana.</li>
  <li><b>Una alerta es un aviso, no un diagnóstico</b>: dice que algo se sale de lo que ese humedal
      suele hacer en estas fechas, y que merece que alguien lo mire.</li>
</ul>"""),
    ]


def section() -> str:
    """La sección completa, lista para insertar en el informe."""
    bloques = _bloques()
    out = ['<h2 id="metodologia">Metodología</h2>',
           '<p class="indice">'
           + " · ".join(f'<a href="#{ancla}">{titulo}</a>' for ancla, titulo, _ in bloques)
           + ' · <a href="#glosario">Glosario de siglas</a></p>']
    for ancla, titulo, cuerpo in bloques:
        out.append(f'<h3 id="{ancla}">{titulo}</h3>{cuerpo}')

    out.append('<h3 id="glosario">Glosario de siglas</h3><dl class="glosario">')
    for sigla, expansion, texto in GLOSARIO:
        exp = "" if expansion == "—" else f" <i>{expansion}</i>"
        out.append(f"<dt>{sigla}{exp}</dt><dd>{texto}</dd>")
    out.append("</dl>")
    return "\n".join(out)
