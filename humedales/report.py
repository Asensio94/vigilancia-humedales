"""Informe HTML: gráficas de serie, alertas, imagen de la última fecha y mapa."""
from __future__ import annotations

import base64
import html
import io
import json
from datetime import date
from pathlib import Path

import folium
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import config, hydro, i18n, masks, metodologia
from .alerts import Alert
from .indices import Rasters
from .logo import LOGO_SVG, favicon_link
from .i18n import t
from .sites import SITES, Site, site_geometry, site_text


def _png_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _jpg_b64(fig) -> str:
    """Las imágenes de satélite son fotografías, y en PNG pesaban 600 KB cada una.

    En JPEG bajan a menos de una quinta parte sin diferencia visible a esta escala, y
    eso es lo que decide si el informe publicado son 2 MB o 6. Las gráficas siguen en
    PNG: tienen texto y líneas finas, que es justo lo que el JPEG estropea.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="jpg", dpi=110, bbox_inches="tight", pil_kwargs={"quality": 82})
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _fmt(v, nd=3) -> str:
    return "–" if v is None or pd.isna(v) else f"{v:.{nd}f}"


def _ha(v, lang: str = "es") -> str:
    """Hectáreas con el separador de miles del idioma: 7.686 en español, 7 686 en francés.

    Con la coma inglesa "7,686 ha" se lee como siete hectáreas y media. Los índices
    espectrales sí se dejan con punto decimal, que es como se citan en la literatura.
    """
    return i18n.n(v, lang)


def _kind(kind: str, lang: str = "es") -> str:
    """Los tipos de alerta viajan como identificadores en el JSON; en pantalla se leen."""
    key = f"kind_{kind}"
    return t(lang, key) if key in i18n.UI["es"] else kind.replace("_", " ")


def denominator(site: Site, df: pd.DataFrame) -> tuple[float, str]:
    """Superficie con la que se compara la lámina medida: (hectáreas, "floodable" | "site").

    La etiqueta es una clave, no un texto: se traduce al pintarla.

    El polígono Natura 2000 es un límite administrativo: en Doñana incluye pinares,
    arenas y cultivos, así que "fracción del sitio" no dice nada hidrológico. Cuando
    el comando `mask` ya ha medido qué parte del humedal llega a tener agua alguna
    vez, ese es el denominador; si no, se cae al polígono completo.
    """
    floodable = masks.floodable_ha(site.slug)
    if floodable:
        return float(floodable), "floodable"
    if not df.empty and df["site_ha"].notna().any():
        return float(df["site_ha"].dropna().iloc[-1]), "site"
    return 0.0, "site"


def hydro_series(site: Site, df: pd.DataFrame) -> tuple[pd.Series | None, pd.Series | None]:
    """Calado y lluvia medidos en el suelo, para contrastar con lo que ve el satélite.

    Nunca debe hacer fallar el informe: si el portal no responde o agota su límite de
    peticiones se usa lo que haya en disco, y si no hay nada se devuelve nada.
    """
    if df.empty or not hydro.has_context(site.slug):
        return None, None
    dates = pd.to_datetime(df["date"])
    start, end = dates.min().date(), dates.max().date()
    level = rain = None
    try:
        lv = hydro.series(site, "waterLevel", start, end)
        if not lv.empty:
            level = lv.median(axis=1, skipna=True)   # mediana entre estaciones de la marisma
            level.attrs.update(lv.attrs)
        rn = hydro.series(site, "rainfallAccumulated", start, end)
        if not rn.empty:
            # La lluvia diaria es ruido a esta escala; el acumulado mensual sí se lee.
            rain = rn.mean(axis=1, skipna=True).resample("MS").sum()
            rain.attrs.update(rn.attrs)
    except Exception:  # noqa: BLE001
        pass
    return level, rain


def series_chart(site: Site, df: pd.DataFrame) -> str:
    """Las gráficas van en el idioma del informe del país del humedal."""
    lang = i18n.lang_of(site.country)
    ok = df[df["quality"] == "ok"].copy()
    other = df[df["quality"] != "ok"]
    ok["date"] = pd.to_datetime(ok["date"])
    den, den_label = denominator(site, df)
    level, rain = hydro_series(site, df)
    with_hydro = level is not None or rain is not None
    n = 4 if with_hydro else 3
    heights = [2.2, 1.1, 1.1] + ([1.5] if with_hydro else [])
    fig, axes = plt.subplots(n, 1, figsize=(10, 7.5 if n == 3 else 9.6), sharex=True,
                             gridspec_kw={"height_ratios": heights})
    axes[0].plot(ok["date"], ok["water_ha"], "o-", color="#1f77b4", ms=3, lw=1, label=t(lang, "ch_water"))
    if "wet_veg_ha" in ok:
        axes[0].plot(ok["date"], ok["wet_veg_ha"], "s--", color="#17becf", ms=3, lw=1,
                     label=t(lang, "ch_wet_veg"))
    if not other.empty:
        axes[0].scatter(pd.to_datetime(other["date"]), other["water_ha"], marker="x",
                        color="grey", s=18, label=t(lang, "ch_discarded"))
    axes[0].legend(loc="upper left", fontsize=8)
    axes[0].set_ylabel(t(lang, "ch_water_axis"))
    axes[0].set_title(t(lang, "ch_title", name=site_text(site, lang)[0],
                        den=t(lang, f"den_{den_label}"), ha=_ha(den, lang)), fontsize=10)
    axes[1].plot(ok["date"], ok["ndci_mean"], "o-", color="#2ca02c", ms=3, lw=1)
    axes[1].axhline(config.NDCI_BLOOM, color="red", ls="--", lw=0.8)
    axes[1].set_ylabel(t(lang, "ch_ndci"))
    axes[2].plot(ok["date"], ok["ndti_mean"], "o-", color="#8c564b", ms=3, lw=1)
    axes[2].set_ylabel(t(lang, "ch_ndti"))
    if with_hydro:
        ax, ax2 = axes[3], None
        if rain is not None:
            # La lluvia va detrás y a la derecha: es el forzamiento, no la medida.
            ax2 = ax.twinx()
            ax2.bar(rain.index, rain.values, width=22, color="#aecfe8", zorder=1,
                    label=t(lang, "ch_rain"))
            ax2.set_ylabel(t(lang, "ch_rain_axis"))
            ax2.set_ylim(bottom=0)
            ax2.set_zorder(ax.get_zorder() - 1)
            ax.patch.set_visible(False)
        if level is not None:
            ax.plot(level.index, level.values, "-", color="#14496f", lw=1.2, zorder=3,
                    label=t(lang, "ch_level"))
            ax.set_ylabel(t(lang, "ch_level_axis"))
        else:
            ax.set_yticks([])
        # Una sola leyenda con las dos series: viven en ejes distintos, así que hay que
        # juntar las etiquetas a mano.
        handles = ax.get_legend_handles_labels()
        if ax2 is not None:
            extra = ax2.get_legend_handles_labels()
            handles = (handles[0] + extra[0], handles[1] + extra[1])
        if handles[0]:
            ax.legend(*handles, loc="upper left", fontsize=8)
    for ax in axes:
        ax.grid(alpha=0.3)
    fig.autofmt_xdate()
    return _png_b64(fig)


def cached_image(slug: str) -> str | None:
    """La última imagen guardada de este humedal, si hay alguna.

    El informe se regenera cada día, pero una fecha nueva de satélite solo llega cada
    varios días, y nunca el mismo día en los seis humedales. Sin esta caché el informe
    automático saldría casi siempre con cinco de seis humedales sin imagen. La fecha va
    impresa dentro del propio PNG, así que no engaña sobre a qué día corresponde.
    """
    guardadas = sorted(config.IMG_DIR.glob(f"{slug}_*.jpg"))
    if not guardadas:
        return None
    return base64.b64encode(guardadas[-1].read_bytes()).decode()


def latest_image(site: Site, when: date, r: Rasters) -> str:
    lang = i18n.lang_of(site.country)
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    rgb = r.rgb.copy()
    rgb[~r.inside] = rgb[~r.inside] * 0.35 + 0.65  # atenúa el exterior del humedal
    axes[0].imshow(rgb)
    axes[0].set_title(t(lang, "img_rgb", name=site_text(site, lang)[0], date=when.isoformat()),
                      fontsize=10)
    overlay = np.zeros(r.water.shape + (4,), dtype=float)
    overlay[r.inside] = (0.9, 0.9, 0.9, 0.35)
    overlay[r.wet_veg] = (0.2, 0.75, 0.75, 0.8)
    overlay[r.water] = (0.1, 0.4, 0.9, 0.95)
    overlay[r.invalid] = (1, 1, 1, 0.9)
    with np.errstate(invalid="ignore"):
        bloom = r.ndci > config.NDCI_BLOOM
    overlay[bloom] = (0.1, 0.8, 0.1, 0.95)
    axes[1].imshow(rgb * 0.4 + 0.3)
    axes[1].imshow(overlay)
    axes[1].set_title(t(lang, "img_overlay"), fontsize=10)
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
    b64 = _jpg_b64(fig)
    # Se guarda para los días en que no hay escena nueva, y se deja solo la última: el
    # histórico de imágenes no lo usa nadie.
    for antigua in config.IMG_DIR.glob(f"{site.slug}_*.jpg"):
        antigua.unlink(missing_ok=True)
    (config.IMG_DIR / f"{site.slug}_{when.isoformat()}.jpg").write_bytes(base64.b64decode(b64))
    return b64


def overview_map(statuses: dict[str, tuple[Site, list[Alert]]], lang: str = "es") -> str:
    """Mapa de situación, encuadrado sobre los humedales que se pintan.

    El encuadre se calcula, no se fija: con un centro escrito a mano el mapa del
    informe francés abría sobre La Mancha.
    """
    # CARTO's basemaps now ask for an API key and serve an "API KEY REQUIRED" tile
    # without one. Same keyless layers as the irrigation map: OpenStreetMap, and
    # Esri imagery to see the wetland itself.
    m = folium.Map(tiles=None)
    folium.TileLayer("OpenStreetMap", name=t(lang, "layer_map")).add_to(m)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name=t(lang, "layer_satellite"), show=False).add_to(m)
    caja = None
    for slug, (site, alerts) in statuses.items():
        geom = site_geometry(site)
        minx, miny, maxx, maxy = geom.bounds
        caja = ((min(caja[0], minx), min(caja[1], miny),
                 max(caja[2], maxx), max(caja[3], maxy)) if caja else
                (minx, miny, maxx, maxy))
        if any(a.severity == "alta" for a in alerts):
            color = "#d62728"
        elif alerts:
            color = "#ff7f0e"
        else:
            color = "#2ca02c"
        folium.GeoJson(
            geom.__geo_interface__,
            style_function=lambda _f, c=color: {"color": c, "fillColor": c, "weight": 1.5,
                                                "fillOpacity": 0.35},
            tooltip=t(lang, "map_tooltip", name=site_text(site, lang)[0], n=len(alerts)),
            control=False,   # the selector only switches the base layer
        ).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    if caja:
        m.fit_bounds([[caja[1], caja[0]], [caja[3], caja[2]]])
    return m.get_root().render()


# Shared look of the sibling projects: copied verbatim from the common style guide and
# inlined first, so each page stays a single self-contained file. Only the accent and
# this repo's own rules go after it.
COMMON_CSS = (Path(__file__).with_name("common.css")).read_text(encoding="utf-8")
FAVICON = favicon_link("#1d6a96", "#6bb3e0")
FONTS_URL = ("https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;600;700"
             "&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600"
             "&family=IBM+Plex+Mono:wght@400;500&display=swap")
ACCENT_CSS = ":root{--accent:#1d6a96;--accent-dark:#6bb3e0}"

# Alert colours carry meaning (high, medium, none) and match the map polygons, so they
# stay here instead of in the common sheet.
CSS = """
:root{--alta:#d62728;--media:#ff7f0e;--sin-alerta:#2ca02c}
.paises{margin:0;font-size:14px;color:var(--muted)}
.paises a[aria-current]{color:var(--ink);text-decoration:none}
.site-header .note{margin:0;max-width:72ch}
main{max-width:1440px;margin:0 auto;padding:0 16px}
main h2{margin:2.5rem 0 .6rem;padding-bottom:4px;border-bottom:1px solid var(--line);
  font:700 26px/1.1 var(--font-title);text-transform:uppercase;letter-spacing:.03em}
main h2 small{font:400 14px/1.4 var(--font-text);text-transform:none;letter-spacing:0;color:var(--muted)}
main img{display:block;height:auto;border:1px solid var(--line)}
small{color:var(--muted)}
.tabla{overflow-x:auto;max-width:100%}
main table{border-collapse:collapse;font-size:14.5px}
main td,main th{border:1px solid var(--line);padding:.3rem .55rem;text-align:left}
main th{font:600 14px/1.3 var(--font-title);text-transform:uppercase;letter-spacing:.05em}
.kpi{display:flex;gap:.6rem;flex-wrap:wrap;margin:.5rem 0}
.kpi div{background:var(--paper);border:1px solid var(--line);padding:.5rem .9rem;min-width:130px}
.kpi small{font:600 12.5px/1.2 var(--font-title);text-transform:uppercase;letter-spacing:.06em}
.kpi b{display:block;font:500 20px/1.3 var(--font-data);font-variant-numeric:tabular-nums}
.alerta,.ok{padding:.5rem .8rem;margin:.4rem 0;border-left:5px solid var(--alta);
  background:color-mix(in srgb,var(--alta) 10%,var(--paper))}
.alerta.media{border-color:var(--media);background:color-mix(in srgb,var(--media) 10%,var(--paper))}
.ok{border-color:var(--sin-alerta);background:color-mix(in srgb,var(--sin-alerta) 10%,var(--paper))}
.mapa{width:100%;height:520px;border:1px solid var(--line);display:block}
.indice{font-size:14.5px;color:var(--muted);line-height:1.7}
.pasos li{margin:.35rem 0}
.glosario dt{font-weight:600;margin-top:.7rem}
.glosario dd{margin:.15rem 0 0 1.2rem;color:var(--muted);max-width:72ch}
@media (max-width:640px){.kpi div{min-width:0;flex:1 1 140px}.mapa{height:420px}}
"""


# Un informe por país, no uno con los doce humedales dentro. No es solo peso: la
# hidrología, las fuentes de contexto y el lector de cada uno son distintos, y una
# tabla resumen que mezcla Doñana con la Camarga no se lee mejor por ser más larga.
# El nombre de cada país se lee en el idioma de la página que lo enlaza (i18n).
PAISES = {"ES": "index.html", "FR": "france.html"}


# Common footer of the sibling projects (style guide, section 3). This project's own
# entry is marked with aria-current.
SIBLINGS = [
    ("https://asensio94.github.io/observatorio-alegaciones/", "Observatorio de alegaciones"),
    ("https://asensio94.github.io/vigia-incendios/", "Vigía de incendios"),
    ("https://asensio94.github.io/centinela-natura/", "Centinela Natura"),
    ("https://asensio94.github.io/vigilancia-humedales/", "Vigilancia de humedales"),
    ("https://asensio94.github.io/sub-nocte/", "Sub Nocte"),
    ("https://asensio94.github.io/riesgo-tendidos-aves/", "Riesgo de tendidos para aves"),
    ("https://asensio94.github.io/grafo-promotores/", "Grafo de promotores"),
    ("https://asensio94.github.io/cartera-cotizadas/", "Cartera de las cotizadas"),
    ("https://asensio94.github.io/cuaderno-campo/", "Cuaderno de campo"),
    ("https://asensio94.github.io/caudal-ecologico/", "Caudal ecológico"),
    ("https://asensio94.github.io/estado-iba/", "Estado de las IBA"),
    ("https://asensio94.github.io/acuiferos-francia/", "Acuíferos de Francia"),
]
OWN_SIBLING = "Vigilancia de humedales"


def site_footer(pais: str, fuentes: list[str] | None = None) -> str:
    """Sources and licences of this project, then the shared principle and siblings. A page
    with sources of its own (the irrigation one) passes them instead of the wetland ones."""
    lang = i18n.lang_of(pais)
    if fuentes is not None:
        return _footer(fuentes, lang)
    fuentes = [t(lang, "src_images"), t(lang, "src_natura")]
    if pais == "FR":
        fuentes.append(t(lang, "src_coast"))
    if any(s.country == pais and hydro.has_context(s.slug) for s in SITES.values()):
        fuentes.append(t(lang, "src_hydro", source=html.escape(hydro.SOURCE)))
    fuentes.append(t(lang, "src_code",
                     link='<a href="https://github.com/Asensio94/vigilancia-humedales">'
                          'github.com/Asensio94/vigilancia-humedales</a>'))
    return _footer(fuentes, lang)


def _footer(fuentes: list[str], lang: str = "es") -> str:
    items = "\n".join(
        f'    <li aria-current="page"><a href="{url}">{name}</a></li>' if name == OWN_SIBLING
        else f'    <li><a href="{url}">{name}</a></li>'
        for url, name in SIBLINGS)
    return (
        '<footer class="site-footer">\n'
        f'  <p class="principle">{t(lang, "principle")}</p>\n'
        + "".join(f"  <p>{f}</p>\n" for f in fuentes)
        # The sibling projects keep their Spanish names: they are proper names.
        + f'  <nav aria-label="{t(lang, "siblings")}"><ul class="siblings"'
        + ("" if lang == "es" else ' lang="es"') + ">\n"
        + items
        + "\n  </ul></nav>\n</footer>")


def header_figures(results: dict[str, dict], lang: str = "es") -> str:
    """Key figures of the page: wetlands, active alerts, last valid date, valid dates."""
    n_alertas = sum(len(r["alerts"]) for r in results.values())
    con_alerta = sum(1 for r in results.values() if r["alerts"])
    fechas = [str(r["latest"]["date"]) for r in results.values() if r["latest"] is not None]
    n_ok = sum(int((r["series"]["quality"] == "ok").sum()) for r in results.values()
               if r["series"] is not None and not r["series"].empty)
    cifras = [
        (str(len(results)), t(lang, "fig_sites")),
        (str(n_alertas), t(lang, "fig_alerts")),
        (str(con_alerta), t(lang, "fig_sites_alert")),
        (max(fechas) if fechas else "–", t(lang, "fig_last")),
        (_ha(n_ok, lang), t(lang, "fig_valid")),
    ]
    return ('<div class="figures">'
            + "".join(f"<div><b>{v}</b><span>{k}</span></div>" for v, k in cifras)
            + "</div>")


def render(results: dict[str, dict], run_date: date, pais: str = "ES") -> str:
    """results[slug] = {site, series, alerts, latest, chart_b64, image_b64}

    La página entera va en el idioma del país: la de España en español, la de Francia
    en francés.
    """
    lang = i18n.lang_of(pais)
    nombre_pais = t(lang, f"country_{pais}")
    paises = " · ".join(
        f'<a aria-current="page">{t(lang, f"country_{codigo}")}</a>' if codigo == pais
        else f'<a href="{fichero}">{t(lang, f"country_{codigo}")}</a>'
        for codigo, fichero in PAISES.items())
    if pais == "ES":
        paises += f' · <a href="regadio.html">{t(lang, "irrigation_link")}</a>'
    donde = t(lang, f"in_country_{pais}")
    parts = [
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        FAVICON,
        f"<title>{t(lang, 'project')} · {nombre_pais} · {run_date.isoformat()}</title>",
        '<link rel="preconnect" href="https://fonts.googleapis.com">',
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
        f'<link rel="stylesheet" href="{html.escape(FONTS_URL)}">',
        f"<style>\n{COMMON_CSS}\n{ACCENT_CSS}\n{CSS}</style></head><body>",
        '<header class="site-header">',
        f"<h1>{LOGO_SVG}{t(lang, 'h1')}</h1>",
        f'<nav class="paises label" aria-label="{t(lang, "countries")}">{paises}</nav>',
        f'<p class="lede">{t(lang, "lede", n=len(results), where=donde)}</p>',
        header_figures(results, lang),
        f'<p class="note">{t(lang, "note", date=run_date.isoformat())}</p>',
        "</header>",
        "<main>",
    ]

    parts.append(f'<h2>{t(lang, "summary")}</h2><div class="tabla"><table><tr>'
                 f'<th>{t(lang, "th_site")}</th><th>{t(lang, "th_last")}</th>'
                 f'<th>{t(lang, "th_water")}</th><th>NDCI</th><th>NDTI</th>'
                 f'<th>{t(lang, "th_alerts")}</th></tr>')
    for slug, res in results.items():
        site, latest, alerts = res["site"], res["latest"], res["alerts"]
        nombre = html.escape(site_text(site, lang)[0])
        if latest is None:
            parts.append(f"<tr><td>{nombre}</td>"
                         f'<td colspan=5>{t(lang, "no_valid_row")}</td></tr>')
            continue
        parts.append(
            f"<tr><td>{nombre}</td><td>{latest['date']}</td>"
            f"<td>{_ha(latest['water_ha'], lang)}</td><td>{_fmt(latest['ndci_mean'])}</td>"
            f"<td>{_fmt(latest['ndti_mean'])}</td>"
            f"<td>{', '.join(_kind(a.kind, lang) for a in alerts) or t(lang, 'none')}</td></tr>")
    parts.append("</table></div>")

    for slug, res in results.items():
        site, df, alerts, latest = res["site"], res["series"], res["alerts"], res["latest"]
        nombre, region, notas = (html.escape(x) for x in site_text(site, lang))
        parts.append(f"<h2>{nombre} <small>({region} · Natura 2000 "
                     f"{', '.join(site.natura_codes)})</small></h2>")
        parts.append(f"<p><small>{notas}</small></p>")
        if latest is None:
            parts.append(f'<p>{t(lang, "no_valid_period")}</p>')
            continue
        n_ok = int((df["quality"] == "ok").sum())
        den, den_label = denominator(site, df)
        frac = latest["water_ha"] / den if den else float("nan")
        pct = "–" if pd.isna(frac) else i18n.p(frac, lang)
        parts.append(
            '<div class="kpi">'
            f'<div><small>{t(lang, "kpi_last")}</small><b>{latest["date"]}</b></div>'
            f'<div><small>{t(lang, "kpi_water")}</small><b>{_ha(latest["water_ha"], lang)} ha</b>'
            f'<small>{t(lang, f"pct_of_{den_label}", pct=pct)}</small></div>'
            f'<div><small>{t(lang, "kpi_ndci")}</small><b>{_fmt(latest["ndci_mean"])}</b></div>'
            f'<div><small>{t(lang, "kpi_ndti")}</small><b>{_fmt(latest["ndti_mean"])}</b></div>'
            f'<div><small>{t(lang, "kpi_clouds")}</small>'
            f'<b>{i18n.p(latest["cloud_frac"], lang)}</b></div>'
            f'<div><small>{t(lang, "kpi_valid")}</small><b>{n_ok}</b>'
            f'<small>{t(lang, "kpi_of_dates", n=len(df))}</small></div>'
            "</div>")
        if alerts:
            for a in alerts:
                parts.append(f'<div class="alerta {a.severity}"><b>{_kind(a.kind, lang).upper()}'
                             f' · {t(lang, f"sev_{a.severity}")}</b><br>'
                             f"{html.escape(a.text(lang))}</div>")
        else:
            parts.append(f'<div class="ok">{t(lang, "no_alerts")}</div>')
        if res.get("chart_b64"):
            parts.append(f'<p><img src="data:image/png;base64,{res["chart_b64"]}" '
                         f'alt="{t(lang, "alt_chart", name=nombre)}"></p>')
            notes = []
            m = masks.load(slug)
            if m:
                notes.append(t(lang, "mask_note", floodable=_ha(m["floodable_ha"], lang),
                               site=_ha(m["site_ha"], lang),
                               permanent=_ha(m["permanent_ha"], lang), dates=m["dates_used"]))
            if hydro.has_context(slug):
                notes.append(t(lang, "hydro_note", source=html.escape(hydro.SOURCE)))
                if hydro.was_limited(slug):
                    notes.append(t(lang, "hydro_limited"))
            if notes:
                parts.append(f"<p><small>{' '.join(notes)}</small></p>")
        if res.get("image_b64"):
            parts.append(f'<p><img src="data:image/jpeg;base64,{res["image_b64"]}" '
                         f'alt="{t(lang, "alt_image", name=nombre)}"></p>')

    parts.append(f'<h2>{t(lang, "map")}</h2>')
    statuses = {slug: (r["site"], r["alerts"]) for slug, r in results.items()}
    map_html = overview_map(statuses, lang)
    parts.append(f'<iframe class="mapa" title="{t(lang, "map_title")}" '
                 f'srcdoc="{html.escape(map_html)}"></iframe>')
    parts.append("</main>")
    parts.append(metodologia.section(results, pais, lang))
    parts.append(site_footer(pais))
    parts.append("</body></html>")
    return "\n".join(parts)


def write(results: dict[str, dict], run_date: date) -> list[tuple[str, str, str]]:
    """Escribe un informe por país y devuelve (país, html, json) de cada uno.

    Las alertas se sacan también en JSON por país porque es lo que lee el resumen de la
    ejecución automática, y allí interesa saber de qué informe viene cada una.
    """
    salidas: list[tuple[str, str, str]] = []
    for pais in PAISES:
        del_pais = {slug: res for slug, res in results.items()
                    if res["site"].country == pais}
        if not del_pais:
            continue
        html_path = config.OUTPUT_DIR / f"informe_{pais}_{run_date.isoformat()}.html"
        html_path.write_text(render(del_pais, run_date, pais), encoding="utf-8")
        alerts = [a.to_dict() for r in del_pais.values() for a in r["alerts"]]
        json_path = config.OUTPUT_DIR / f"alertas_{pais}_{run_date.isoformat()}.json"
        json_path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")
        salidas.append((pais, str(html_path), str(json_path)))

    # Y todas juntas, con el nombre de siempre: es el fichero que puede estar leyendo
    # algo de fuera, y a un consumidor le sirve más la lista completa que dos mitades.
    todas = [a.to_dict() for r in results.values() for a in r["alerts"]]
    (config.OUTPUT_DIR / f"alertas_{run_date.isoformat()}.json").write_text(
        json.dumps(todas, ensure_ascii=False, indent=2), encoding="utf-8")
    return salidas
