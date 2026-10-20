from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, box

from app.geo.candidates import build_places_query, dedupe, parse_places, prefilter, to_venue
from app.geo.projection import LocalProjection, angular_difference, haversine_km, initial_bearing_deg
from app.geo.spatial_context import ContextAnalyzer, NearbySource
from app.geo.wind_context import describe, upwind_sources
from app.schemas.common import Coordinates
from app.services.geocoding import GeocodeResult, decide
from app.services.osm_context import ContextFeature
from app.services.osm_places import main_tags, nominatim_to_elements, pin_requested, requested_venue, viewbox

ORIGIN = Coordinates(lat=19.1176, lon=72.9060)  # Powai
DEG_LAT_M = 111_195  # metres per degree of latitude (spherical Earth, R = 6371 km)


def offset(lat, lon, north_m=0.0, east_m=0.0):
    import math
    return lat + north_m / DEG_LAT_M, lon + east_m / (DEG_LAT_M * math.cos(math.radians(lat)))


# --------------------------------------------------------------------------- projection
def test_haversine_and_bearing():
    assert haversine_km(19.0, 72.0, 20.0, 72.0) == pytest.approx(111.2, abs=0.2)
    assert initial_bearing_deg(19.0, 72.0, 20.0, 72.0) == pytest.approx(0, abs=0.01)
    assert initial_bearing_deg(19.0, 72.0, 19.0, 73.0) == pytest.approx(90, abs=0.3)
    assert angular_difference(350, 10) == pytest.approx(20)
    assert angular_difference(90, 270) == pytest.approx(180)


def test_local_projection_distances_in_metres():
    proj = LocalProjection(ORIGIN.lat, ORIGIN.lon)
    lat, lon = offset(ORIGIN.lat, ORIGIN.lon, east_m=1000)
    x0, y0 = proj.point_xy(ORIGIN.lat, ORIGIN.lon)  # centre is rounded to 3 dp for transformer reuse
    x, y = proj.point_xy(lat, lon)
    assert x - x0 == pytest.approx(1000, rel=0.01) and abs(y - y0) < 5
    line = proj.to_local(LineString([(ORIGIN.lon, ORIGIN.lat), (lon, lat)]))
    assert line.length == pytest.approx(1000, rel=0.01)
    back = proj.to_wgs84(proj.to_local(Point(lon, lat)))
    assert back.x == pytest.approx(lon, abs=1e-7) and back.y == pytest.approx(lat, abs=1e-7)


# --------------------------------------------------------------------------- spatial context and wind
def test_context_road_industry_green():
    lat_r, lon_r = offset(ORIGIN.lat, ORIGIN.lon, east_m=200)
    lat_i, lon_i = offset(ORIGIN.lat, ORIGIN.lon, north_m=800)
    road = LineString([(lon_r, lat_r - 0.01), (lon_r, lat_r + 0.01)])  # N-S road 200 m east
    ind_lat2, ind_lon2 = offset(lat_i, lon_i, north_m=300, east_m=300)
    industrial = box(lon_i, lat_i, ind_lon2, ind_lat2)
    g_lat, g_lon = offset(ORIGIN.lat, ORIGIN.lon, north_m=250, east_m=250)
    g2_lat, g2_lon = offset(ORIGIN.lat, ORIGIN.lon, north_m=-250, east_m=-250)
    green = box(g2_lon, g2_lat, g_lon, g_lat)  # 500 x 500 m square centred on the venue
    feats = [ContextFeature("major_road", "primary", road, "LBS Marg"),
             ContextFeature("industrial", "industrial_landuse", industrial, None),
             ContextFeature("green", "park", green, None)]
    ctx = ContextAnalyzer(feats, ORIGIN.lat, ORIGIN.lon).analyze(ORIGIN.lat, ORIGIN.lon)
    assert ctx.nearest_major_road_m == pytest.approx(200, abs=5)
    assert ctx.nearest_major_road_class == "primary"
    assert ctx.nearest_industrial_m == pytest.approx(800, abs=5)
    assert ctx.industrial_within_1km is True
    # square area 250 000 m2 / buffer area pi * 500^2 ~ 785 000 m2
    assert ctx.green_share_500m == pytest.approx(250_000 / 785_398, abs=0.02)
    road_src = next(s for s in ctx.sources if s.kind == "major_road")
    assert road_src.bearing_deg == pytest.approx(90, abs=2)
    ind_src = next(s for s in ctx.sources if s.kind == "industrial")
    assert ind_src.bearing_deg == pytest.approx(0, abs=2)


