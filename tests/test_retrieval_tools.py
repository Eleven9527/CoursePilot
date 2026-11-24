from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.rag.retrieval import tools


def make_tool(role="student", subject="english"):
    return tools.create_search_tool(
        role=role, subject=subject, grade="高一",
        unit_start=1, unit_end=2, question="原始问题",
    )


def test_tool_schema_and_server_bound_scope(monkeypatch):
    retrieval = Mock(return_value=[{"text": "evidence"}])
    monkeypatch.setattr(tools, "retrieve", retrieval)
    student = make_tool()
    teacher = make_tool("teacher", "math")
    assert set(student.args) == {"query"}
    assert student.invoke({"query": "改写查询"}) == {"sources": [{"text": "evidence"}]}
    retrieval.assert_called_with(
        "原始问题", "高一", 1, 2, 5, "改写查询",
        subject="english", include_drafts=False,
    )
    teacher.invoke({"query": "数学"})
    assert retrieval.call_args.kwargs == {"subject": "math", "include_drafts": True}
    student.invoke({"query": "再次查询"})
    assert retrieval.call_args.kwargs == {"subject": "english", "include_drafts": False}


def test_tool_rejects_injected_identity_and_unauthorized_scope(monkeypatch):
    retrieval = Mock()
    monkeypatch.setattr(tools, "retrieve", retrieval)
    with pytest.raises(ValidationError):
        make_tool().invoke({"query": "查询", "role": "teacher"})
    with pytest.raises(ValidationError):
        make_tool().invoke({"query": ""})
    with pytest.raises(HTTPException) as denied:
        make_tool(subject="math").invoke({"query": "查询"})
    assert denied.value.status_code == 403
    retrieval.assert_not_called()
