"""HTML page of the irrigation check: map, yearly table, patches and method, in Spanish."""
from __future__ import annotations

import html
import json
from pathlib import Path

import folium
from shapely.geometry import mapping
from shapely.ops import unary_union

from . import config, legal, validation
from .irrigation import IrrigationSite
from .report import CSS, _ha

USE_NAMES = {"IV": "invernadero / bajo plástico", "TA": "tierra arable", "FO": "forestal",
             "FY": "frutales", "CI": "cítricos", "PR": "pasto arbustivo", "PA": "pasto con arbolado",
             "PS": "pastizal", "OV": "olivar", "VI": "viñedo", "MT": "matorral", "TH": "huerta"}


def _campaigns(slug: str) -> list[tuple[dict, dict]]:
    out = []
    for p in sorted(config.IRRIGATION_DIR.glob(f"{slug}_*.json")):
        fc = json.loads(p.with_suffix(".geojson").read_text(encoding="utf-8"))
        out.append((json.loads(p.read_text(encoding="utf-8")), fc))
    return out


def _d(v, nd=1) -> str:
    return f"{v:,.{nd}f}".replace(",", "X").replace(".", ",").replace("X", ".")


CHIP_CSS = """
.chips{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin:.5rem 0 1rem}
.chip{margin:0;font-size:.8rem}.chip div{position:relative;aspect-ratio:1}
.chip img,.chip svg{position:absolute;inset:0;width:100%;height:100%}.chip img{background:#eee}
.chip path{fill:none;stroke:#e00;stroke-width:2.5}details summary{cursor:pointer;margin:.5rem 0}
"""

# Display only: a date counts as clear when this share of the plan area was visible.
CLEAR_DAY = 0.8


def _adjacent_ha(fc: dict) -> float:
    """Hectares of patches within ADJACENT_M of the irrigable land, read from the patches
    themselves so that campaigns computed before the summary carried it still render."""
    return sum(f["properties"]["ha"] for f in fc["features"]
               if f["properties"]["distance_to_irrigable_m"] <= config.ADJACENT_M)


def _adjacent_reading(adjacent: float, outside: float) -> str:
    share = adjacent / outside if outside else 0
    if share >= 0.5:
        return ("Lo que domina son fincas que siguen más allá de la línea del suelo regable, no "
                "parcelas aisladas en mitad del pinar.")
    return "La mayor parte son parcelas separadas del suelo regable, no bordes de fincas legales."


def _pct(x: float) -> str:
    return f"{_d(100 * x, 0)} %"


def _checks(slug: str, camps: list[tuple[dict, dict]]) -> list[tuple[int, str, dict, dict]]:
    """Every labelled campaign as (campaign, PNOA layer, its patches, its labels)."""
    by_year = {c["campaign"]: fc for c, fc in camps}
    out = []
    for path in sorted((config.IRRIGATION_DIR / "validation").glob(f"{slug}_*.csv")):
        year, flight = path.stem[len(slug) + 1:].split("_", 1)
        if int(year) in by_year:
            out.append((int(year), flight, by_year[int(year)], validation.read_labels(path)))
    return out


def _chip(f: dict, geom, label: dict, flight: str, n: int) -> str:
    px = 400
    bbox = validation.chip_bbox(geom)
    p = f["properties"]
    note = f"<br>{html.escape(label['note'])}" if label["note"] else ""
    return (f'<figure class="chip"><div><img loading="lazy" width="{px}" height="{px}" '
            f'alt="Ortofoto PNOA de la mancha {n}" src="{html.escape(validation.pnoa_url(flight, bbox, px))}">'
            f'<svg viewBox="0 0 {px} {px}"><path d="{validation.outline_svg_path(geom, bbox, px)}"/></svg></div>'
            f"<figcaption><b>#{n} · {_d(p['ha'])} ha · {html.escape(label['label'])}</b>{note}</figcaption>"
            "</figure>")


