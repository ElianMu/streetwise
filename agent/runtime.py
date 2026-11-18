"""Agent Runtime: a stateful, tool-calling LangGraph agent for one real City Walk scenario — finding a food
stop that satisfies free-form constraints (cuisine/item, walk-time limit, weather-dependent seating) by calling
the Tool Registry (agent/tools.py) itself, rather than following the fixed deterministic pipeline
(routing/recommend.py's recommend_food) every time regardless of what was actually asked.

States (spec-required, all real — a state the graph never actually enters is not claimed as implemented):
  CREATED    -> the graph has a checkpointed thread but hasn't run a step yet
  RUNNING    -> the agent node is deciding what to do next
  WAITING_FOR_TOOL -> the agent asked for tool call(s); the tools node is executing them
  RETRYING   -> a tool call failed with a transient (upstream) error and is being retried, bounded by MAX_RETRIES
  COMPLETED  -> the agent produced a final answer with no further tool calls
  FAILED     -> step budget or wall-clock deadline exceeded, or an unhandled exception (e.g. a model call timing
                out). A tool that still fails after its retries does not fail the run: its error is handed back to
                the model as the tool result.
  WAITING_FOR_USER and CANCELLED are not implemented: this vertical slice has no human-in-the-loop step and no
  cancellation endpoint, so claiming them would be fabricating states no code path ever reaches.

Persistence: langgraph's SqliteSaver checkpoints every step to .agent-state/agent_checkpoints.db (outside the
statically served tree; override with AGENT_CHECKPOINT_DB), keyed by thread_id
(=run_id). The checkpoints are a durable record of each run's steps that survives a process restart. Resuming an
interrupted run is NOT implemented: run_food_stop_agent always starts from a fresh initial state (passing an existing
run_id would append a new user turn and reset the step budget, not continue the old run), and the server never
passes a run_id. Resuming would mean invoking the compiled graph with input None for that thread_id.
"""
import os
import time
import uuid
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.sqlite import SqliteSaver

from . import tracing
from .tools import TOOLS, ERR_UPSTREAM

ROOT = Path(__file__).resolve().parent.parent
# Not under data/: everything there is served as a static file, and checkpoints hold user requests and model output.
CHECKPOINT_DB = Path(os.environ.get('AGENT_CHECKPOINT_DB') or ROOT / '.agent-state' / 'agent_checkpoints.db')
MAX_STEPS = 6          # agent-node turns; bounds runaway tool-call loops
MAX_RETRIES = 2        # per tool call, only for upstream/transient errors
WALL_CLOCK_TIMEOUT_S = 45
MODEL_NAME = os.environ.get('OPENAI_MODEL', 'gpt-4o-mini')

SYSTEM_PROMPT = (
    "You are the STROLLANE NYC food-stop planning agent. The user wants a place to eat on their walk, possibly "
    "with constraints (cuisine, a specific item, a walk-time limit, weather sensitivity for outdoor seating). "
    "Use the tools to find real candidates, check real walk time with calculate_route/validate_route when a time "
    "limit was stated, check get_weather only when the request mentions weather/outdoor seating, and check "
    "verify_restaurant_menu when a specific item was requested. Never claim a menu item, rating, or walk time you "
    "did not get from a tool. When you have enough real evidence, answer with a final recommendation naming the "
    "place, why it fits, and which constraints you verified versus could not verify."
)


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    run_id: str
    status: str
    step_count: int
    trace: dict
    deadline: float


LLM_CALL_TIMEOUT_S = 30  # one model call; also capped by what is left of WALL_CLOCK_TIMEOUT_S


def _llm(timeout=LLM_CALL_TIMEOUT_S):
    from langchain_openai import ChatOpenAI
    # Without an explicit timeout the OpenAI client waits up to 10 minutes and retries twice, so one stuck call
    # would outlive the run's wall-clock deadline and hold a server capacity slot. No client-side retries: the
    # deadline, not the SDK, decides whether there is time for another attempt.
    return ChatOpenAI(model=MODEL_NAME, temperature=0, timeout=timeout, max_retries=0).bind_tools(TOOLS)


def agent_node(state: AgentState):
    trace = state['trace']
    if time.time() > state['deadline']:
        tracing.record_step(trace, 'control', 'deadline_exceeded')
        return {'status': 'FAILED'}
    if state['step_count'] >= MAX_STEPS:
        tracing.record_step(trace, 'control', 'max_steps_exceeded', step_count=state['step_count'])
        return {'status': 'FAILED'}
    tracing.record_step(trace, 'state', 'RUNNING', step_count=state['step_count'])
    remaining = state['deadline'] - time.time()
    response = _llm(timeout=max(1.0, min(LLM_CALL_TIMEOUT_S, remaining))).invoke([SystemMessage(SYSTEM_PROMPT)] + state['messages'])
    next_status = 'WAITING_FOR_TOOL' if getattr(response, 'tool_calls', None) else 'COMPLETED'
    tracing.record_step(trace, 'llm', 'agent_turn', tool_calls=len(getattr(response, 'tool_calls', None) or []),
                         output=getattr(response, 'content', ''))
    return {'messages': [response], 'status': next_status, 'step_count': state['step_count'] + 1}


