"""Informe HTML: gráficas de serie, alertas, imagen de la última fecha y mapa."""
from __future__ import annotations

import base64
import html
import io
import json
from datetime import date

import folium
import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import config, hydro, masks, metodologia
from .alerts import Alert
from .indices import Rasters
from .sites import Site, site_geometry


def _png_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _fmt(v, nd=3) -> str:
    return "–" if v is None or pd.isna(v) else f"{v:.{nd}f}"


def _ha(v) -> str:
    """Hectáreas con separador de miles español: 7.686, no 7,686.

    El informe está en español y con la coma inglesa "7,686 ha" se lee como siete
    hectáreas y media. Los índices espectrales sí se dejan con punto decimal, que es
    como se citan en la literatura.
    """
    return f"{v:,.0f}".replace(",", ".")


# Los tipos de alerta viajan como identificadores en el JSON; en pantalla se leen.
KIND_LABELS = {"desecacion": "desecación", "descenso_brusco": "descenso brusco",
               "eutrofizacion": "eutrofización", "turbidez": "turbidez"}


def _kind(kind: str) -> str:
    return KIND_LABELS.get(kind, kind.replace("_", " "))


def denominator(site: Site, df: pd.DataFrame) -> tuple[float, str]:
    """Superficie con la que se compara la lámina medida.

    El polígono Natura 2000 es un límite administrativo: en Doñana incluye pinares,
    arenas y cultivos, así que "fracción del sitio" no dice nada hidrológico. Cuando
    el comando `mask` ya ha medido qué parte del humedal llega a tener agua alguna
    vez, ese es el denominador; si no, se cae al polígono completo.
    """
    floodable = masks.floodable_ha(site.slug)
    if floodable:
        return float(floodable), "área inundable"
    if not df.empty and df["site_ha"].notna().any():
        return float(df["site_ha"].dropna().iloc[-1]), "sitio Natura 2000"
    return 0.0, "sitio Natura 2000"


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
    axes[0].plot(ok["date"], ok["water_ha"], "o-", color="#1f77b4", ms=3, lw=1, label="agua libre")
    if "wet_veg_ha" in ok:
        axes[0].plot(ok["date"], ok["wet_veg_ha"], "s--", color="#17becf", ms=3, lw=1,
                     label="vegetación inundada")
    if not other.empty:
        axes[0].scatter(pd.to_datetime(other["date"]), other["water_ha"], marker="x",
                        color="grey", s=18, label="descartadas (nubes, neblina, incoherentes)")
    axes[0].legend(loc="upper left", fontsize=8)
    axes[0].set_ylabel("Agua (ha)")
    axes[0].set_title(f"{site.name}: superficie de agua. {den_label[0].upper()}{den_label[1:]}: "
                      f"{_ha(den)} ha", fontsize=10)
    axes[1].plot(ok["date"], ok["ndci_mean"], "o-", color="#2ca02c", ms=3, lw=1)
    axes[1].axhline(config.NDCI_BLOOM, color="red", ls="--", lw=0.8)
    axes[1].set_ylabel("NDCI medio\n(clorofila)")
    axes[2].plot(ok["date"], ok["ndti_mean"], "o-", color="#8c564b", ms=3, lw=1)
    axes[2].set_ylabel("NDTI medio\n(turbidez)")
    if with_hydro:
        ax, ax2 = axes[3], None
        if rain is not None:
            # La lluvia va detrás y a la derecha: es el forzamiento, no la medida.
            ax2 = ax.twinx()
            ax2.bar(rain.index, rain.values, width=22, color="#aecfe8", zorder=1,
                    label="lluvia mensual")
            ax2.set_ylabel("Lluvia\n(mm/mes)")
            ax2.set_ylim(bottom=0)
            ax2.set_zorder(ax.get_zorder() - 1)
            ax.patch.set_visible(False)
        if level is not None:
            ax.plot(level.index, level.values, "-", color="#14496f", lw=1.2, zorder=3,
                    label="calado medido en la marisma")
            ax.set_ylabel("Calado (m)")
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