def _check_section(check: tuple[int, str, dict, dict]) -> str:
    year, flight, fc, labels = check
    st = validation.precision(fc, labels)
    geoms = validation.patch_geoms(fc)
    chips = {"hit": [], "miss": []}
    for n, f in enumerate(fc["features"], 1):
        pid = f["properties"]["id"]
        if pid in labels:
            key = "hit" if labels[pid]["label"] == "invernadero" else "miss"
            chips[key].append(_chip(f, geoms[pid], labels[pid], flight, n))
    c, h = st["counts"], st["ha"]
    legend = "".join(f"<li><b>{k}</b>: {html.escape(text)}</li>" for k, (text, _) in validation.LABELS.items())
    return "".join([
        f'<h2 id="ortofoto">Comprobado con la ortofoto · campaña {year}</h2>',
        "<p>Sentinel-2 ve píxeles de 10 m; la ortofoto del PNOA (IGN) ve los túneles uno a uno, a 25 cm. "
        f"Se miraron <b>las {st['labelled']} manchas</b> de la campaña {year} sobre el vuelo más cercano "
        f"({html.escape(validation.FLIGHTS.get(flight, flight))}) y cada una se clasificó a ojo. Las etiquetas "
        f"están en <code>data/irrigation/validation/</code>, y cada imagen de abajo se pide en directo al "
        "servicio del IGN con el contorno de la mancha encima: cualquiera puede revisar el juicio.</p>",
        '<div class="kpi">',
        f"<div>Con túneles visibles<b>{_pct(st['precision_patches'])}</b><small>{c['invernadero']} manchas, "
        f"{_d(h['invernadero'])} ha</small></div>",
        f"<div>Terreno agrícola<b>{_pct(st['farmland_patches'])}</b><small>túneles o cultivo, "
        f"{c['invernadero'] + c['cultivo']} manchas</small></div>",
        f"<div>Falsos positivos<b>{c['no_agricola']}</b><small>{_d(h['no_agricola'])} ha no agrícolas</small></div>",
        "</div>",
        f'<ul style="font-size:.85rem">{legend}</ul>',
        "<p><small>El vuelo es de verano y el plástico se pone en otoño, así que una finca con el túnel ya "
        "desmontado sale lisa: esas cuentan como «cultivo», y por eso la cifra de túneles es un mínimo. Una "
        "mancha lisa también puede ser una finca abierta después del vuelo. Los falsos positivos son franjas "
        "de arena dentro del pinar (cortafuegos) que la regla espectral no separa del plástico. "
        "<b>La clasificación la hizo Claude, un modelo de IA, sobre estas mismas imágenes, y está pendiente de "
        "revisión por una persona</b>; una etiqueta mal puesta se corrige en el CSV.</small></p>",
        f"<h3>Las que no son túnel ({len(chips['miss'])})</h3>",
        '<div class="chips">', "".join(chips["miss"]), "</div>",
        f"<details><summary>Ver las {len(chips['hit'])} con túneles visibles</summary>",
        '<div class="chips">', "".join(chips["hit"]), "</div></details>",
        "<p><small>Ortofoto: PNOA © Instituto Geográfico Nacional, CC BY 4.0.</small></p>",
    ])


def _why(s: dict, check: tuple | None) -> str:
    declared = s["outside_declared_ha"] / s["outside_ha"] if s["outside_ha"] else 0
    checked = ""
    if check:
        st = validation.precision(check[2], check[3])
        checked = (f" Comprobadas con la ortofoto, el {_pct(st['farmland_patches'])} de las manchas de "
                   f"{check[0]} son terreno agrícola (<a href=\"#ortofoto\">ver</a>).")
    return "".join([
        "<h2>Para qué sirve</h2><ul>",
        "<li><b>Pone la causa junto al efecto.</b> La <a href=\"index.html\">página de humedales</a> mide "
        "cuánta agua queda en las lagunas; esta mide cuánta tierra se riega alrededor donde el plan no lo "
        "permite, sobre el mismo acuífero.</li>",
        "<li><b>Es una serie, no un informe suelto.</b> Se repite cada campaña con el mismo método y datos "
        "abiertos: cualquiera puede rehacerla y la cifra se sigue año a año.</li>",
        f"<li><b>Cada mancha se puede comprobar.</b> Lleva coordenadas, zona del plan, recinto SIGPAC e imagen "
        f"aérea.{checked}</li>",
        f"<li><b>Contrasta dos registros oficiales.</b> El {_pct(declared)} de lo detectado fuera del SAR está "
        "declarado en SIGPAC como invernadero o regadío: el registro de las ayudas de la PAC reconoce regadío "
        "en suelo donde el plan no lo deja. Eso ya no depende del satélite.</li>",
        "<li><b>Para quién.</b> Para quien ya trabaja en esto (organizaciones ambientales, Confederación y "
        "Junta, periodistas, investigación): una lista anual, abierta y georreferenciada de dónde mirar.</li>",
        "</ul><p>Y lo que <b>no</b> es: no prueba que nadie riegue ilegalmente (ver «Qué no dice este mapa»), "
        f"es poca superficie (el {_d(100 * s['outside_ha'] / s['plastic_in_plan_ha'], 0)} % del plástico del "
        "ámbito, sobre todo fincas que pasan unos metros de la línea) y solo ve cultivos bajo plástico.</p>",
    ])


