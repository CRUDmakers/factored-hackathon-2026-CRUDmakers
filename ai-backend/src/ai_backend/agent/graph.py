"""Graph wiring (ARCHITECTURE §5). M1: the read path.

    START → preprocess → agent ⇄ tools → respond → END
                 └──────────(refused)──────→ respond
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from ai_backend.agent import nodes
from ai_backend.agent.state import AgentContext, AgentState


def build_graph(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    g = StateGraph(AgentState, context_schema=AgentContext)
    g.add_node("preprocess", nodes.preprocess)
    g.add_node("agent", nodes.agent)
    g.add_node("tools", nodes.run_tools)
    g.add_node("respond", nodes.respond)

    g.add_edge(START, "preprocess")
    g.add_conditional_edges("preprocess", nodes.after_preprocess, ["agent", "respond"])
    g.add_conditional_edges("agent", nodes.after_agent, ["tools", "respond"])
    g.add_conditional_edges("tools", nodes.after_tools, ["agent", "respond"])
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)