def latest_image(site: Site, when: date, r: Rasters) -> str:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.2))
    rgb = r.rgb.copy()
    rgb[~r.inside] = rgb[~r.inside] * 0.35 + 0.65  # atenúa el exterior del humedal
    axes[0].imshow(rgb)
    axes[0].set_title(f"{site.name}, color natural, {when.isoformat()}", fontsize=10)
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
    axes[1].set_title("Agua libre (azul), veg. inundada (cian), NDCI alto (verde), nubes (blanco)", fontsize=10)
    for ax in axes:
        ax.set_xticks([])
        ax.set_yticks([])
    return _png_b64(fig)


def overview_map(statuses: dict[str, tuple[Site, list[Alert]]]) -> str:
    m = folium.Map(location=[39.5, -3.5], zoom_start=6, tiles="CartoDB positron")
    for slug, (site, alerts) in statuses.items():
        geom = site_geometry(site)
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
            tooltip=f"{site.name}: {len(alerts)} alerta(s)",
        ).add_to(m)
    return m.get_root().render()


CSS = """
body{font-family:system-ui,sans-serif;max-width:1100px;margin:auto;padding:1rem 1.5rem;color:#222}
h1{font-size:1.5rem} h2{font-size:1.2rem;margin-top:2.5rem;border-bottom:1px solid #ddd}
.kpi{display:flex;gap:1rem;flex-wrap:wrap;margin:.5rem 0}
.kpi div{background:#f4f6f8;border-radius:8px;padding:.5rem .9rem;min-width:130px}
.kpi b{display:block;font-size:1.25rem}
.alerta{border-left:5px solid #d62728;background:#fff4f4;padding:.5rem .8rem;margin:.4rem 0}
.alerta.media{border-color:#ff7f0e;background:#fff8f0}
.ok{border-left:5px solid #2ca02c;background:#f3fbf3;padding:.5rem .8rem}
img{max-width:100%} small{color:#666}
table{border-collapse:collapse;font-size:.85rem} td,th{border:1px solid #ddd;padding:.25rem .5rem}
h3{font-size:1.02rem;margin:1.6rem 0 .3rem}
.indice{font-size:.85rem;color:#555;line-height:1.7}
.glosario dt{font-weight:600;margin-top:.7rem} .glosario dd{margin:.15rem 0 0 1.2rem;color:#444}
#metodologia ~ p,#metodologia ~ ul li,.glosario dd{max-width:75ch;line-height:1.5}
"""


