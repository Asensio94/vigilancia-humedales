"""Catálogo de humedales vigilados y obtención de sus límites (Natura 2000)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import requests
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

from . import config, costa


@dataclass(frozen=True)
class Site:
    slug: str
    name: str
    natura_codes: tuple[str, ...]
    region: str
    notes: str = ""
    # Humedales donde la lámina de agua es permanente (lagunas costeras): la
    # métrica relevante es la calidad del agua, no la superficie inundada.
    permanent_water: bool = False
    country: str = "ES"
    # Humedales cuyo polígono Natura 2000 entra en el mar: hay que recortarlo antes
    # de medir nada. Ver costa.py.
    sea_in_polygon: bool = False
    # Meses en que la lámina alcanza su máximo, cuando no son los del invierno
    # ibérico. Solo se usa para muestrear el área inundable: en un embalse de
    # laminación o en un étang piscícola el máximo es de primavera, y buscarlo en
    # enero mediría un humedal más pequeño del que hay.
    wet_months: tuple[int, ...] = ()

    @property
    def crs(self) -> str:
        return config.CRS_BY_COUNTRY[self.country]


SITES: dict[str, Site] = {
    s.slug: s
    for s in [
        Site("donana", "Doñana", ("ES0000024",), "Andalucía",
             "Marismas del Guadalquivir. Inundación estacional; desecación por sobreexplotación del acuífero."),
        Site("mar-menor", "Mar Menor", ("ES6200030",), "Murcia",
             "Laguna hipersalina. Crisis de eutrofización recurrentes (2016, 2019, 2021).",
             permanent_water=True),
        Site("tablas-daimiel", "Tablas de Daimiel", ("ES0000013",), "Castilla-La Mancha",
             "Humedal fluvial dependiente del acuífero 23. Se seca casi por completo en sequías."),
        Site("albufera-valencia", "L'Albufera de València", ("ES0000023",), "C. Valenciana",
             "Laguna costera eutrófica rodeada de arrozal.", permanent_water=True),
        Site("fuente-piedra", "Laguna de Fuente de Piedra", ("ES0000033",), "Andalucía",
             "Laguna salina endorreica. Colonia de flamenco; se seca en verano."),
        Site("gallocanta", "Laguna de Gallocanta", ("ES2430043",), "Aragón",
             "Laguna salina endorreica. Invernada de grulla; ciclos plurianuales de inundación."),

        # Francia. Los seis son continentales a propósito: en los grandes humedales
        # mareales del Atlántico francés (bahía del Mont-Saint-Michel, bahía del
        # Somme, golfo de Morbihan, Arcachon) la superficie de agua a la hora del
        # paso del satélite la manda la marea, no la sequía, así que una alerta de
        # desecación allí no mediría nada. Encajarlos exige predicción de marea.
        Site("camargue", "Camarga", ("FR9301592",), "Provenza-Alpes-Costa Azul",
             "Delta del Ródano. Lagunas salobres y marismas gestionadas con compuertas; "
             "arrozal y la mayor colonia de flamenco del Mediterráneo occidental.",
             country="FR", sea_in_polygon=True),
        Site("marais-poitevin", "Marais Poitevin", ("FR5200659", "FR5400446"),
             "Nueva Aquitania / País del Loira",
             "Marjal drenado y compartimentado en canales, el segundo de Francia. "
             "Tensión abierta por las reservas de riego y el nivel del acuífero.",
             country="FR", sea_in_polygon=True),
        Site("brenne", "Grande Brenne", ("FR2400534",), "Centro-Valle del Loira",
             "Cerca de 2.000 étangs piscícolas medievales. Se vacían por rotación, "
             "así que la lámina agregada baja por manejo y no solo por sequía.",
             country="FR", wet_months=(1, 2, 3, 4, 5)),
        Site("lac-du-der", "Lac du Der-Chantecoq", ("FR2100334",), "Gran Este",
             "Embalse de laminación del Marne: se llena en invierno y se vacía en "
             "verano para sostener el estiaje del Sena. Escala mayor de la grulla en "
             "Europa occidental, el otro extremo del eje de Gallocanta.",
             country="FR", wet_months=(4, 5, 6)),
        Site("grand-lieu", "Lac de Grand-Lieu", ("FR5200625",), "País del Loira",
             "Lago somero natural sin apenas cubeta: su extensión invernal multiplica "
             "por tres la de verano, y esa oscilación es el estado normal.",
             country="FR"),
        Site("dombes", "La Dombes", ("FR8201635",), "Auvernia-Ródano-Alpes",
             "Un millar de étangs en rotación de inundación y cultivo (evolage y "
             "assec). El polígono es una comarca entera con los étangs dispersos "
             "dentro, así que el área inundable medida es aquí más necesaria que en "
             "ningún otro.",
             # La ventana empieza en noviembre porque el evolage se llena en otoño, y
             # falta niebla: con los meses 1 a 5 solo 11 de 45 fechas pasaban el
             # control de calidad, la mitad que en cualquier otro humedal, y un
             # área inundable medida con once fechas se queda corta por definición.
             country="FR", wet_months=(11, 12, 1, 2, 3, 4, 5)),
    ]
}


def natura_geometry(sitecode: str) -> dict:
    params = {
        "where": f"SITECODE='{sitecode}'",
        "outFields": "SITECODE,SITENAME,SITETYPE",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
    }
    r = requests.get(config.NATURA_URL, params=params, timeout=60)
    r.raise_for_status()
    fc = r.json()
    if not fc.get("features"):
        raise RuntimeError(f"Natura 2000: sin resultados para {sitecode}")
    return fc["features"][0]


def site_geometry(site: Site, refresh: bool = False):
    """Devuelve la geometría shapely (EPSG:4326) del humedal, cacheada en disco."""
    path = config.SITES_DIR / f"{site.slug}.geojson"
    if path.exists() and not refresh:
        with path.open(encoding="utf-8") as fh:
            guardado = json.load(fh)
        # La caché se rehace si se guardó con otra decisión sobre el mar. Marais
        # Poitevin quedó en disco antes de que existiera el recorte, y su polígono
        # traía el Atlántico dentro: la máscara se habría construido sobre eso sin
        # que nada avisara, porque un fichero cacheado no dice con qué código se hizo.
        if guardado["properties"].get("sea_clipped", False) == site.sea_in_polygon:
            return shape(guardado["geometry"])
    geoms = []
    names = []
    for code in site.natura_codes:
        feat = natura_geometry(code)
        geoms.append(shape(feat["geometry"]).buffer(0))
        names.append(feat["properties"].get("SITENAME"))
    geom = unary_union(geoms)
    if site.sea_in_polygon:
        geom = costa.recortar_mar(geom, site.slug, site.crs, refresh=refresh)
    feature = {
        "type": "Feature",
        "properties": {"slug": site.slug, "name": site.name,
                       "natura_codes": list(site.natura_codes), "natura_names": names,
                       "sea_clipped": site.sea_in_polygon},
        "geometry": mapping(geom),
    }
    with path.open("w", encoding="utf-8") as fh:
        json.dump(feature, fh, ensure_ascii=False)
    return geom