def _map(zones, fc: dict) -> str:
    def to_ll(g):
        return legal.reproject(g, config.IRRIGATION_CRS, 4326)
    irrigable = unary_union([z.geom for z in zones if z.irrigable and not z.urban]).simplify(10)
    plan = unary_union([z.geom for z in zones]).simplify(25)
    # Fixed centre and zoom instead of fit_bounds: folium renders the map inside an iframe
    # that still measures 0 px when fitBounds runs, and the map opened on the whole world.
    b = to_ll(plan).bounds
    m = folium.Map(location=[(b[1] + b[3]) / 2, (b[0] + b[2]) / 2], zoom_start=11, tiles=None,
                   control_scale=True)
    folium.TileLayer("OpenStreetMap", name="Mapa").add_to(m)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satélite").add_to(m)
    folium.GeoJson(mapping(to_ll(plan.boundary)), name="Ámbito del plan",
                   style_function=lambda _: {"color": "#555", "weight": 1, "dashArray": "4"}).add_to(m)
    folium.GeoJson(mapping(to_ll(irrigable)), name="Suelo agrícola regable (SAR)",
                   style_function=lambda _: {"color": "#1f77b4", "weight": 0.6, "fillOpacity": 0.15}).add_to(m)

    def style(f):
        p = f["properties"]
        declared = max(p["declared_greenhouse_share"], p["declared_irrigated_share"]) >= 0.5
        return {"color": "#d62728" if not declared else "#ff7f0e", "weight": 1.5, "fillOpacity": 0.5}
    folium.GeoJson(fc, name="Plástico fuera del SAR", style_function=style,
                   tooltip=folium.GeoJsonTooltip(
                       ["ha", "plastic_dates", "plan_zone", "sigpac_use", "sigpac_irrigation_coef"],
                       ["ha", "fechas con plástico", "zona del plan", "uso SIGPAC", "coef. regadío"])).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    return m._repr_html_()