def render(results: dict[str, dict], run_date: date) -> str:
    """results[slug] = {site, series, alerts, latest, chart_b64, image_b64}"""
    parts = [
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">",
        f"<title>Vigilancia de humedales · {run_date.isoformat()}</title>",
        f"<style>{CSS}</style></head><body>",
        "<h1>Vigilancia satelital de humedales protegidos</h1>",
        "<p><small>Sentinel-2 L2A (Earth Search / AWS), límites Natura 2000 (EEA). Informe "
        f"generado el {run_date.isoformat()}. Superficie de agua, turbidez y clorofila medidas por "
        "satélite cada pocos días; las alertas comparan cada humedal consigo mismo en la misma "
        "época del año. Todo lo demás —qué mide cada índice, qué fechas se descartan, cómo se "
        "decide una alerta y qué significa cada sigla— está en la "
        "<a href=\"#metodologia\">metodología</a>, al final.</small></p>",
    ]

    parts.append("<h2>Resumen</h2><table><tr><th>Humedal</th><th>Última fecha válida</th>"
                 "<th>Agua (ha)</th><th>NDCI</th><th>NDTI</th><th>Alertas</th></tr>")
    for slug, res in results.items():
        site, latest, alerts = res["site"], res["latest"], res["alerts"]
        if latest is None:
            parts.append(f"<tr><td>{html.escape(site.name)}</td>"
                         "<td colspan=5>sin observaciones válidas</td></tr>")
            continue
        parts.append(
            f"<tr><td>{html.escape(site.name)}</td><td>{latest['date']}</td>"
            f"<td>{_ha(latest['water_ha'])}</td><td>{_fmt(latest['ndci_mean'])}</td>"
            f"<td>{_fmt(latest['ndti_mean'])}</td>"
            f"<td>{', '.join(_kind(a.kind) for a in alerts) or 'ninguna'}</td></tr>")
    parts.append("</table>")

    for slug, res in results.items():
        site, df, alerts, latest = res["site"], res["series"], res["alerts"], res["latest"]
        parts.append(f"<h2>{html.escape(site.name)} <small>({site.region} · Natura 2000 "
                     f"{', '.join(site.natura_codes)})</small></h2>")
        parts.append(f"<p><small>{html.escape(site.notes)}</small></p>")
        if latest is None:
            parts.append("<p>Sin observaciones válidas en el periodo.</p>")
            continue
        n_ok = int((df["quality"] == "ok").sum())
        den, den_label = denominator(site, df)
        frac = latest["water_ha"] / den if den else float("nan")
        parts.append(
            '<div class="kpi">'
            f"<div><small>Última fecha válida</small><b>{latest['date']}</b></div>"
            f"<div><small>Agua</small><b>{_ha(latest['water_ha'])} ha</b>"
            f"<small>{100 * frac:.0f} % del {den_label}</small></div>"
            f"<div><small>NDCI medio</small><b>{_fmt(latest['ndci_mean'])}</b></div>"
            f"<div><small>NDTI medio</small><b>{_fmt(latest['ndti_mean'])}</b></div>"
            f"<div><small>Nubes en el sitio</small><b>{100 * latest['cloud_frac']:.0f} %</b></div>"
            f"<div><small>Observaciones válidas</small><b>{n_ok}</b><small>de {len(df)} fechas</small></div>"
            "</div>")
        if alerts:
            for a in alerts:
                parts.append(f'<div class="alerta {a.severity}"><b>{_kind(a.kind).upper()}'
                             f' · {a.severity}</b><br>{html.escape(a.message)}</div>')
        else:
            parts.append('<div class="ok">Sin alertas: valores dentro del rango de referencia.</div>')
        if res.get("chart_b64"):
            parts.append(f'<p><img src="data:image/png;base64,{res["chart_b64"]}"></p>')
            notes = []
            m = masks.load(slug)
            if m:
                notes.append(
                    f"Área inundable {_ha(m['floodable_ha'])} ha de las {_ha(m['site_ha'])} ha del "
                    f"sitio Natura 2000, de las cuales {_ha(m['permanent_ha'])} ha con agua casi "
                    f"siempre; medida acumulando {m['dates_used']} fechas de meses húmedos.")
            if hydro.has_context(slug):
                notes.append(f"Calado y lluvia del panel inferior: {html.escape(hydro.SOURCE)}.")
                if hydro.was_limited(slug):
                    notes.append("La serie de campo se ha servido desde la copia local: el portal "
                                 "agotó su límite de peticiones, así que puede no llegar a la última "
                                 "fecha del satélite.")
            if notes:
                parts.append(f"<p><small>{' '.join(notes)}</small></p>")
        if res.get("image_b64"):
            parts.append(f'<p><img src="data:image/png;base64,{res["image_b64"]}"></p>')

    parts.append("<h2>Mapa</h2>")
    statuses = {slug: (r["site"], r["alerts"]) for slug, r in results.items()}
    map_html = overview_map(statuses)
    parts.append(f'<iframe srcdoc="{html.escape(map_html)}" '
                 'style="width:100%;height:520px;border:0"></iframe>')
    parts.append(metodologia.section(results))
    parts.append("</body></html>")
    return "\n".join(parts)


def write(results: dict[str, dict], run_date: date) -> tuple[str, str]:
    html_path = config.OUTPUT_DIR / f"informe_{run_date.isoformat()}.html"
    html_path.write_text(render(results, run_date), encoding="utf-8")
    alerts = [a.to_dict() for r in results.values() for a in r["alerts"]]
    json_path = config.OUTPUT_DIR / f"alertas_{run_date.isoformat()}.json"
    json_path.write_text(json.dumps(alerts, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(html_path), str(json_path)
