"""Each country's report in its own language, with the alert JSON left canonical."""
from datetime import date, timedelta

import pandas as pd

from humedales import alerts, i18n, metodologia
from humedales.sites import SITES, site_text


def test_same_keys_in_every_language():
    assert set(i18n.UI["fr"]) == set(i18n.UI["es"])


def test_french_numbers():
    assert i18n.n(46709, "fr") == "46 709"
    assert i18n.n(46709, "es") == "46.709"
    assert i18n.p(0.15, "fr") == "15 %"


def test_every_french_site_has_french_text():
    for s in SITES.values():
        if s.country == "FR":
            assert site_text(s, "fr") != (s.name, s.region, s.notes), s.slug


def _drying_series() -> pd.DataFrame:
    """Eight years of 1000 ha around this date, then 100 ha now."""
    rows = []
    today = date(2026, 6, 1)
    for y in range(2018, 2026):
        for k in (-10, 0, 10):
            rows.append({"date": date(y, 6, 1) + timedelta(days=k), "water_ha": 1000.0})
    for k in (0, 5, 10):
        rows.append({"date": today - timedelta(days=k), "water_ha": 100.0})
    df = pd.DataFrame(rows)
    df["quality"] = "ok"
    df["ndci_mean"] = df["ndti_mean"] = 0.0
    df["bloom_frac"] = 0.0
    return df


def test_alert_in_french_and_json_canonical():
    out = alerts.evaluate(SITES["grand-lieu"], _drying_series())
    drying = next(a for a in out if a.kind == "desecacion")
    assert drying.text("fr").startswith("Surface en eau de 100 ha")
    assert drying.text("es") == drying.message and drying.message.startswith("Lámina")
    assert "translations" not in drying.to_dict()


def test_method_section_in_french():
    html = metodologia.section(None, "FR", "fr")
    assert "Méthode de calcul" in html and "Glossaire des sigles" in html
    assert "Cómo se calcula" not in html
