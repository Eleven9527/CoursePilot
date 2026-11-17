from dataclasses import replace
from io import BytesIO
from unittest.mock import Mock

import pytest
from docx import Document
from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver

from app.api.v1.endpoints import prep
from app.core import database
from app.main import app
from app.services import document_service
from app.services import prep_workflow

API = "/api/v1/prep"
SCOPE = {"subject": "english", "grade": "初三", "unit_start": 5, "unit_end": 5}
SOURCE = {"text": "Fill in: It ___ made here.", "filename": "unit5.md",
          "heading": "被动语态", "unit": "第5单元", "chunk_index": 0}
MODEL_DRAFT = {"title": "被动语态", "focus": "基本结构", "difficulty": "时态判断",
               "exercises": [{"question": SOURCE["text"], "answer": "is",
                              "explanation": "一般现在时被动语态", "source": 1}]}


@pytest.fixture
def client_factory(tmp_path, monkeypatch):
    settings = replace(database.settings, data_dir=tmp_path, database_url="")
    monkeypatch.setattr(database, "settings", settings)
    monkeypatch.setattr(document_service, "settings", settings)
    document_service.initialize_database()
    monkeypatch.setattr(prep, "retrieve", Mock(return_value=[SOURCE]))
    monkeypatch.setattr(prep, "chat_json", Mock(
        side_effect=lambda _, payload: MODEL_DRAFT if "scope" in payload else {"issues": []}
    ))

    clients = []

    def login(role):
        client = TestClient(app, follow_redirects=False)
        clients.append(client)
        response = client.post("/login", data={"account": role, "password": "123"})
        assert response.status_code == 303
        return client

    yield login

    for client in clients:
        client.close()


def generate(client, scope=SCOPE):
    response = client.post(f"{API}/generate", json=scope)
    assert response.status_code == 200, response.text
    draft_id = response.json()["id"]
    return draft_id, f"{API}/drafts/{draft_id}"


def test_auto_saved_draft_can_be_reopened_rejected_and_regenerated(client_factory):
    teacher = client_factory("teacher")
    first_id, first_url = generate(teacher)
    checkpoint_path = database.settings.data_dir / "prep-checkpoints.sqlite"
    config = {"configurable": {"thread_id": first_id}}
    with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        pending = prep_workflow._workflow.compile(checkpointer=saver).get_state(config)
    assert pending.interrupts[0].value == {"draft_id": first_id, "status": "pending_review"}

    # A new session represents returning to the draft list after closing the page.
    returning_teacher = client_factory("teacher")
    assert first_id in {draft["id"] for draft in returning_teacher.get(f"{API}/drafts").json()}
    first = returning_teacher.get(first_url).json()
    assert first["reviewed_at"] is None and first["rejected_at"] is None
    assert returning_teacher.get(f"{first_url}/export?version=student&format=md").status_code == 409

    rejection = returning_teacher.post(f"{first_url}/reject")
    assert rejection.status_code == 200
    with SqliteSaver.from_conn_string(str(checkpoint_path)) as saver:
        completed = prep_workflow._workflow.compile(checkpointer=saver).get_state(config)
    assert completed.values["decision"] == "reject" and not completed.next
    assert returning_teacher.get(first_url).json()["rejected_at"] == rejection.json()["rejected_at"]
    assert returning_teacher.post(f"{first_url}/review").status_code == 409
    assert returning_teacher.get(f"{first_url}/export?version=teacher&format=docx").status_code == 409

    second_id, second_url = generate(returning_teacher, {key: first[key] for key in SCOPE})
    assert second_id != first_id
    audit = teacher.get(f"{API}/audit", params={"draft_id": first_id})
    assert audit.status_code == 200
    entries = audit.json()
    assert entries and {entry["draft_id"] for entry in entries} == {first_id}
    assert "reject_teaching_draft" in {entry["tool"] for entry in entries}
    assert returning_teacher.get(second_url).json()["reviewed_at"] is None
    review = returning_teacher.post(f"{second_url}/review")
    assert review.status_code == 200
    assert teacher.get(second_url).json()["reviewed_at"] == review.json()["reviewed_at"]

    student_file = teacher.get(f"{second_url}/export?version=student&format=md")
    assert student_file.status_code == 200
    assert SOURCE["text"] in student_file.text
    assert "参考答案" not in student_file.text and "答案：" not in student_file.text
    word_file = teacher.get(f"{second_url}/export?version=teacher&format=docx")
    assert word_file.status_code == 200
    content = Document(BytesIO(word_file.content)).tables[0].cell(5, 0).text
    assert SOURCE["text"] in content and "答案：is" in content and SOURCE["filename"] in content


def test_student_cannot_operate_on_known_draft(client_factory):
    teacher = client_factory("teacher")
    _, draft_url = generate(teacher)
    assert teacher.post(f"{draft_url}/review").status_code == 200

    student = client_factory("student")
    assert student.get(f"{API}/drafts").status_code == 403
    assert student.get(draft_url).status_code == 403
    assert student.post(f"{draft_url}/review").status_code == 403
    assert student.post(f"{draft_url}/reject").status_code == 403
    assert student.get(f"{draft_url}/export?version=teacher&format=docx").status_code == 403
    assert student.get(f"{API}/audit").status_code == 403

    audit = teacher.get(f"{API}/audit")
    assert audit.status_code == 200
    denied = {entry["tool"]: entry["reason"] for entry in audit.json()
              if entry["role"] == "student" and entry["subject"] == "english" and entry["outcome"] == "denied"}
    assert set(denied) == {"open_teaching_draft", "review_teaching_draft",
                           "reject_teaching_draft", "export_teaching_draft"}
    assert all(denied.values())


def test_content_review_retries_and_blocks_failed_draft(client_factory):
    teacher = client_factory("teacher")
    issue = "第 1 题的引用不支持答案"
    prep.chat_json.side_effect = [MODEL_DRAFT, {"issues": [issue]}, MODEL_DRAFT, {"issues": [issue]}]
    response = teacher.post(f"{API}/generate", json=SCOPE)
    assert response.status_code == 502
    assert issue in response.json()["detail"]
    assert prep.chat_json.call_args_list[2].args[1]["validation_errors"] == [issue]
    assert teacher.get(f"{API}/drafts").json() == []
