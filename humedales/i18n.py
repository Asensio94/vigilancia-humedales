"""Interface strings and number formats, one dictionary per language.

Each country's report is written in that country's language: the Spanish one in
Spanish, the French one in French. Data files (series, alert JSON) stay in canonical,
language-independent values; only what a reader sees goes through here. Same pattern
as birdrisk/i18n.py in riesgo-tendidos-aves.
"""
from __future__ import annotations

LANG_BY_COUNTRY = {"ES": "es", "FR": "fr"}

# French typography: a narrow no-break space as thousands separator and before «%».
_NNBSP = " "


def lang_of(pais: str) -> str:
    return LANG_BY_COUNTRY.get(pais, "es")


def n(v: float, lang: str) -> str:
    """Integer with the thousands separator of the language: 46.709 / 46 709."""
    s = f"{v:,.0f}"
    return s.replace(",", "." if lang == "es" else _NNBSP)


def d(v: float, lang: str, nd: int = 1) -> str:
    """Decimal with comma, in both languages: 2,7. Format the number, never the sentence."""
    return f"{v:.{nd}f}".replace(".", ",")


def p(x: float, lang: str) -> str:
    """A fraction as a percentage without decimals: 15 % / 15 %."""
    return f"{100 * x:.0f}{' ' if lang == 'es' else _NNBSP}%"


