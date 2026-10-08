"""Irrigation check on synthetic rasters and on small copies of the real source formats."""
import struct

import numpy as np
from rasterio.transform import from_origin
from shapely import to_wkb
from shapely.geometry import box

from humedales import config, irrigation as I, legal as L

# Spectra measured on Doñana, 4 Feb 2025 (medians): plastic tunnel, yellow sand, pine.
PLASTIC = dict(blue=0.177, green=0.19, red=0.184, nir=0.26, swir16=0.20)
SAND = dict(blue=0.142, green=0.22, red=0.324, nir=0.38, swir16=0.40)
PINE = dict(blue=0.03, green=0.05, red=0.04, nir=0.25, swir16=0.14)


def _px(spec, scl=5, n=1):
    return {k: np.full(n, v, np.float32) for k, v in spec.items()} | {"scl": np.full(n, scl)}


def test_plastic_rules_separate_plastic_sand_and_forest():
    for spec, expected in ((PLASTIC, True), (SAND, False), (PINE, False)):
        valid, plastic = I.plastic_rules(**_px(spec))
        assert valid[0] and plastic[0] == expected


def test_cloud_and_nodata_are_not_valid():
    assert not I.plastic_rules(**_px(PLASTIC, scl=9))[0][0]            # SCL cloud
    assert not I.plastic_rules(**_px(PLASTIC | {"blue": 0.3}))[0][0]   # bright blue
    assert not I.plastic_rules(**_px(PLASTIC | {"blue": np.nan}))[0][0]


def test_offset_check_reads_the_data_not_the_flag():
    assert I.offset_already_applied(np.array([0, 210, 280, 340, 1800]))      # 2025 scenes
    assert not I.offset_already_applied(np.array([0, 1210, 1280, 1340, 2800]))


def test_outside_mask_edge_use_and_size_filters():
    zone = np.full((60, 60), I.NOT_IRRIGABLE, np.uint8)
    zone[:, :20] = I.IRRIGABLE
    farming = np.ones_like(zone, bool)
    plastic = np.zeros_like(zone)
    plastic[10:20, 20:24] = 3     # strip glued to the irrigable land: inside the 20 m edge
    plastic[30:40, 30:40] = 3     # 1 ha block well outside
    plastic[50:52, 50:52] = 3     # 0.04 ha speck
    plastic[0:8, 40:50] = 1       # seen on a single date only
    out, stages = I.outside_mask(plastic, zone, farming)
    assert out.sum() == 100 and out[30:40, 30:40].all()
    assert stages["not_irrigable"].sum() == 40 + 100 + 4
    assert stages["away_from_edge"].sum() == 2 * 10 + 100 + 4   # 2 of the 4 strip columns survive
    # The same block on a road parcel is not farming and disappears.
    farming[30:40, 30:40] = False
    assert I.outside_mask(plastic, zone, farming)[0].sum() == 0


def test_patches_carry_parcel_and_zone():
    tr = from_origin(0, 600, 10, 10)
    mask = np.zeros((60, 60), bool)
    mask[30:40, 30:40] = True
    zones = [L.Zone(box(0, 0, 200, 600), True, False, "Zona C", "Zona C - Suelo agricola regable"),
             L.Zone(box(200, 0, 600, 600), False, False, "Zona A", "Zona A - Suelo Forestal")]
    zone, zone_idx = I.zone_rasters(zones, mask.shape, tr)
    parcels = [L.Parcel(box(250, 150, 450, 350), "21:5:0:0:12:34:5", "IV", 0)]
    parcel_idx = I.parcel_raster(parcels, mask.shape, tr)
    plastic = np.where(mask, 4, 0)
    plastic[30:35, 30:40] = 2     # half the patch seen under plastic fewer times: the mean is 3
    valid = np.full(mask.shape, 10)
    [f] = I.patches(mask, tr, plastic, valid, zone_idx, zones, parcel_idx, parcels, "t", 2025)
    p = f["properties"]
    assert p["ha"] == 1.0 and p["plastic_dates"] == 3 and p["valid_dates"] == 10
    assert p["plan_zone"] == "Zona A - Suelo Forestal" and p["sigpac_use"] == "IV"
    assert p["declared_greenhouse_share"] == 1.0 and p["declared_irrigated_share"] == 0.0
    assert p["distance_to_irrigable_m"] == 100     # x=300 to the SAR edge at x=200
    assert p["sigpac_url"].endswith("/recinfo/21/5/0/0/12/34/5.json")


