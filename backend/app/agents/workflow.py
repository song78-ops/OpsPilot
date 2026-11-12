"""Executable wrapper around the compiled LangGraph StateGraph."""

import logging
from typing import Any

from app.agents.graph import build_agent_graph
from app.agents.nodes import AgentNodes
from app.agents.state import AgentState
from app.core.exceptions import ApplicationError
from app.rag.exceptions import AgentNodeExecutionError

logger = logging.getLogger(__name__)


class AgentWorkflow:
    """Run one supervised graph execution with bounded steps."""

    def __init__(
        self,
        *,
        nodes: AgentNodes,
        max_execution_steps: int,
    ) -> None:
        self._graph, self._recursion_limit = build_agent_graph(
            nodes,
            max_execution_steps=max_execution_steps,
        )

    async def run(
        self,
        *,
        message: str,
        conversation_id: str | None,
    ) -> AgentState:
        initial: AgentState = {
            "message": message,
            "conversation_id": conversation_id,
            "executed_nodes": [],
            "node_traces": [],
            "tool_calls": [],
            "usage_parts": [],
        }
        try:
            return await self._graph.ainvoke(
                initial,
                config={"recursion_limit": self._recursion_limit},
            )
        except ApplicationError:
            raise
        except Exception as exc:
            logger.error(
                "Agent graph execution failed type=%s",
                type(exc).__name__,
            )
            raise AgentNodeExecutionError("graph") from exc