UI: dict[str, dict[str, str]] = {
    "es": {
        "project": "Vigilancia de humedales",
        "h1": "Vigilancia de <span>humedales</span>",
        "countries": "Países",
        "country_ES": "España",
        "country_FR": "Francia",
        "in_country_ES": "de España",
        "in_country_FR": "de Francia",
        "irrigation_link": "Regadío fuera del suelo regable en Doñana",
        "lede": ("Mide cada pocos días con Sentinel-2 la superficie de agua, la turbidez y la "
                 "clorofila de {n} humedales protegidos {where} y avisa cuando uno se sale de lo "
                 "que suele dar en la misma época del año."),
        "note": ("Informe generado el {date}. Las alertas comparan cada humedal consigo mismo en "
                 "la misma época del año. Todo lo demás —qué mide cada índice, qué fechas se "
                 "descartan, cómo se decide una alerta y qué significa cada sigla— está en "
                 '<a href="#metodologia">Cómo se calcula</a>, al final.'),
        "fig_sites": "humedales",
        "fig_alerts": "alertas activas",
        "fig_sites_alert": "humedales con alerta",
        "fig_last": "última fecha válida",
        "fig_valid": "fechas válidas en la serie",
        "summary": "Resumen",
        "th_site": "Humedal",
        "th_last": "Última fecha válida",
        "th_water": "Agua (ha)",
        "th_alerts": "Alertas",
        "no_valid_row": "sin observaciones válidas",
        "none": "ninguna",
        "no_valid_period": "Sin observaciones válidas en el periodo.",
        "kpi_last": "Última fecha válida",
        "kpi_water": "Agua",
        "pct_of_floodable": "{pct} del área inundable",
        "pct_of_site": "{pct} del sitio Natura 2000",
        "kpi_ndci": "NDCI medio",
        "kpi_ndti": "NDTI medio",
        "kpi_clouds": "Nubes en el sitio",
        "kpi_valid": "Observaciones válidas",
        "kpi_of_dates": "de {n} fechas",
        "sev_alta": "alta",
        "sev_media": "media",
        "kind_desecacion": "desecación",
        "kind_descenso_brusco": "descenso brusco",
        "kind_eutrofizacion": "eutrofización",
        "kind_turbidez": "turbidez",
        "no_alerts": "Sin alertas: valores dentro del rango de referencia.",
        "alt_chart": "Series de agua, NDCI y NDTI de {name}",
        "alt_image": "Última imagen de {name}: color natural y agua detectada",
        "mask_note": ("Área inundable {floodable} ha de las {site} ha del sitio Natura 2000, de "
                      "las cuales {permanent} ha con agua casi siempre; medida acumulando {dates} "
                      "fechas de meses húmedos."),
        "hydro_note": "Calado y lluvia del panel inferior: {source}.",
        "hydro_limited": ("La serie de campo se ha servido desde la copia local: el portal agotó "
                          "su límite de peticiones, así que puede no llegar a la última fecha del "
                          "satélite."),
        "map": "Mapa",
        "map_title": "Mapa de los humedales",
        "map_tooltip": "{name}: {n} alerta(s)",
        "layer_map": "Mapa",
        "layer_satellite": "Satélite",
        # Charts and satellite image.
        "den_floodable": "Área inundable",
        "den_site": "Sitio Natura 2000",
        "ch_water": "agua libre",
        "ch_wet_veg": "vegetación inundada",
        "ch_discarded": "descartadas (nubes, neblina, incoherentes)",
        "ch_water_axis": "Agua (ha)",
        "ch_title": "{name}: superficie de agua. {den}: {ha} ha",
        "ch_ndci": "NDCI medio\n(clorofila)",
        "ch_ndti": "NDTI medio\n(turbidez)",
        "ch_rain": "lluvia mensual",
        "ch_rain_axis": "Lluvia\n(mm/mes)",
        "ch_level": "calado medido en la marisma",
        "ch_level_axis": "Calado (m)",
        "img_rgb": "{name}, color natural, {date}",
        "img_overlay": "Agua libre (azul), veg. inundada (cian), NDCI alto (verde), nubes (blanco)",
        # Footer.
        "principle": ("Datos públicos, reglas a la vista y cada cifra enlazada a su fuente. "
                      "Indicios, no veredictos."),
        "hub": "← Terra Aperta: todos los proyectos",
        "siblings": "Proyectos hermanos",
        "src_images": ("Imágenes: Copernicus Sentinel-2 L2A, servidas por Earth Search "
                       "(Element 84, AWS)."),
        "src_natura": ("Contornos de los humedales: red Natura 2000 (Agencia Europea de Medio "
                       "Ambiente)."),
        "src_coast": ("Línea de costa para recortar el mar: © colaboradores de OpenStreetMap "
                      "(ODbL)."),
        "src_hydro": "Calado y lluvia medidos en el suelo: {source}.",
        "src_code": "Código con licencia MIT en {link}.",
    },
    "fr": {
        "project": "Veille des zones humides",
        "h1": "Veille des <span>zones humides</span>",
        "countries": "Pays",
        "country_ES": "Espagne",
        "country_FR": "France",
        "in_country_ES": "en Espagne",
        "in_country_FR": "en France",
        "irrigation_link": "Irrigation hors des terres irrigables à Doñana",
        "lede": ("Mesure tous les quelques jours, avec Sentinel-2, la surface en eau, la turbidité "
                 "et la chlorophylle de {n} zones humides protégées {where}, et signale celles qui "
                 "s'écartent de ce qu'elles donnent d'habitude à la même époque de l'année."),
        "note": ("Rapport généré le {date}. Les alertes comparent chaque zone humide à elle-même, "
                 "à la même époque de l'année. Tout le reste — ce que mesure chaque indice, quelles "
                 "dates sont écartées, comment se décide une alerte et ce que veut dire chaque "
                 'sigle — se trouve dans <a href="#metodologia">Méthode de calcul</a>, à la fin.'),
        "fig_sites": "zones humides",
        "fig_alerts": "alertes actives",
        "fig_sites_alert": "zones humides en alerte",
        "fig_last": "dernière date valide",
        "fig_valid": "dates valides dans la série",
        "summary": "Synthèse",
        "th_site": "Zone humide",
        "th_last": "Dernière date valide",
        "th_water": "Eau (ha)",
        "th_alerts": "Alertes",
        "no_valid_row": "aucune observation valide",
        "none": "aucune",
        "no_valid_period": "Aucune observation valide sur la période.",
        "kpi_last": "Dernière date valide",
        "kpi_water": "Eau",
        "pct_of_floodable": "{pct} de la zone inondable",
        "pct_of_site": "{pct} du site Natura 2000",
        "kpi_ndci": "NDCI moyen",
        "kpi_ndti": "NDTI moyen",
        "kpi_clouds": "Nuages sur le site",
        "kpi_valid": "Observations valides",
        "kpi_of_dates": "sur {n} dates",
        "sev_alta": "élevée",
        "sev_media": "moyenne",
        "kind_desecacion": "assèchement",
        "kind_descenso_brusco": "baisse brutale",
        "kind_eutrofizacion": "eutrophisation",
        "kind_turbidez": "turbidité",
        "no_alerts": "Aucune alerte : valeurs dans la plage de référence.",
        "alt_chart": "Séries d'eau, de NDCI et de NDTI de {name}",
        "alt_image": "Dernière image de {name} : couleurs naturelles et eau détectée",
        "mask_note": ("Zone inondable de {floodable} ha sur les {site} ha du site Natura 2000, "
                      "dont {permanent} ha en eau presque en permanence ; mesurée en cumulant "
                      "{dates} dates de mois humides."),
        "hydro_note": "Hauteur d'eau et pluie du panneau inférieur : {source}.",
        "hydro_limited": ("La série de terrain provient de la copie locale : le portail a atteint "
                          "sa limite de requêtes, elle peut donc s'arrêter avant la dernière date "
                          "du satellite."),
        "map": "Carte",
        "map_title": "Carte des zones humides",
        "map_tooltip": "{name} : {n} alerte(s)",
        "layer_map": "Carte",
        "layer_satellite": "Satellite",
        "den_floodable": "Zone inondable",
        "den_site": "Site Natura 2000",
        "ch_water": "eau libre",
        "ch_wet_veg": "végétation inondée",
        "ch_discarded": "écartées (nuages, brume, incohérentes)",
        "ch_water_axis": "Eau (ha)",
        "ch_title": "{name} : surface en eau. {den} : {ha} ha",
        "ch_ndci": "NDCI moyen\n(chlorophylle)",
        "ch_ndti": "NDTI moyen\n(turbidité)",
        "ch_rain": "pluie mensuelle",
        "ch_rain_axis": "Pluie\n(mm/mois)",
        "ch_level": "hauteur d'eau mesurée dans le marais",
        "ch_level_axis": "Hauteur (m)",
        "img_rgb": "{name}, couleurs naturelles, {date}",
        "img_overlay": ("Eau libre (bleu), vég. inondée (cyan), NDCI élevé (vert), "
                        "nuages (blanc)"),
        "principle": ("Données publiques, règles visibles et chaque chiffre relié à sa source. "
                      "Des indices, pas des verdicts."),
        "hub": "← Terra Aperta : tous les projets",
        "siblings": "Projets frères",
        "src_images": ("Images : Copernicus Sentinel-2 L2A, distribuées par Earth Search "
                       "(Element 84, AWS)."),
        "src_natura": ("Contours des zones humides : réseau Natura 2000 (Agence européenne pour "
                       "l'environnement)."),
        "src_coast": ("Trait de côte pour découper la mer : © contributeurs d'OpenStreetMap "
                      "(ODbL)."),
        "src_hydro": "Hauteur d'eau et pluie mesurées sur le terrain : {source}.",
        "src_code": "Code sous licence MIT sur {link}.",
    },
}


def t(lang: str, key: str, **kw) -> str:
    """The string `key` in `lang`, formatted with `kw`. Falls back to Spanish."""
    s = UI.get(lang, UI["es"]).get(key) or UI["es"][key]
    return s.format(**kw) if kw else s