def tools_node(state: AgentState):
    trace = state['trace']
    last = state['messages'][-1]
    by_name = {t.name: t for t in TOOLS}
    outputs = []
    for call in last.tool_calls:
        tool_fn = by_name.get(call['name'])
        if tool_fn is None:
            outputs.append(ToolMessage(content=f'Unknown tool {call["name"]}', tool_call_id=call['id']))
            continue
        attempt, result = 0, None
        while True:
            t0 = time.time()
            try:
                result = tool_fn.invoke(call['args'])
            except Exception as e:  # a tool contract violation, not an upstream outcome
                result = {'ok': False, 'error': {'type': 'tool_exception', 'message': str(e)[:400]}}
            dur_ms = round((time.time() - t0) * 1000, 1)
            ok = isinstance(result, dict) and result.get('ok')
            transient = (not ok) and isinstance(result, dict) and result.get('error', {}).get('type') == ERR_UPSTREAM
            if ok or not transient or attempt >= MAX_RETRIES or time.time() > state['deadline']:
                tracing.record_step(trace, 'tool', call['name'], input=call['args'], ok=ok, duration_ms=dur_ms,
                                     attempt=attempt, output=result if ok else result.get('error'))
                break
            attempt += 1
            tracing.record_step(trace, 'state', 'RETRYING', tool=call['name'], attempt=attempt, duration_ms=dur_ms)
        outputs.append(ToolMessage(content=str(result), tool_call_id=call['id']))
    return {'messages': outputs, 'status': 'RUNNING'}


def route_after_agent(state: AgentState):
    if state['status'] in ('FAILED', 'COMPLETED'):
        return END
    return 'tools'


def build_graph():
    CHECKPOINT_DB.parent.mkdir(parents=True, exist_ok=True)
    graph = StateGraph(AgentState)
    graph.add_node('agent', agent_node)
    graph.add_node('tools', tools_node)
    graph.set_entry_point('agent')
    graph.add_conditional_edges('agent', route_after_agent, {'tools': 'tools', END: END})
    graph.add_edge('tools', 'agent')
    with SqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as saver:
        pass  # validate the path is writable before compiling; the real saver is opened per-run below
    return graph


_GRAPH = build_graph()


def initial_message(user_request, origin=None):
    """The user's turn. The agent has no geocoder, so the caller's real position is stated explicitly; without
    one the agent is told not to invent coordinates."""
    if origin:
        return HumanMessage(f"{user_request}\n\n[Caller's current location from the device: lat={origin['lat']:.6f}, "
                            f"lon={origin['lon']:.6f}. Use exactly these coordinates for search_places and as the route "
                            "origin; do not substitute other coordinates.]")
    return HumanMessage(f"{user_request}\n\n[No location was provided. Do not call tools with guessed coordinates; "
                        "say that a location is needed.]")


def run_food_stop_agent(user_request, run_id=None, origin=None):
    """Execute the agent for one request. origin = {'lat', 'lon'} of the caller (validated by the server).
    Returns {run_id, status, final_answer, trace}.
    status is one of COMPLETED / FAILED. Always a new run: this does not resume an earlier run_id (see module
    docstring).
    """
    run_id = run_id or str(uuid.uuid4())
    trace = tracing.new_trace(run_id)
    tracing.record_step(trace, 'state', 'CREATED')
    with SqliteSaver.from_conn_string(str(CHECKPOINT_DB)) as checkpointer:
        compiled = _GRAPH.compile(checkpointer=checkpointer)
        initial = {'messages': [initial_message(user_request, origin)], 'run_id': run_id, 'status': 'CREATED',
                   'step_count': 0, 'trace': trace, 'deadline': time.time() + WALL_CLOCK_TIMEOUT_S}
        try:
            final_state = compiled.invoke(initial, config={'configurable': {'thread_id': run_id}})
        except Exception as e:
            tracing.record_step(trace, 'control', 'unhandled_exception', error=str(e))
            return {'run_id': run_id, 'status': 'FAILED', 'final_answer': None, 'trace': tracing.finalize(trace, 'FAILED')}
    status = final_state.get('status', 'FAILED')
    final_answer = None
    if status == 'COMPLETED':
        for m in reversed(final_state['messages']):
            if getattr(m, 'content', None) and not getattr(m, 'tool_calls', None):
                final_answer = m.content
                break
    tracing.finalize(trace, status)
    return {'run_id': run_id, 'status': status, 'final_answer': final_answer, 'trace': trace}
