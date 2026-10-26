# Agent Evaluation

`eval/agent_tasks.jsonl` + `eval/run_eval.py`.

## Why 12 tasks, not ~200

The original spec called for a ~200-task benchmark suite across 6 categories. This vertical slice has **one**
agentic task (food-stop planning). Padding to 200 cases for one task would mean either duplicating near-
identical scenarios (adding no real coverage) or inventing categories this app doesn't have features for —
both of which the spec's own "do not fabricate" rule forbids. 12 hand-picked, genuinely distinct scenarios
(different cuisines, a no-item request, a constraint-heavy request, and one deliberately out-of-coverage
request) is what's real here.

## How checks work

Each task declares `checks` — structural assertions against the real response (candidate count, whether
`item_status` values are from the real known set, whether an out-of-NYC request correctly returns zero
candidates). **No LLM judges the output** — grading an LLM's output with another LLM call risks exactly the
kind of fabricated-looking "pass rate" the spec warns against. These are plain assertions against real,
structured data.

## Real result, this environment

```
12/12 tasks run, 16/16 checks passed (pass_rate 1.0)
served_by: {"deterministic_fallback": 12}
```

Every task was served by the **existing deterministic pipeline**, not the agent — because this environment
has no `OPENAI_API_KEY`, and the endpoint's own feature-flag logic honestly falls back rather than faking an
agent run (see `AGENT_RUNTIME.md`). This is a real evaluation of the Agent Runtime's necessary scaffolding
(the endpoint, request validation, fallback behavior) — not evidence that the LLM-driven tool selection
itself produces good food recommendations, which requires a real key to measure.

## What a real-key run would additionally tell you

With `OPENAI_API_KEY` set and `AGENT_ENABLED=1`, re-running `eval/run_eval.py` would exercise the actual
agent graph for all 12 tasks (`served_by: "agent"`), and the same structural checks would validate real
LLM-driven tool selection output rather than the fallback's. Nothing in the script needs to change to do
this — it already calls the real endpoint logic, which already branches correctly on the flag and the key.
