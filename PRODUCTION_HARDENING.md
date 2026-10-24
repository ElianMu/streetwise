# Production capacity and evidence follow-up

This follows the phase-one acceptance in `URBAN_RELEASE_VALIDATION.md`. Measurements below are actual runs, not a claim that one local workload establishes production capacity.

## Lossless geometry and admission (2026-10-24)

- Original graph, scores, vertices, projection, routing algorithm and 12 dimension definitions are unchanged. Coordinates use float64 arrays (3,578,640 bytes including offsets); metric coordinates materialize on demand. Each coordinate cache holds at most 256 lines / 8,192 vertices.
- All 61,047 original polylines and their projected vertices compare exactly with the shipped graph. A separately saved pre-change baseline of 34 routes across default, Nature, Architecture, opposite complaint-density and opposite waterfront requests has identical geometry, ordered edges, distance, duration, scores, coverage and maneuver content. Only random route/maneuver IDs were excluded from comparison.
- Heavy POST requests share two active slots and three FIFO waiting slots. Route waits expire after 12 seconds; other heavy requests after 25 seconds. Full/expired queues return HTTP 503 `capacity_busy` with `Retry-After: 3`. Slots release on errors. Health/status, AI interpretation and navigation progress do not wait behind this queue.
- `/api/status` reports active/queued/rejected requests, cache budgets, runtime version, process RSS/high-water mark, cgroup current/peak/limit/events and anonymous/file/kernel memory. A missing field on a platform means unavailable, not zero.

Local fresh-process Python 3.12.14, same graph and source snapshots:

| Workload | Before RSS KiB | After RSS KiB |
| --- | ---: | ---: |
| Graph and original scores | 377,900 | 306,780 |
| Default complaint field | 379,888 | 308,896 |
| Manhattan places + citywide parks/restrooms | 396,756 | 329,152 |
| First all-borough DOHMH load | 407,912 | 340,200 |
| Two simultaneous fresh-evidence food recommendations | 413,464 | 345,296 |

`python scripts/check_capacity.py` exercises the first Brooklyn permit lookup and three concurrent real route clients, without paid AI calls or website mocks. Actual process peak was 356,232 KiB (347.9 MiB), with five routes per client, two active slots and no rejected clients. CI fails above 448 MiB process peak, reserving 64 MiB against a 512 MiB instance. This does not include the host's cgroup file-cache budget; deployment validation must check that separately.

Validation: full Python suite 234 tests passed before one additional slot-release regression was added; all four capacity tests then passed. All nine JavaScript/DOM scripts passed. CI runs the entire final suite and a separate fresh-process memory check. Existing unclosed-file ResourceWarnings are visible and were not suppressed.

Production PR [#24](https://github.com/ElianMu/streetwise/pull/24) passed CI (235 Python tests, nine JS scripts and the isolated memory check), merged and deployed as `f51145c6c2bfa868b99c6c445c02189ebea336bc`. Render reports Python 3.14.8. Three simultaneous real complaint-aware route requests all returned HTTP 200/five routes in 11.159, 11.077 and 14.274 seconds. Sampled RSS peaked at 344,980 KiB (336.9 MiB); process start time stayed constant and OOM/kill counters stayed zero. This is a small bounded workload, not an unlimited-concurrency guarantee. A status attempt during rollout timed out before subsequent successful checks.

Cgroup total remained close to 512 MiB: after this batch it included 340,348,928 anonymous bytes and 178,122,752 file-cache bytes, with no OOM. The `max` counter increased as memory was reclaimed; it is not an OOM counter. Total cgroup usage must not be described as free headroom merely by subtracting process RSS.

## Place evidence, menu latency and frontend follow-up

- Rebuilt DOHMH associations using the same shipped source snapshots, without claiming a fresh source download. Require normalized address, specific name agreement and <60 m, with exactly one match. Of 5,164 previous OSM links, 3,326 now meet the stricter evidence rule; 1,949 assignments changed, including reassignment. These include uncertain matches, not 1,949 proven false identities. Uncertain entities remain separate, so source records increase from 14,517 to 16,456 food records. All retained OSM permit links are tested against the real source. Receipt: `data/urban/research/permit-link-repair.json`.
- Permit-only listings without an actual inspection or public-facing website are excluded from default food discovery/recommendations and public restaurant stops. Pinterest NYC's `1900-01-01` is a placeholder, now displayed as no actual inspection. This rule does not assert that every such venue is private, or that every inspected business is public. Explicit OSM private/no/permit restrictions are excluded; future source refreshes retain access tags.
- Algonquin uses its existing `lpc:LP-01547` and mapped official website for historic property identity corroboration. The evidence scope explicitly excludes current hotel operation, room types, prices and availability. No hotel stock was invented.
- PH holiday exceptions now return unknown when no authoritative holiday calendar exists; they are not silently skipped. Invalid clock values are rejected in Python and JS. Mapped hours remain non-live evidence.
- Six menu candidates/three workers now share one 10-second remaining-time budget across website checks, including queued tasks. Website/DNS availability can still affect elapsed time; 403/404, missing sites, unreadable pages and no confirmed menu item remain explicit outcomes. Cache successful first-party documents for five minutes, bounded at 8 MiB/32 documents, reuse across dishes, and preserve the actual document-read timestamp. Bound PDF decompression. Positive item receipts retain their existing 12-hour expiry; frontend cards/navigation now also check expiry and deduplicate in-flight item checks.
- Generic nearby food discovery now queries bounded server shortlists instead of downloading the complete restaurant file; item-specific discovery already uses server recommendations. The complete published source snapshot remains the fallback for a failed API or unusually long search area, with a diagnostic. The snapshot grew as uncertain merges were split; payload improvement is measured per user flow, not by deleting real records.
- A failed 2.5-second AI status probe no longer permanently selects local preview. An unknown configuration triggers a real parse on planning. The UI distinguishes configured from a successful real request; an actual failure still shows Limited Local Preview and the next plan retries.
- Local final checks: 243/243 Python tests, eleven JS/DOM scripts, fresh-process memory check (369,808 KiB peak, three real clients). Three first-run menu fixture failures exposed cached documents leaking between mocked scenarios; isolate each scenario's new document cache and rerun all original assertions. No tests were skipped or relaxed.

Still external or outside the current graph: authorized ratings/reviews and lodging providers; full public-access/operating-hours freshness; four-borough hotel/attraction discovery coverage and pedestrian graphs; physical GPS field validation. Optional vendor keys do not implement the still-missing lodging adapter. OPENAI_API_KEY normalization/control-character regressions remain in the full suite; production AI must be confirmed with an actual parse after rollout, not inferred from the configured flag.