GML = b"""<?xml version='1.0' encoding="UTF-8" ?>
<wfs:FeatureCollection xmlns:ms="http://mapserver.gis.umn.edu/mapserver"
  xmlns:wfs="http://www.opengis.net/wfs" xmlns:gml="http://www.opengis.net/gml">
 <gml:featureMember><ms:Zona_B_C_regable>
  <ms:msGeometry><gml:MultiPolygon srsName="EPSG:3042"><gml:polygonMember><gml:Polygon>
   <gml:outerBoundaryIs><gml:LinearRing><gml:coordinates>0,0 100,0 100,100 0,100 0,0</gml:coordinates>
   </gml:LinearRing></gml:outerBoundaryIs></gml:Polygon></gml:polygonMember></gml:MultiPolygon></ms:msGeometry>
  <ms:INFORMACIO>Zona C - Suelo agricola regable</ms:INFORMACIO><ms:SAR_1025>SI</ms:SAR_1025>
  <ms:ZonADM1025>Zona C</ms:ZonADM1025><ms:Zonif_1025>Zona C</ms:Zonif_1025>
 </ms:Zona_B_C_regable></gml:featureMember>
 <gml:featureMember><ms:Zona_B_C_regable>
  <ms:msGeometry><gml:MultiPolygon srsName="EPSG:3042"><gml:polygonMember><gml:Polygon>
   <gml:outerBoundaryIs><gml:LinearRing><gml:coordinates>100,0 200,0 200,100 100,100 100,0</gml:coordinates>
   </gml:LinearRing></gml:outerBoundaryIs></gml:Polygon></gml:polygonMember></gml:MultiPolygon></ms:msGeometry>
  <ms:INFORMACIO>Suelo Urbano-Urbanizable</ms:INFORMACIO><ms:SAR_1025>NO</ms:SAR_1025>
  <ms:ZonADM1025>Zona B</ms:ZonADM1025><ms:Zonif_1025>Zona B</ms:Zonif_1025>
 </ms:Zona_B_C_regable></gml:featureMember>
</wfs:FeatureCollection>"""


def test_parse_peorcfd_gml():
    a, b = L.parse_peorcfd_gml(GML)
    assert a.irrigable and not a.urban and a.geom.area == 10_000 and a.admin_zone == "Zona C"
    assert b.urban and not b.irrigable


def test_gpkg_geometry_header():
    wkb = to_wkb(box(0, 0, 1, 1))
    no_env = b"GP\x00\x01" + struct.pack("<i", 4258) + wkb
    xy_env = b"GP\x00\x03" + struct.pack("<i", 4258) + struct.pack("<4d", 0, 1, 0, 1) + wkb
    assert L.gpkg_to_shapely(no_env).area == 1 == L.gpkg_to_shapely(xy_env).area


def test_sigpac_zip_name_from_listing():
    page = ('<a href="21005_rec_2026_20251001_gpkg.zip">x</a><a href="21005_rec_2026_20251215_gpkg.zip">'
            '</a><a href="21005_rec_2026_20251215_shp.zip"></a><a href="210050_rec_2026_20251215_gpkg.zip">')
    assert L.sigpac_zip_url(page, "21005", 2026) == "21005_rec_2026_20251215_gpkg.zip"
    assert L.sigpac_zip_url(page, "21013", 2026) is None


def test_thresholds_documented_in_one_place():
    assert config.PLASTIC_BLUE_MAX == config.BLUE_CLOUD