def render(site: IrrigationSite) -> str:
    camps = _campaigns(site.slug)
    if not camps:
        raise RuntimeError(f"no hay campañas calculadas para {site.slug}")
    s, fc = camps[-1]
    checks = _checks(site.slug, camps)
    check = checks[-1] if checks else None
    zones = legal.peorcfd_zoning()
    feats = fc["features"]
    r = s["rules"]
    fun = s["funnel_ha"]
    years = "".join(
        f"<tr><td>{c['campaign']}</td><td>{len(c['dates'])}</td>"
        f"<td>{sum(d['coverage'] >= CLEAR_DAY for d in c['dates'])}</td><td>{_ha(c['plastic_in_plan_ha'])}</td>"
        f"<td>{_ha(c['plastic_in_irrigable_ha'])}</td><td>{_d(c['outside_ha'])}</td>"
        f"<td>{_d(100 * c['outside_ha'] / c['plastic_in_plan_ha'])} %</td>"
        f"<td>{c['outside_patches']}</td><td>{_d(c['outside_declared_ha'])}</td></tr>" for c, _ in camps)
    rows = []
    for f in feats[:40]:
        p = f["properties"]
        ref = (f'<a href="{html.escape(p["sigpac_url"])}">{html.escape(p["sigpac_ref"])}</a>'
               if p["sigpac_url"] else "–")
        use = p["sigpac_use"] or "–"
        rows.append(
            f"<tr><td>{_d(p['ha'])}</td><td>{_d(p['plastic_dates'], 0)} de {_d(p['valid_dates'], 0)}</td>"
            f"<td>{html.escape(p['plan_zone'] or '–')}</td><td>{_ha(p['distance_to_irrigable_m'])} m</td>"
            f"<td>{use} <small>{USE_NAMES.get(use, '')}</small></td><td>{p['sigpac_irrigation_coef']}</td>"
            f"<td>{ref}</td>"
            f'<td><a href="https://www.google.com/maps/@{p["lat"]},{p["lon"]},600m/data=!3m1!1e3">'
            f"{p['lat']:.5f}, {p['lon']:.5f}</a></td></tr>")
    zone_txt = ", ".join(f"{k}: {_d(v)} ha" for k, v in sorted(s["outside_by_admin_zone"].items()))
    dates = ", ".join(d["date"] for d in s["dates"])
    return "".join([
        '<!doctype html><html lang="es"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>Regadío fuera del suelo regable · {html.escape(site.name)} · {s['campaign']}</title>",
        f"<style>{CSS}html{{color-scheme:light}}body{{background:#fff}}{CHIP_CSS}</style></head><body>",
        f"<h1>Regadío fuera del suelo regable · {html.escape(site.name)}</h1>",
        '<p class="nav"><small><a href="index.html">Vigilancia de humedales · España</a></small></p>',
        f"<p>Cultivos bajo plástico vistos por Sentinel-2 en la campaña {s['campaign']}, cruzados con la "
        "zonificación oficial del Plan Especial de la Corona Forestal de Doñana (Decreto 178/2014). "
        "El plan solo permite regar en los <em>suelos agrícolas regables</em> (SAR); el resto de su ámbito "
        "es forestal o agrícola de secano. Lo que hay aquí son <strong>indicios para comprobar, no "
        "infracciones</strong>: ver la sección «Qué no dice este mapa».</p>",
        '<div class="kpi">',
        f"<div>Ámbito del plan<b>{_ha(s['plan_ha'])} ha</b></div>",
        f"<div>Suelo regable (SAR)<b>{_ha(s['irrigable_ha'])} ha</b></div>",
        f"<div>Plástico dentro del SAR<b>{_ha(s['plastic_in_irrigable_ha'])} ha</b></div>",
        f"<div>Plástico fuera del SAR<b>{_d(s['outside_ha'])} ha</b><small>{s['outside_patches']} manchas</small></div>",
        f"<div>…declarado en SIGPAC<b>{_d(s['outside_declared_ha'])} ha</b><small>invernadero o regadío</small></div>",
        "</div>",
        f"<p>De las {_d(s['outside_ha'])} ha fuera del SAR, {_d(_adjacent_ha(fc))} están a "
        f"{config.ADJACENT_M} m o menos de él. {_adjacent_reading(_adjacent_ha(fc), s['outside_ha'])}</p>",
        f"<p><small>Fuera del SAR por zona del plan: {zone_txt}. Naranja en el mapa: la parcela SIGPAC "
        "declara invernadero o coeficiente de regadío, es decir, los propios registros de la administración "
        "contradicen el mapa del plan. Rojo: plástico sin nada declarado.</small></p>",
        _why(s, check),
        _map(zones, fc),
        "<h2>Por campaña</h2><table><tr><th>campaña</th><th>fechas</th><th>despejadas</th>"
        "<th>plástico en el ámbito (ha)</th><th>dentro del SAR (ha)</th><th>fuera del SAR (ha)</th>"
        f"<th>% del plástico</th><th>manchas</th><th>fuera y declarado (ha)</th></tr>{years}</table>",
        f"<p><small>«Despejadas»: fechas con al menos el {CLEAR_DAY:.0%} del ámbito visible. Las hectáreas "
        "dependen del tiempo que hizo: como se exige plástico en dos fechas, un invierno nublado deja menos "
        "plástico en todo el ámbito, dentro y fuera del SAR (2024 tuvo una sola fecha despejada antes del 20 "
        "de febrero). Entre campañas se compara mejor el porcentaje del plástico que cae fuera.</small></p>",
        f"<h2>Manchas fuera del SAR · campaña {s['campaign']}</h2>",
        "<p><small>Las 40 mayores. La referencia SIGPAC enlaza a la consulta pública del recinto (uso, "
        "pendiente, coeficiente de regadío); no contiene ni se publica ningún dato del titular. Todas las "
        f"manchas, con su geometría, en <code>data/irrigation/{site.slug}_{s['campaign']}.geojson</code>."
        "</small></p>",
        "<table><tr><th>ha</th><th>fechas con plástico</th><th>zona del plan</th><th>distancia al SAR</th>"
        "<th>uso SIGPAC</th><th>coef. regadío</th><th>recinto SIGPAC</th><th>ver</th></tr>",
        "".join(rows), "</table>",
        _check_section(check) if check else "",
        '<h2 id="metodologia">Cómo se calcula</h2>',
        "<p>En el Condado de Huelva el regadío no se ve verde: las fincas de fresa y frutos rojos cubren el "
        "suelo con macrotúneles de plástico de otoño a primavera y lo dejan desnudo en verano, cuando lo único "
        "verde es el pinar. Por eso se busca plástico en enero, febrero y marzo, no vegetación en julio.</p><ul>",
        f"<li>Cada fecha Sentinel-2 L2A de la ventana se lee a {r['IRRIGATION_RES_M']} m. Un píxel es plástico si "
        f"RPGI ≥ {r['PLASTIC_RPGI_MIN']:g} (índice de invernadero de Yang et al. 2017, alto sobre superficies "
        f"blancas y brillantes), PMLI ≤ {r['PLASTIC_PMLI_MAX']:g} (índice de acolchado plástico de Lu et al. 2014, "
        "bajo porque el plástico apenas cambia del rojo al infrarrojo de onda corta) y azul/rojo ≥ "
        f"{r['PLASTIC_BLUE_RED_MIN']:g} (descarta la mayor parte de la arena amarilla de cortafuegos y claros).</li>",
        f"<li>Se queda el plástico visto en al menos {r['PLASTIC_MIN_DATES']} fechas válidas. Fechas usadas: {dates}.</li>",
        f"<li>Se cruza con la zonificación del plan (REDIAM). No se cuenta el plástico a menos de "
        f"{r['LEGAL_EDGE_M']} m del SAR (píxeles mixtos y precisión de una cartografía 1:10.000), el que cae en "
        "suelo urbano ni el que está sobre recintos SIGPAC de agua, viales, edificaciones o improductivo. "
        "Sí se cuenta sobre recintos forestales: un claro nuevo cultivado en suelo aún registrado como "
        "forestal es justo el caso que interesa.</li>",
        f"<li>Se agrupa en manchas de al menos {_d(r['PATCH_MIN_HA'])} ha, y cada una lleva su recinto SIGPAC "
        f"(campaña {s['sigpac_campaign']}) con lo que declara.</li></ul>",
        "<h3>Qué no dice este mapa</h3><ul>",
        "<li>Que una finca riegue ilegalmente. El artículo 26.6 del plan permite que una explotación que cumpla los "
        "requisitos prevalezca sobre la cartografía, y el propio SAR se ha revisado (2014, 2018, 2021).</li>",
        "<li>Que el agua salga del acuífero. Un plástico no es un pozo. Para eso hace falta el Registro de Aguas "
        "de la Confederación del Guadalquivir.</li>",
        "<li>Cuánto regadío hay sin plástico. Cítricos, arándano bajo malla o fresa al aire no se detectan, así "
        "que la cifra es un mínimo.</li>",
        "<li>Que cada mancha sea un cultivo. Algunas franjas de arena del pinar pasan la regla (ver la "
        "comprobación con la ortofoto), y nadie ha ido a las fincas.</li></ul>",
        "<h3>Qué quita cada filtro</h3><table><tr><th>paso</th><th>ha</th></tr>",
        f"<tr><td>plástico persistente en suelo no regable del plan</td><td>{_ha(fun['not_irrigable'])}</td></tr>",
        f"<tr><td>…a más de {r['LEGAL_EDGE_M']} m del SAR</td><td>{_ha(fun['away_from_edge'])}</td></tr>",
        f"<tr><td>…sobre recintos SIGPAC de uso agrario o forestal</td><td>{_ha(fun['farming_use'])}</td></tr>",
        f"<tr><td>…en manchas de al menos {_d(r['PATCH_MIN_HA'])} ha (lo publicado)</td><td>{_d(s['outside_ha'])}</td></tr>",
        "</table>",
        "<h3>Contraste</h3><p>WWF estimó en 2021 unas 1.653 ha de cultivos bajo plástico fuera del SAR "
        "(<a href=\"https://wwfes.awsassets.panda.org/downloads/regadiosybalsasdonana.pdf\">Regadíos y balsas en "
        "Doñana</a>), por fotointerpretación y con la cartografía SAR de 2014. Desde entonces el SAR se revisó dos "
        "veces y el acuerdo de 2023 promovió el abandono de regadío, así que las cifras no son directamente "
        "comparables: la primera fila de la tabla anterior es la que se le parece en método.</p>",
        "<h3>Fuentes</h3><ul>",
        f"<li>Zonificación del plan: REDIAM, WFS <code>{html.escape(s['sources']['zoning'])}</code> (CC BY 4.0).</li>",
        f"<li>SIGPAC: FEGA, descarga ATOM por municipio <code>{html.escape(s['sources']['sigpac'])}</code> (CC BY 4.0).</li>",
        f"<li>Sentinel-2 L2A: Earth Search <code>{html.escape(s['sources']['sentinel2'])}</code>.</li>",
        f"<li>Ortofoto: PNOA histórico, IGN, WMS <code>{config.PNOA_WMS}</code> (CC BY 4.0).</li></ul>",
        "</body></html>",
    ])


def write(site: IrrigationSite) -> Path:
    path = config.OUTPUT_DIR / f"regadio_{site.slug}.html"
    path.write_text(render(site), encoding="utf-8")
    return path
