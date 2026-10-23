# Current handoff — center-map update

Read `IMPLEMENTATION_REPORT.md` first. Implemented: dual-mode single-map UI, real Midtown pilot, official tree source, complete scans, section evidence shared with candidate ranking/profile, GPS states, section exports. Calculated raw Nature/Architecture proxies are working; calibrated scores still NULL. Next: browser/WebGL/device acceptance, source-specific buffer/calibration research, true pedestrian graph-edge matching and optimization, remaining ten data models. Do not erase these boundaries by inventing 0–100 scores.

The original engineering roadmap follows; items may now be partially implemented. Current implementation report is authoritative.

---

# STREETWISE · NYC — Codex implementation brief (continue from v0.4)

**Do not re-design the UI from scratch.** Preserve existing dark + lime style, Manhattan MapLibre/Kepler data access, and the three-column layout. Do not claim full 12-dimensional routing until the computation and validation are real.

The detailed user product requirements are the authoritative spec. Work on the v0.4 codebase, not old v0.2/v0.3 files. First run the tests and read `README.md` and `METHODOLOGY.md`.

## P0 — Fix research foundation before polishing

1. Formalize the 12 prescribed dimensions and their operational measures, source versions, CRS, field mappings, covariate leakage, effect ranges, missingness, and calibration; maintain the exact dimension labels and order.
2. Generate verified pedestrian **edge-level** scores with appropriate corridor/view/sound/air influence mechanisms; document alternative buffer widths and sensitivity analyses. Preserve null when unavailable.
3. Build cached per-edge spatial evidence on a vetted OSM/Valhalla-compatible network; do not use NYC Street Centerline as an automatically walkable graph. Validate topology, crossings, sidewalk access and accessibility tags.
4. Only publish normalized 0–100 objective scores after a calibration dataset and reproducible tests exist. Distinguish from user importance weights (0–100), desired direction, and route match. Avoid double counting correlated dimensions.

## P1 — Real multiobjective optimization

1. Implement a tested backend graph-edge path solver (Dijkstra/A* / multi-label constrained shortest path) with travel-time cap, detour limit, pedestrian access restrictions, and per-edge experience costs. Current candidate re-ranking alone is insufficient.
2. Compare against fastest baseline, generate up to three *geometrically distinct* feasible results without hardcoded labels, show the actual count, and decline when fewer are available.
3. When optimizing under unverified step-free access or stair avoidance, refuse a safety claim and withhold recommendations unless source coverage is sufficient.
4. Use one immutable route-result payload for map geometry, evidence values, candidate ranking, explanation and POIs. Retain origin/destination and unchanged constraints during follow-ups. If the best path remains identical, say so explicitly.

## P2 — Reliability + E2E

1. Replace the local preview parser in deployed mode with explicit authenticated/validated LLM JSON schema; ask clarifications on conflicting intent, show failure clearly, and preserve user state transactionally.
2. Cache and retry public GIS services with source dates and partial-coverage indicators; route-local OSM POIs should include ways/relations with real geometry when supported (no invented POIs).
3. Check weather timestamp and GPS permission flow, especially no-GPS fallback; weather is contextual unless a street-scale link is calibrated.
4. Add tests with geographically accurate Manhattan fixtures and mocked API error/partial/timeout/duplicate states, plus live staging smoke with declared endpoints and exact recorded responses. Add accessibility audit and route difference sensitivity tests.

## Minimum acceptance

- Exact 12 dimension labels and unchanged 3-column aesthetic.
- Text request modifies structured preferences; optional slider changes update state; 0 importance excludes a dimension, negative experience intent uses separate direction, default dimensions stay explicitly 'unexpressed'.
- Every displayed route is sourced from a pedestrian path solver, meets hard constraints, is geometrically distinct, and has a correct map highlight.
- Each displayed evidence score maps to reproducible records and deterministic code; no random scores; unknown is Not Available (never 0 by default).
- After a follow-up, rerun true optimization on altered edge costs; not merely relabel existing paths.
- Verified E2E tests and an explicit Implemented/Partial/Unavailable report.
