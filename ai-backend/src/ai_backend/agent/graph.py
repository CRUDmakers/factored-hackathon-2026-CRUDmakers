"""Graph wiring (ARCHITECTURE §5).

    START → intake ─(pending + yes)→ mark_executing → execute_write → verify → respond
              │                                         └(unknown)→ reconcile ─┘
              ├─(pending + no / expired)→ respond         (unknown/mismatch)→ handoff
              │   a batch of payments loops verify → mark_executing until its queue is empty
              └→ preprocess → agent → policy_gate ─(reads)→ tools → escalation_check → agent
                                        ├(payment)→ prepare_write → respond (confirm?)
                                        └(escalate)→ handoff → respond → END

Branching nodes set `next_step`; `nodes.route` follows it.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ai_backend.agent import nodes
from ai_backend.agent.state import AgentContext, AgentState

EDGES: dict[str, list[str]] = {
    "intake": ["preprocess", "mark_executing", "reconcile", "respond"],
    "preprocess": ["agent", "handoff", "respond"],
    "agent": ["policy_gate", "handoff", "respond"],
    "policy_gate": ["tools", "prepare_write", "handoff", "agent", "respond"],
    "tools": ["escalation_check", "handoff", "respond"],
    "escalation_check": ["agent", "handoff"],
    "prepare_write": ["agent", "handoff", "respond"],
    "mark_executing": ["execute_write"],
    "execute_write": ["verify", "reconcile", "mark_executing", "respond"],
    "reconcile": ["verify", "handoff"],
    "verify": ["handoff", "mark_executing", "respond"],
    "handoff": ["respond"],
}


def build_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    g = StateGraph(AgentState, context_schema=AgentContext)
    g.add_node("intake", nodes.intake)
    g.add_node("preprocess", nodes.preprocess)
    g.add_node("agent", nodes.agent)
    g.add_node("policy_gate", nodes.policy_gate)
    g.add_node("tools", nodes.run_tools)
    g.add_node("escalation_check", nodes.escalation_check)
    g.add_node("prepare_write", nodes.prepare_write)
    g.add_node("mark_executing", nodes.mark_executing)
    g.add_node("execute_write", nodes.execute_write)
    g.add_node("reconcile", nodes.reconcile)
    g.add_node("verify", nodes.verify)
    g.add_node("handoff", nodes.handoff)
    g.add_node("respond", nodes.respond)

    g.add_edge(START, "intake")
    for node, targets in EDGES.items():
        g.add_conditional_edges(node, nodes.route, targets)
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)
