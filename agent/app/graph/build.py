"""Assemble and compile the turn graph."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .nodes import Runtime, make_nodes
from .state import TurnState


def build_graph(rt: Runtime, checkpointer=None):
    nodes = make_nodes(rt)
    g = StateGraph(TurnState)
    for name, fn in nodes.items():
        g.add_node(name, fn)
    g.add_edge(START, "authorize")

    def by_route(*allowed: str):
        def router(state: TurnState) -> str:
            route = state.get("route") or allowed[0]
            return route if route in allowed else allowed[-1]
        return router

    g.add_conditional_edges("authorize", by_route("classify", "render"), {"classify": "classify", "render": "render"})
    g.add_conditional_edges("classify", by_route("retrieve", "plan"), {"retrieve": "retrieve", "plan": "plan"})
    g.add_conditional_edges("plan", by_route("retrieve", "narrate"), {"retrieve": "retrieve", "narrate": "narrate"})
    g.add_conditional_edges("retrieve", by_route("plan", "narrate"), {"plan": "plan", "narrate": "narrate"})
    g.add_conditional_edges("narrate", by_route("verify", "revalidate"), {"verify": "verify", "revalidate": "revalidate"})
    g.add_conditional_edges("verify", by_route("repair", "revalidate"), {"repair": "repair", "revalidate": "revalidate"})
    g.add_conditional_edges("repair", by_route("verify", "revalidate"), {"verify": "verify", "revalidate": "revalidate"})
    g.add_edge("revalidate", "render")
    g.add_edge("render", END)
    return g.compile(checkpointer=checkpointer)