def test_empty_context_is_unknown():
    ctx = ContextAnalyzer([], ORIGIN.lat, ORIGIN.lon).analyze(ORIGIN.lat, ORIGIN.lon)
    assert ctx.nearest_major_road_m is None and ctx.nearest_industrial_m is None


def test_upwind_sector_and_calm():
    src = [NearbySource("industrial", "works", 600, 10), NearbySource("major_road", "trunk", 120, 200)]
    assert [s.subtype for s in upwind_sources(src, wind_from_deg=355, wind_kmh=12)] == ["works"]
    assert upwind_sources(src, wind_from_deg=355, wind_kmh=3) == []
    assert upwind_sources(src, wind_from_deg=None, wind_kmh=12) == []
    assert upwind_sources(src, wind_from_deg=100, wind_kmh=12) == []
    assert describe(src[0]) == "industrial works ~600 m upwind"


# --------------------------------------------------------------------------- candidates
def el(osm_type, osm_id, tags, north_m=0.0, east_m=0.0, size_m=None):
    lat, lon = offset(ORIGIN.lat, ORIGIN.lon, north_m, east_m)
    e = {"type": osm_type, "id": osm_id, "tags": tags}
    if osm_type == "node":
        e.update(lat=lat, lon=lon)
    else:
        e["center"] = {"lat": lat, "lon": lon}
        if size_m:
            la2, lo2 = offset(lat, lon, size_m, size_m)
            e["bounds"] = {"minlat": lat, "minlon": lon, "maxlat": la2, "maxlon": lo2}
    return e


def test_query_contains_selectors_and_radius():
    q = build_places_query("running", ORIGIN.lat, ORIGIN.lon, 5)
    assert '["leisure"="track"]' in q and "around:5000" in q and q.startswith("[out:json]")
    assert '["leisure"="park"]["name"]' in build_places_query("running", ORIGIN.lat, ORIGIN.lon, 15)


def test_parse_places_filters_and_annotates():
    payload = {"elements": [
        el("way", 1, {"leisure": "track", "name": "IIT Track"}, 500),
        el("way", 2, {"leisure": "park"}, -400),  # unnamed park
        el("way", 3, {"leisure": "park", "name": "Private Garden Park", "access": "private"}, 300),
        el("way", 4, {"leisure": "garden", "name": "Fee Garden", "fee": "yes"}, 0, 600),
        el("way", 5, {"leisure": "park", "name": "Too Far"}, 9000),
        el("way", 6, {"amenity": "school"}, 100),
        {"type": "way", "id": 7, "tags": {"leisure": "park"}},  # no centre
    ]}
    places = {p.osm_id: p for p in parse_places(payload, "running", ORIGIN, radius_km=5)}
    assert set(places) == {1, 2, 4}
    assert places[1].selector.category == "running_track"
    assert places[2].name is None
    assert "fee" in places[4].notes[0]
    v = to_venue(places[2], "places:overpass")
    assert v.display_label == "Unnamed park (OSM way 2)"
    assert v.osm_url == "https://www.openstreetmap.org/way/2"


def test_min_area_applies_to_generic_selectors():
    payload = {"elements": [el("way", 1, {"landuse": "recreation_ground", "name": "Tiny"}, 100, size_m=20),
                            el("way", 2, {"landuse": "recreation_ground", "name": "Big"}, 200, size_m=150)]}
    names = [p.name for p in parse_places(payload, "cricket", ORIGIN, radius_km=5)]
    assert "Tiny" not in names


def test_dedupe_same_name_and_same_category():
    payload = {"elements": [
        el("way", 1, {"leisure": "park", "name": "Hiranandani Garden"}, 0, 0, size_m=200),
        el("node", 2, {"leisure": "park", "name": "Hiranandani  garden"}, 100),
        el("way", 3, {"leisure": "park"}, 50, 50),
        el("way", 4, {"leisure": "park", "name": "Other Park"}, 1500),
    ]}
    kept = dedupe(parse_places(payload, "running", ORIGIN, radius_km=5))
    assert sorted(p.osm_id for p in kept) == [1, 4]


