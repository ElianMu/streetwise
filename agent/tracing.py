"""Structured execution tracing for the Agent Runtime.

Each step emits one JSON line (to stdout, same as the rest of server.py's logging — no new log destination) and
is appended to the in-memory trace returned to the caller. Never logs raw API keys or full user free text beyond
a short preview; never logs exact GPS history beyond the single point a tool call used.
"""
import json
import time


def new_trace(run_id):
    return {'run_id': run_id, 'steps': [], 'started_at': time.time()}


def _preview(value, limit=160):
    s = str(value)
    return s if len(s) <= limit else s[:limit] + '…'


def record_step(trace, kind, name, **fields):
    step = {'t_ms': round((time.time() - trace['started_at']) * 1000, 1), 'kind': kind, 'name': name}
    for k, v in fields.items():
        step[k] = _preview(v) if k in ('input', 'output', 'error') else v
    trace['steps'].append(step)
    print(json.dumps({'agent_trace': trace['run_id'], **step}, default=str), flush=True)
    return step


def finalize(trace, outcome):
    trace['outcome'] = outcome
    trace['duration_ms'] = round((time.time() - trace['started_at']) * 1000, 1)
    return trace
