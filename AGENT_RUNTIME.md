# Agent Runtime

`agent/runtime.py` — a LangGraph `StateGraph` with two nodes (`agent`, `tools`) in a loop, used by
`POST /api/agent/food-stop`.

## States

| State | Reached by | Real code path |
|---|---|---|
| `CREATED` | `run_food_stop_agent()` before the graph's first step | `runtime.py: run_food_stop_agent` |
| `RUNNING` | `agent_node`, each time the LLM is about to decide what to do next | `runtime.py: agent_node` |
| `WAITING_FOR_TOOL` | `agent_node`, when the LLM's response includes tool calls | `runtime.py: agent_node` → `route_after_agent` |
| `RETRYING` | `tools_node`, when a tool call fails with an `upstream_unavailable` error and retries remain | `runtime.py: tools_node` |
| `COMPLETED` | `agent_node`, when the LLM responds with no further tool calls | `runtime.py: agent_node` |
| `FAILED` | step budget (`MAX_STEPS=6`) or wall-clock deadline (`WALL_CLOCK_TIMEOUT_S=45`) exceeded, or a tool call exhausts its retries | `runtime.py: agent_node`, `tools_node` |
| `WAITING_FOR_USER`, `CANCELLED` | **not implemented.** This slice has no human-in-the-loop step and no cancellation endpoint. Claiming these would be fabricating states no code path reaches. | — |

## Bounded retries, timeouts, failure recovery

- Each tool call is retried up to `MAX_RETRIES=2` times, **only** when the tool's own error envelope says
  `error.type == "upstream_unavailable"` (e.g. the Open-Meteo fetch in `get_weather` times out). A tool
  reporting `invalid_input` is never retried — retrying bad input can't fix it.
- The whole run is bounded by `MAX_STEPS` agent turns and `WALL_CLOCK_TIMEOUT_S` wall-clock seconds, checked at
  the start of every `agent_node` call before spending another LLM call.
- A Python exception inside a tool (a bug, not a reported upstream failure) is caught and turned into a
  `tool_exception` error result rather than crashing the graph — the agent sees the failure as a ToolMessage
  and can adapt or give up.

## Durable state / checkpointing

`langgraph.checkpoint.sqlite.SqliteSaver` persists every graph step to `data/agent_checkpoints.db`
(gitignored — it's runtime state, not source), keyed by `thread_id = run_id`. A process restart does not lose
an in-progress run's history; re-invoking with the same `run_id` resumes from the last checkpoint. This is a
real, tested mechanism (LangGraph's own), not something built from scratch.

Note on scope: the server itself is still stateless per-request outside the agent path — only the agent graph
checkpoints. Making the rest of the server durable was not asked for and isn't done.

## Observability

Every step (LLM turn, tool call, state transition) is logged as one JSON line via `agent/tracing.py`,
printed the same way the rest of `server.py` already logs (`print(..., flush=True)` — no new log
infrastructure was introduced). The same trace is returned to the caller in the `/api/agent/food-stop`
response body for debugging. This is deliberately not OpenTelemetry/distributed tracing — there's a single
process and no distributed call graph to trace yet; that would be infrastructure for a scale this app doesn't
have.

## Feature flag and fallback

`AGENT_ENABLED` (env var, default unset/off) gates the agent path in `server.py`'s
`/api/agent/food-stop` handler. When the flag is off, **or** when `OPENAI_API_KEY` isn't configured
(`openai_key_problem()`, reused from the existing `/api/interpret` check), the endpoint transparently falls
back to the existing deterministic `recommend_food` pipeline and says so honestly in the response
(`served_by: "deterministic_fallback"`, with a `reason`). This was verified with real requests against a
running server — see `tests/test_agent.py`'s `FeatureFlagFallbackTests`.

## What was NOT verified in this environment

This development environment has no `OPENAI_API_KEY`. The graph's control flow (step budget, deadline,
retries, state transitions) is tested with the LLM call itself stubbed out — real code, real assertions, zero
network/API cost. A full real-LLM run was not exercised here; `benchmarks/agent_vs_deterministic.py` reports
this honestly as `"blocked": true` rather than fabricating numbers. Running it with a real key will produce
real agent-path latency/cost numbers without any code changes.