def test_prefilter_caps_and_prefers_explicit():
    elements = [el("way", i, {"leisure": "park", "name": f"P{i}"}, i * 200) for i in range(1, 9)]
    elements += [el("way", 100 + i, {"leisure": "garden", "name": f"G{i}"}, i * 150, 300) for i in range(1, 9)]
    places = parse_places({"elements": elements}, "running", ORIGIN, radius_km=5)
    chosen = prefilter(places, 5, 6)
    assert len(chosen) == 6
    assert sum(p.selector.suitability != "explicit" for p in chosen) <= 3
    assert chosen == prefilter(list(reversed(places)), 5, 6)


# --------------------------------------------------------------------------- Nominatim fallback / requested venue
NOMI = {"osm_type": "way", "osm_id": "123", "lat": "12.9763", "lon": "77.5929", "category": "leisure",
        "type": "park", "name": "Cubbon Park", "boundingbox": ["12.968", "12.982", "77.588", "77.600"],
        "extratags": {"opening_hours": "05:00-20:00"}}


def test_nominatim_to_elements_shapes_like_overpass():
    [e] = nominatim_to_elements([NOMI, {"osm_type": "node"}])
    assert e["type"] == "way" and e["id"] == 123
    assert e["tags"]["leisure"] == "park" and e["tags"]["name"] == "Cubbon Park"
    assert e["center"] == {"lat": 12.9763, "lon": 77.5929} and "bounds" in e


def test_requested_venue_and_pinning():
    origin = Coordinates(lat=12.9763, lon=77.5929)
    target = requested_venue(NOMI, "picnic", origin)
    assert target is not None and target.uid == "osm:way:123"
    assert requested_venue({**NOMI, "category": "place", "type": "suburb"}, "picnic", origin) is None
    payload = {"elements": [
        {"type": "way", "id": 123, "center": {"lat": 12.9763, "lon": 77.5929}, "tags": {"leisure": "park",
                                                                                         "name": "Cubbon Park"}},
        {"type": "way", "id": 9, "center": {"lat": 12.98, "lon": 77.59}, "tags": {"leisure": "park", "name": "X"}},
    ]}
    others = parse_places(payload, "picnic", origin, radius_km=5)
    pinned = pin_requested(others, target, 5)
    assert [p.uid for p in pinned] == ["osm:way:123", "osm:way:9"]


def test_main_tags_and_viewbox():
    from app.geo.activity_tags import ACTIVITY_SELECTORS
    assert ("leisure", "track") in main_tags(ACTIVITY_SELECTORS["running"][0])
    w, n, e, s = viewbox(19.0, 72.0, 10)  # Nominatim viewbox order: x1,y1,x2,y2
    assert w < 72.0 < e and s < 19.0 < n
    assert haversine_km(s, 72.0, n, 72.0) == pytest.approx(20, abs=0.5)


# --------------------------------------------------------------------------- geocoding decision
def gr(label, lat, lon, imp, ptype):
    return GeocodeResult(label, label, lat, lon, imp, "relation", 1, ptype)


def test_decide_unique_clustered_ambiguous():
    assert decide([]).reason == "not_found"
    assert decide([gr("Powai", 19.11, 72.90, 0.5, "suburb")]).reason == "unique"
    near = decide([gr("Powai", 19.11, 72.90, 0.5, "suburb"), gr("Powai stn", 19.12, 72.91, 0.4, "station")])
    assert near.reason == "clustered" and near.chosen.label == "Powai"
    amb = decide([gr("Springfield IL", 39.8, -89.6, 0.6, "city"), gr("Springfield MA", 42.1, -72.6, 0.58, "city")])
    assert amb.reason == "ambiguous" and amb.chosen is None and len(amb.options) == 2


def test_decide_same_area_prefers_urban_and_urban_over_villages():
    # rival 5 km away (beyond the 3 km cluster) but within the 8 km same-area radius: the suburb wins
    same = decide([gr("Whitefield stn", 13.01, 77.77, 0.5, "station"), gr("Whitefield", 12.97, 77.75, 0.45,
                                                                             "suburb")])
    assert same.reason == "clustered" and same.chosen.label == "Whitefield"
    u = decide([gr("Indiranagar village", 26.0, 80.0, 0.4, "village"),
                gr("Indiranagar", 12.97, 77.64, 0.4, "suburb")])
    assert u.reason == "urban_preferred" and u.chosen.label == "Indiranagar" and u.options
