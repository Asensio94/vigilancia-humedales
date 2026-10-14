"""signals.json for estado-iba: the same figures the hub used to compute from the series."""
import json
from datetime import date, datetime, timezone

from shapely.geometry import MultiPolygon, Polygon, box, mapping

from humedales import config, signals
from humedales.sites import Site


def _row(day: str, ha, quality="ok") -> dict:
    return {"date": day, "water_ha": "" if ha is None else str(ha), "quality": quality}


def _octobers(*years_ha) -> list[dict]:
    rows = []
    for year, values in years_ha:
        rows += [_row(f"{year}-10-{5 + 10 * k:02d}", v) for k, v in enumerate(values)]
    return rows


def test_state_against_the_same_month_of_earlier_years():
    rows = _octobers((2022, [100, 300]), (2023, [400]), (2024, [500, 600, 700]))  # year medians 200, 400, 600
    rows += [_row("2024-09-20", 5000),                 # another month: not in the reference
             _row("2026-10-08", 480),
             _row("2026-10-12", 9000, "nublado"),       # not good: neither the latest nor the max
             _row("2026-10-13", None)]                  # no water figure
    st = signals.state(rows, date(2026, 10, 13))
    assert st["date"] == "2026-10-08" and st["water_ha"] == 480.0
    assert st["ref_ha"] == 400.0 and st["ref_years"] == [2022, 2023, 2024]
    assert st["ratio"] == 1.2 and not st["dry_ref"] and st["current"]
    assert signals.title("Doñana", st) == "Doñana: 120 % del agua normal en ese mes"


def test_too_few_years_give_no_ratio():
    rows = _octobers((2024, [400]), (2025, [500])) + [_row("2026-10-08", 450.04)]
    st = signals.state(rows, date(2026, 10, 13))
    assert st["ratio"] is None and st["ref_ha"] is None and st["ref_years"] == [2024, 2025]
    assert st["water_ha"] == 450.0 and not st["dry_ref"]
    assert signals.title("Gallocanta", st) == "Gallocanta: 450 ha de agua"


def test_usually_dry_month_gives_no_ratio():
    # A seasonal lagoon: 1000 ha in winter, almost nothing every August.
    rows = [_row(f"{y}-02-10", 1000) for y in range(2020, 2026)]
    rows += [_row(f"{y}-08-10", 2) for y in range(2020, 2026)]
    rows.append(_row("2026-08-10", 330))
    st = signals.state(rows, date(2026, 8, 20))
    assert st["dry_ref"] and st["ratio"] is None and st["ref_ha"] == 2.0
    assert signals.title("Fuente de Piedra", st) == "Fuente de Piedra: 330 ha de agua; en ese mes suele estar seca"


def test_current_until_45_days():
    rows = [_row("2026-08-29", 10)]
    assert signals.state(rows, date(2026, 10, 13))["current"]        # 45 days
    assert not signals.state(rows, date(2026, 10, 14))["current"]    # 46 days


def test_no_good_observation_no_state():
    assert signals.state([_row("2026-10-08", 10, "parcial"), _row("2026-10-09", None)], date(2026, 10, 13)) is None


def test_a_site_needs_a_quarter_of_the_wetland():
    wetland = box(0, 0, 10, 10)
    shapes = {"ZEPA_30": box(7, 0, 20, 10),       # 30 % of the wetland
              "ZEPA_25": box(-5, 0, 2.5, 10),     # exactly 25 %
              "ZEC_20": box(0, 8, 10, 20),        # 20 %: grazes the edge
              "FAR": box(50, 50, 60, 60)}
    assert signals.sites_of(wetland, shapes) == {"ZEPA_30", "ZEPA_25"}


