"""Piecewise-linear comfort curves mapping a physical value to a 0..1 score."""

from __future__ import annotations

from collections.abc import Sequence

Curve = Sequence[tuple[float, float]]


def interp(curve: Curve, x: float | None) -> float | None:
    if x is None:
        return None
    pts = sorted(curve)
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
        if x0 <= x <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


# Heat index (C): comfortable up to ~24 C, steep decline through the NWS caution bands.
HEAT_STRENUOUS: Curve = ((24, 1.0), (27, 0.85), (32, 0.45), (36, 0.15), (41, 0.0))
HEAT_LIGHT: Curve = ((26, 1.0), (29, 0.85), (32, 0.6), (37, 0.25), (41, 0.0))
COLD: Curve = ((-5, 0.0), (5, 0.4), (10, 0.75), (14, 1.0))

PRECIP_PROB: Curve = ((0, 1.0), (20, 0.9), (40, 0.6), (60, 0.3), (80, 0.1), (100, 0.0))
PRECIP_MM: Curve = ((0, 1.0), (0.2, 0.85), (1, 0.5), (3, 0.15), (6, 0.0))
PRIOR_RAIN_MM: Curve = ((0, 1.0), (1, 0.85), (3, 0.5), (8, 0.15), (15, 0.0))

WIND_GENERAL: Curve = ((0, 1.0), (15, 1.0), (25, 0.75), (35, 0.45), (50, 0.1), (62, 0.0))
WIND_SENSITIVE: Curve = ((0, 1.0), (10, 1.0), (18, 0.7), (25, 0.4), (35, 0.1), (50, 0.0))

AQI: Curve = ((0, 1.0), (50, 0.95), (100, 0.6), (150, 0.25), (200, 0.05), (300, 0.0))
AQI_SENSITIVE: Curve = ((0, 1.0), (50, 0.85), (75, 0.5), (100, 0.25), (150, 0.0))

UV: Curve = ((0, 1.0), (3, 0.95), (6, 0.7), (8, 0.45), (11, 0.2))
VISIBILITY_M: Curve = ((200, 0.0), (1000, 0.3), (5000, 0.75), (10000, 0.9), (20000, 1.0))

TRAVEL_MIN: Curve = ((0, 1.0), (10, 1.0), (20, 0.8), (35, 0.55), (60, 0.25), (120, 0.0))
TRAVEL_MIN_DESTINATION: Curve = ((0, 1.0), (30, 0.95), (60, 0.7), (90, 0.45), (150, 0.15), (240, 0.0))

ROAD_DISTANCE_M: Curve = ((0, 0.2), (50, 0.35), (150, 0.65), (300, 0.85), (600, 1.0))
GREEN_SHARE: Curve = ((0, 0.3), (0.15, 0.55), (0.35, 0.8), (0.6, 1.0))
INDUSTRIAL_M: Curve = ((0, 0.2), (500, 0.5), (1000, 0.8), (2000, 1.0))

AREA_M2_EVENT: Curve = [(500, 0.2), (2000, 0.5), (10000, 0.85), (40000, 1.0)]

# Photography: total cloud cover - some cloud adds colour at golden hour; overcast blocks the sun.
SKY_GOLDEN: Curve = ((0, 0.75), (15, 0.9), (35, 1.0), (60, 0.75), (85, 0.3), (100, 0.1))
LOW_CLOUD_GOLDEN: Curve = ((0, 1.0), (25, 0.85), (50, 0.5), (80, 0.15), (100, 0.0))
