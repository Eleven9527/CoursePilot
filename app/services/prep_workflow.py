"""Persist a human review checkpoint for each teaching draft."""

from threading import Lock
from typing import Literal, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.core import database

Decision = Literal["approve", "reject"]


class ReviewState(TypedDict, total=False):
    draft_id: str
    decision: Decision


def _await_review(state: ReviewState) -> ReviewState:
    decision = interrupt({"draft_id": state["draft_id"], "status": "pending_review"})
    if decision not in ("approve", "reject"):
        raise ValueError("Invalid review decision")
    return {"decision": decision}


_workflow = StateGraph(ReviewState)
_workflow.add_node("await_review", _await_review)
_workflow.add_edge(START, "await_review")
_workflow.add_edge("await_review", END)
_lock = Lock()


def review_checkpoint(draft_id: str, decision: Decision | None = None) -> Decision | None:
    config = {"configurable": {"thread_id": draft_id}}
    path = database.settings.data_dir / "prep-checkpoints.sqlite"
    with _lock, SqliteSaver.from_conn_string(str(path)) as saver:
        graph = _workflow.compile(checkpointer=saver)
        state = graph.get_state(config)
        if not state.values:
            graph.invoke({"draft_id": draft_id}, config)
            state = graph.get_state(config)
        if decision is None or state.values.get("decision"):
            return state.values.get("decision")
        return graph.invoke(Command(resume=decision), config)["decision"]