def test_polygonal_keeps_only_areas_of_a_broken_multipolygon():
    bowtie = Polygon([(0, 0), (2, 2), (2, 0), (0, 2)])          # ring crossing itself
    collapsed = Polygon([(5, 5), (5, 5), (5, 5), (5, 5)])       # a part simplified into a point
    geom = {"type": "MultiPolygon", "coordinates": [mapping(collapsed)["coordinates"], mapping(bowtie)["coordinates"]]}
    g = signals.polygonal(geom)
    assert g.is_valid and g.geom_type in ("Polygon", "MultiPolygon") and g.area == 2.0


def _feature(geom, **props) -> dict:
    return {"type": "Feature", "properties": props, "geometry": mapping(geom)}


def test_document(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SITES_DIR", tmp_path)
    monkeypatch.setattr(config, "SERIES_DIR", tmp_path)
    monkeypatch.setattr(signals, "SITES", {
        "laguna": Site("laguna", "Laguna", ("ZEC1",), "Aragón"),
        "marisma": Site("marisma", "Marisma", ("ES1",), "Andalucía"),
        "seca": Site("seca", "Seca", ("ES2",), "Murcia"),
        "etang": Site("etang", "Étang", ("FR1",), "Centre", country="FR"),
    })
    shapes = {"laguna": box(0, 0, 1, 1), "marisma": box(10, 10, 12, 11), "seca": box(20, 20, 21, 21)}
    for slug, g in shapes.items():
        (tmp_path / f"{slug}.geojson").write_text(json.dumps(_feature(g, slug=slug)), encoding="utf-8")
    header = "site,date,water_ha,quality\n"
    (tmp_path / "laguna.csv").write_text(header + "laguna,2026-10-09,50.0,ok\n", encoding="utf-8")
    (tmp_path / "marisma.csv").write_text(header + "marisma,2026-08-01,7.0,ok\nmarisma,2026-09-01,8.0,nublado\n",
                                          encoding="utf-8")
    (tmp_path / "seca.csv").write_text(header + "seca,2026-10-01,,parcial\n", encoding="utf-8")
    natura = {"features": [_feature(box(-1, -1, 2, 2), codigo="ES0000017", nombre="ZEPA", tipo="ZEPA"),
                           _feature(box(0, 0, 1, 1), codigo="ES2430043", nombre="ZEC", tipo="ZEC"),
                           _feature(MultiPolygon([box(9, 9, 13, 12)]), codigo="ES0000024", nombre="Marisma",
                                    tipo="ZEC y ZEPA"),
                           _feature(box(20, 20, 21, 21), codigo="ES0000099", nombre="Seca", tipo="ZEPA")]}

    doc = signals.build(natura, date(2026, 10, 13), datetime(2026, 10, 13, 7, 2, 41, tzinfo=timezone.utc))

    assert (doc["source"], doc["version"], doc["generated"]) == ("vigilancia-humedales", 1, "2026-10-13T07:02Z")
    # A wetland with nothing to say still counts as watched; the French one is not sent.
    assert doc["coverage"] == {"label": "Seis humedales", "sites": ["ES0000017", "ES0000024", "ES0000099", "ES2430043"],
                               "note": signals.COVERAGE["note"]}
    assert [s["id"] for s in doc["signals"]] == ["marisma", "laguna"]   # by date
    old, new = doc["signals"]
    assert new == {
        "id": "laguna", "kind": "wetland_water", "date": "2026-10-09", "title": "Laguna: 50 ha de agua",
        "url": "https://asensio94.github.io/vigilancia-humedales/",
        "sites": [{"code": "ES0000017"}, {"code": "ES2430043"}], "municipalities": [],
        "precision": "lamina", "deadline": None, "status": "vigente", "value": {"amount": 50.0, "unit": "ha"},
        "details": {"ratio": None, "ref_ha": None, "ref_years": [], "dry_ref": False, "current": True,
                    "name": "Laguna", "point": [0.5, 0.5]},
    }
    assert old["status"] == "antiguo" and old["details"]["current"] is False
    assert old["sites"] == [{"code": "ES0000024"}] and old["details"]["point"] == [11.0, 10.5]
