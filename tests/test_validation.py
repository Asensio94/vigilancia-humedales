import pytest
from shapely.geometry import box

from humedales import validation


def _fc(*has):
    return {"features": [{"properties": {"id": f"p{k}", "ha": ha}} for k, ha in enumerate(has)]}


def test_precision_counts_and_skips_doubtful():
    fc = _fc(4.0, 2.0, 1.0, 3.0)
    labels = {"p0": {"label": "invernadero"}, "p1": {"label": "cultivo"},
              "p2": {"label": "no_agricola"}, "p3": {"label": "dudoso"}}
    st = validation.precision(fc, labels)
    assert st["labelled"] == 4
    assert st["precision_patches"] == pytest.approx(1 / 3)
    assert st["precision_ha"] == pytest.approx(4 / 7)
    assert st["farmland_patches"] == pytest.approx(2 / 3)
    assert st["farmland_ha"] == pytest.approx(6 / 7)


def test_precision_without_labels():
    st = validation.precision(_fc(1.0), {})
    assert st["precision_patches"] is None and st["farmland_ha"] is None


def test_chip_bbox_is_square_and_has_a_minimum():
    small = validation.chip_bbox(box(0, 0, 10, 20))
    assert small[2] - small[0] == small[3] - small[1] == 300
    big = validation.chip_bbox(box(0, 0, 1000, 500))
    assert big[2] - big[0] == big[3] - big[1] == pytest.approx(1400)
    assert (big[0] + big[2]) / 2 == 500 and (big[1] + big[3]) / 2 == 250


def test_outline_flips_y_into_pixels():
    path = validation.outline_svg_path(box(0, 0, 50, 50), (0, 0, 100, 100), 200)
    pts = {tuple(map(float, p.split(","))) for p in path[1:-2].split(" L")}
    assert pts == {(100.0, 200.0), (100.0, 100.0), (0.0, 100.0), (0.0, 200.0)}


def test_read_labels_rejects_unknown(tmp_path):
    path = tmp_path / "x.csv"
    validation.write_labels(path, [{"patch_id": "a", "ha": 1, "label": "invernadero", "note": ""}])
    assert validation.read_labels(path)["a"]["label"] == "invernadero"
    validation.write_labels(path, [{"patch_id": "a", "ha": 1, "label": "pozo", "note": ""}])
    with pytest.raises(ValueError):
        validation.read_labels(path)


def test_pnoa_url_asks_for_png():
    url = validation.pnoa_url("PNOA2022", (0, 0, 300, 300), 400)
    assert "format=image%2Fpng" in url and "layers=PNOA2022" in url
