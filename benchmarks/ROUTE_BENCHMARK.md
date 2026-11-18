# Route benchmark — shortest vs preference route

Generated 2026-11-15T23:58:46Z by `benchmarks/route_benchmark.py` · network `osm-walk-20261023-99602011` · scores `strollane-12x24-v1+bb10da45e2` · 19 trips × 12 single-dimension preferences (weight 80) · limits: 100 min, 25% detour.

"Gain" = the preference route's score on the requested dimension minus the shortest route's score (0–100 ranks within Manhattan). 5 points is the smallest difference the app describes in words (`route-story.js`). These are the router's own scores: a gain shows the engine moved its metric, **not** that a walker perceives the difference. The trip set is hand-picked, not a random sample.

## By dimension

| | Runs | Mean gain (pts) | Median gain | Gain ≥ 5 pts | Same as shortest | Mean detour | Mean overlap with shortest |
|---|---|---|---|---|---|---|---|
| Architecture | 19 | +10.9 | +10.0 | 13/19 | 6/19 | 5.8% | 0.40 |
| Nature | 19 | +11.9 | +10.0 | 12/19 | 1/19 | 4.8% | 0.39 |
| Culture | 19 | +7.7 | +2.0 | 9/19 | 6/19 | 3.5% | 0.45 |
| Quiet & Relax | 19 | +10.8 | +12.0 | 14/19 | 2/19 | 4.2% | 0.35 |
| Spatial Comfort | 19 | +9.7 | +9.0 | 15/19 | 2/19 | 4.7% | 0.33 |
| Urban Vibrancy | 19 | +5.5 | +2.0 | 7/19 | 6/19 | 2.3% | 0.53 |
| Food & Retail | 19 | +7.8 | +7.0 | 13/19 | 3/19 | 4.6% | 0.37 |
| Scenic & Visual | 19 | +2.8 | +2.0 | 7/19 | 8/19 | 2.3% | 0.54 |
| Walkability | 19 | +6.0 | +5.0 | 10/19 | 1/19 | 2.7% | 0.37 |
| Access & Safety | 19 | +9.0 | +8.0 | 14/19 | 2/19 | 5.2% | 0.33 |
| Environment | 19 | +6.4 | +4.0 | 9/19 | 6/19 | 3.3% | 0.41 |
| Transit Connectivity | 19 | +10.7 | +13.0 | 12/19 | 7/19 | 4.2% | 0.43 |
| **All** | 228 | +8.3 | +7.0 | 135/228 | 50/228 | 4.0% | 0.41 |

## By trip length (shortest-path distance)

| | Runs | Mean gain (pts) | Median gain | Gain ≥ 5 pts | Same as shortest | Mean detour | Mean overlap with shortest |
|---|---|---|---|---|---|---|---|
| short (< 1.5 km) | 72 | +4.2 | +1.0 | 24/72 | 32/72 | 2.5% | 0.64 |
| medium (1.5–3 km) | 120 | +9.4 | +7.0 | 78/120 | 17/120 | 4.6% | 0.34 |
| long (≥ 3 km) | 36 | +12.5 | +11.5 | 33/36 | 1/36 | 4.8% | 0.16 |

## Nature (Nature) by trip length

| | Runs | Mean gain (pts) | Median gain | Gain ≥ 5 pts | Same as shortest | Mean detour | Mean overlap with shortest |
|---|---|---|---|---|---|---|---|
| short (< 1.5 km) | 6 | +3.0 | +1.5 | 1/6 | 1/6 | 0.5% | 0.63 |
| medium (1.5–3 km) | 10 | +14.5 | +12.0 | 8/10 | 0/10 | 6.5% | 0.32 |
| long (≥ 3 km) | 3 | +21.0 | +24.0 | 3/3 | 0/3 | 8.1% | 0.10 |

## Quiet & Relax (Quiet & Relax) by trip length

| | Runs | Mean gain (pts) | Median gain | Gain ≥ 5 pts | Same as shortest | Mean detour | Mean overlap with shortest |
|---|---|---|---|---|---|---|---|
| short (< 1.5 km) | 6 | +7.7 | +8.0 | 5/6 | 1/6 | 4.1% | 0.46 |
| medium (1.5–3 km) | 10 | +11.3 | +12.0 | 6/10 | 1/10 | 4.1% | 0.32 |
| long (≥ 3 km) | 3 | +15.3 | +14.0 | 3/3 | 0/3 | 5.2% | 0.21 |

Routing errors: 0. Blocking QA issues on preference routes: 0. Preference routes scoring below the shortest route on the requested dimension: 0.
