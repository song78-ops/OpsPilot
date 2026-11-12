"""True LangGraph StateGraph for supervised dynamic routing."""

from langgraph.graph import END, START, StateGraph

from app.agents.nodes import AgentNodes
from app.agents.state import AgentState


def route_intent(state: AgentState) -> str:
    """Return a valid graph branch without using keyword rules."""
    intent = state.get("intent", "clarification")
    return {
        "knowledge_query": "knowledge",
        "ticket_request": "ticket_agent",
        "general_chat": "chat",
        "clarification": "clarification",
    }.get(intent, "clarification")


def route_ticket_tools(state: AgentState, *, max_tool_calls: int) -> str:
    """Continue the bounded tool loop only when tool calls remain."""
    calls = state.get("pending_tool_calls", [])
    count = int(state.get("ticket_tool_call_count", 0))
    return "tools" if calls and count + len(calls) <= max_tool_calls else "done"


def build_agent_graph(nodes: AgentNodes, *, max_execution_steps: int):
    """Compile the single-pass supervisor graph."""
    graph = StateGraph(AgentState)
    graph.add_node("supervisor", nodes.supervisor)
    graph.add_node("knowledge", nodes.knowledge)
    graph.add_node("chat", nodes.chat)
    graph.add_node("ticket_agent", nodes.ticket_agent)
    graph.add_node("ticket_tools", nodes.ticket_tools)
    graph.add_node("clarification", nodes.clarification)

    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_intent,
        {
            "knowledge": "knowledge",
            "ticket_agent": "ticket_agent",
            "chat": "chat",
            "clarification": "clarification",
        },
    )
    graph.add_edge("knowledge", END)
    graph.add_edge("chat", END)
    graph.add_edge("clarification", END)
    graph.add_conditional_edges(
        "ticket_agent",
        lambda state: route_ticket_tools(
            state,
            max_tool_calls=nodes.max_tool_calls,
        ),
        {
            "tools": "ticket_tools",
            "done": END,
        },
    )
    graph.add_edge("ticket_tools", "ticket_agent")
    return graph.compile(), max_execution_steps

