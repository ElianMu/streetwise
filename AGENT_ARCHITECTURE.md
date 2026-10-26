# Agent Architecture

Scope: one real, complete vertical slice — not a framework for hypothetical future agents, and not a shallow
pass over the full 16-section AI Agent Infrastructure spec. See the session's repository audit (summarized
below) for why the full spec's scope doesn't fit this codebase as a 1:1 implementation.

## What this app had before this change

A deterministic routing/recommendation engine: A*/Dijkstra pedestrian routing (`routing/engine.py`), a
multi-stop itinerary planner (`routing/itinerary.py`), food recommendation with real menu verification
(`routing/recommend.py`, `routing/menu.py`), and exactly **one** LLM call in the whole system — a single-shot,
schema-constrained OpenAI call (`server.py:688`, `call_llm()`) that turns free-text trip preferences into
structured JSON. No loop, no model-driven tool selection, no multi-step planning.

## What this change adds

A real, tool-calling LangGraph agent for one concrete scenario: **food-stop planning from a free-text
request** (`POST /api/agent/food-stop`). Given something like *"a quiet cafe within a 10 minute walk with
vegan options,"* the agent — not a fixed sequence of calls — decides which tools to call and in what order:

- `search_places` — real place discovery (wraps `routing/places.py`'s `PlaceStore.search`)
- `get_weather` — real Open-Meteo forecast fetch + `routing/weather.py`'s assessment (same source as the
  client's own `weather.js`)
- `calculate_route` — a real OSM pedestrian route (wraps `routing/engine.py`'s `RoutePlanner.plan`)
- `validate_route` — checks a returned route against the caller's own stated time/distance limit
- `verify_restaurant_menu` — real official-site menu evidence (wraps `routing/menu.py`'s `verify`, SSRF-guarded,
  cached)

This is a genuine behavioral difference from the existing deterministic pipeline (`routing/recommend.py`'s
`recommend_food`, used by `/api/recommend/food`), which always runs the same fixed sequence regardless of what
was actually asked. The agent only calls `get_weather` when the request mentions weather/outdoor seating, only
calls `verify_restaurant_menu` when a specific item was named, etc. — see the system prompt in
`agent/runtime.py`.

## Why not the full 16-phase spec

The original spec assumed a system with multiple agentic tasks worth a shared Runtime, a 200-case eval suite,
distributed tracing infrastructure, SQLite checkpointing for long-running multi-step tasks, and a CI/CD
pipeline with Docker. This codebase has **one** agentic task. Building all of that for one task would mean
either inventing complexity to match the spec's shape (explicitly forbidden — "do not fabricate," "do not
hardcode outputs to pass benchmark cases") or turning the whole app into a tool-calling agent, which nobody
asked for and which risks the deterministic, auditable routing behavior the rest of this project protects.

What was built instead, scoped to this one real task:

| Spec phase | What's real here | Where |
|---|---|---|
| Phase 1: Agent Runtime, explicit states | Real: CREATED/RUNNING/WAITING_FOR_TOOL/RETRYING/COMPLETED/FAILED, all actually reached. `WAITING_FOR_USER`/`CANCELLED` are **not** reached by this slice (no human-in-the-loop step exists) — not claimed | `agent/runtime.py` |
| Phase 2: Tool Registry | Real: 5 tools, uniform `{ok, data}` / `{ok: False, error}` envelope | `agent/tools.py` |
| Phase 3: durable state | Real: LangGraph `SqliteSaver` checkpoints every step to `data/agent_checkpoints.db`, keyed by `run_id` | `agent/runtime.py` |
| Phase 4: observability | Real but minimal: structured JSON trace lines per step (tool/LLM turn/state transition), no new log destination | `agent/tracing.py` |
| Phase 5: evaluation | Real but small: 12 hand-written scenarios, checked structurally (not LLM-judged) | `eval/` |
| Phase 6: reliability | Real: bounded retries (upstream errors only), step budget, wall-clock timeout | `agent/runtime.py` |
| Phase 7: performance | Real baseline numbers for the deterministic path and the real Admission-gate concurrency sweep; agent-path numbers honestly blocked without an `OPENAI_API_KEY` | `benchmarks/` |
| Phase 8: CI/CD | Not changed. Docker/K8s would be pure overhead for a stdlib `http.server` app already deployed to Render with 4 real GitHub Actions workflows | — |

## Everything preserved

The 12 Experience Dimensions, OSM pedestrian routing, City Walk itinerary planning, interactive maps, GPS
navigation, and `/api/recommend/food` are all unchanged. The new code is additive and sits behind the
`AGENT_ENABLED` feature flag (default off) with the existing deterministic pipeline as the automatic fallback
— see `AGENT_RUNTIME.md`.
