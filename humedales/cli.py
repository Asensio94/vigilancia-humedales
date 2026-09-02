"""CLI: python -m humedales.cli run --site tablas-daimiel --since 2026-06-01"""
from __future__ import annotations

import time
from datetime import date, timedelta
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from . import alerts as alerts_mod
from . import backfill as backfill_mod
from . import report, stac, store
from .indices import observe
from .sites import SITES, site_geometry

app = typer.Typer(add_completion=False, help="Vigilancia satelital de humedales protegidos.")
console = Console()


def _resolve_sites(site: list[str] | None):
    if not site:
        return list(SITES.values())
    bad = [s for s in site if s not in SITES]
    if bad:
        raise typer.BadParameter(f"humedal desconocido: {bad}. Usa `sites` para ver la lista.")
    return [SITES[s] for s in site]


@app.command()
def sites():
    """Lista los humedales del catálogo."""
    t = Table("slug", "nombre", "región", "Natura 2000", "agua permanente")
    for s in SITES.values():
        t.add_row(s.slug, s.name, s.region, ", ".join(s.natura_codes), "sí" if s.permanent_water else "no")
    console.print(t)


@app.command()
def run(
    site: Optional[list[str]] = typer.Option(None, "--site", "-s", help="slug(s); por defecto todos"),
    since: Optional[str] = typer.Option(None, help="YYYY-MM-DD; por defecto desde la última fecha guardada o 90 días"),
    until: Optional[str] = typer.Option(None, help="YYYY-MM-DD; por defecto hoy"),
    max_scene_cloud: float = typer.Option(60.0, help="nubosidad máxima de la escena completa (%)"),
    force: bool = typer.Option(False, help="recalcula fechas ya guardadas"),
    no_report: bool = typer.Option(False, help="solo actualiza las series"),
):
    """Descarga las fechas nuevas, calcula métricas, evalúa alertas y genera el informe."""
    today = date.today()
    end = date.fromisoformat(until) if until else today
    results: dict[str, dict] = {}

    for s in _resolve_sites(site):
        console.rule(f"[bold]{s.name}")
        geom = site_geometry(s)
        known = store.known_dates(s.slug)
        if since:
            start = date.fromisoformat(since)
        elif known:
            start = max(known) + timedelta(days=1)
        else:
            start = end - timedelta(days=90)

        items = stac.search(geom.bounds, start, end, max_scene_cloud) if start <= end else []
        days = stac.group_by_day(items)
        if not force:
            days = {d: its for d, its in days.items() if d not in known}
        console.print(f"{len(items)} escenas, {len(days)} fechas nuevas entre {start} y {end}")

        observations, last_rasters = [], None
        for d, its in days.items():
            try:
                obs, rasters = observe(s.slug, d, its, geom)
            except Exception as exc:  # noqa: BLE001
                console.print(f"  [red]{d}: error {type(exc).__name__}: {exc}")
                continue
            observations.append(obs)
            if obs.quality == "ok":
                last_rasters = (d, rasters)
            console.print(f"  {d}  {obs.quality:9s} agua={obs.water_ha:8.1f} ha  "
                          f"nubes={100 * obs.cloud_frac:4.0f}%  NDCI={obs.ndci_mean}  NDTI={obs.ndti_mean}")

        series = store.upsert(s.slug, observations) if observations else store.load(s.slug)
        site_alerts = alerts_mod.evaluate(s, series)
        for a in site_alerts:
            console.print(f"  [bold red]ALERTA {a.kind} ({a.severity}):[/] {a.message}")

        ok = series[series["quality"] == "ok"]
        latest = ok.iloc[-1] if not ok.empty else None
        res = {"site": s, "series": series, "alerts": site_alerts, "latest": latest,
               "chart_b64": None, "image_b64": None}
        if not no_report and not series.empty:
            res["chart_b64"] = report.series_chart(s, series)
            if last_rasters is not None:
                res["image_b64"] = report.latest_image(s, *last_rasters)
        results[s.slug] = res

    if not no_report and results:
        html_path, json_path = report.write(results, today)
        console.print(f"\nInforme: {html_path}\nAlertas: {json_path}")


@app.command()
def backfill(
    site: Optional[list[str]] = typer.Option(None, "--site", "-s", help="slug(s); por defecto todos"),
    since: str = typer.Option("2017-07-01", help="Sentinel-2 L2A empieza a mediados de 2017"),
    until: Optional[str] = typer.Option(None, help="YYYY-MM-DD; por defecto hoy"),
    workers: Optional[int] = typer.Option(None, help="procesos en paralelo; por defecto según el tamaño del sitio"),
    max_scene_cloud: float = typer.Option(60.0, help="nubosidad máxima de la escena completa (%)"),
    force: bool = typer.Option(False, help="recalcula fechas ya guardadas"),
):
    """Carga el histórico completo. Reanudable: repite el comando y sigue donde se quedó."""
    end = date.fromisoformat(until) if until else date.today()
    start = date.fromisoformat(since)
    t0 = time.time()
    for s in _resolve_sites(site):
        console.rule(f"[bold]{s.name}")
        st = time.time()
        for done, total, batch in backfill_mod.run(
                s, start, end, max_scene_cloud, workers, force, log=console.print):
            elapsed = time.time() - st
            rate = elapsed / max(done, 1)
            eta = timedelta(seconds=int(rate * (total - done)))
            oks = sum(1 for o in batch if o.quality == "ok")
            console.print(f"  {done}/{total} fechas · {oks}/{len(batch)} válidas en el lote · "
                          f"{rate:.1f} s/fecha · quedan ~{eta}")
        df = store.load(s.slug)
        n_ok = int((df["quality"] == "ok").sum()) if not df.empty else 0
        console.print(f"[green]{s.name}: {len(df)} fechas en la serie, {n_ok} válidas "
                      f"({timedelta(seconds=int(time.time() - st))})")
    console.print(f"\nTotal: {timedelta(seconds=int(time.time() - t0))}")


@app.command("report")
def report_cmd(site: Optional[list[str]] = typer.Option(None, "--site", "-s")):
    """Regenera el informe a partir de las series guardadas, sin descargar nada."""
    results = {}
    for s in _resolve_sites(site):
        series = store.load(s.slug)
        if series.empty:
            continue
        ok = series[series["quality"] == "ok"]
        results[s.slug] = {"site": s, "series": series, "alerts": alerts_mod.evaluate(s, series),
                           "latest": ok.iloc[-1] if not ok.empty else None,
                           "chart_b64": report.series_chart(s, series), "image_b64": None}
    html_path, json_path = report.write(results, date.today())
    console.print(f"Informe: {html_path}\nAlertas: {json_path}")


if __name__ == "__main__":
    app()
