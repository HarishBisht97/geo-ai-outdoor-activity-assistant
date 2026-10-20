# Scoring rules

Safety filters run **before** scoring. An excluded slot has `score = null` and cannot win.

## Thresholds (with sources)

From `app/ranking/thresholds.py`:

| Quantity | Caution | Exclude | Source |
| --- | --- | --- | --- |
| Heat index | 27 °C (32 °C extreme caution) | 41 °C strenuous / 46 °C light | [NWS heat index](https://www.weather.gov/safety/heat-index) |
| US AQI | 51 moderate (sensitive: caution); 101 USG | 151 unhealthy (sensitive); 201 everyone; 101+ sensitive+strenuous | [EPA AQI](https://www.airnow.gov/aqi/aqi-basics/) |
| Gusts | 75% of activity limit | min(activity limit, 62 km/h gale) | Beaufort |
| Rain | ≥60% probability | ≥4 mm/h if the activity excludes heavy rain | WMO-style |
| Thunder | — | WMO codes 95/96/99 in the slot ± activity buffer | NWS “when thunder roars” |
| UV | 6 high / 8 very high | scored, not a hard exclude | WHO UV index |

Heat-sensitive, children and older adults use lower heat limits. Respiratory / children / elderly are air-sensitive.

## Score

For available components \(s_i \in [0,1]\) with weights \(w_i\):

\[
\text{total} = 100 \times \frac{\sum w_i s_i}{\sum w_i\text{ available}} \times \bigl(1 - 0.5 \times \text{missing weight share}\bigr)
\]

A missing component is omitted and the total is reduced by half of its weight share. Completeness ≥0.9 → confidence `high`; ≥0.7 `medium`; else `low`.

Weights are activity-specific (`app/ranking/activities.py`) and normalised at scoring time. Running emphasises heat and air; cricket emphasises rain and surface; photography emphasises sky and golden hour.

## Ranking key (ascending)

1. Not recommendable (`excluded` / `unverified`) after recommendable.
2. Higher total first (rounded to 0.5).
3. Higher safety margin.
4. Shorter known travel; unknown travel last.
5. Shorter straight-line distance.
6. Venue id (stable).

The same evidence always produces the same order.
