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

Production deployment/concurrency evidence will be appended after the actual rollout. No OOM-free or unlimited-concurrency guarantee is made.
