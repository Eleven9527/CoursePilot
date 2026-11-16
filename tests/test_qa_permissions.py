from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import qa
from app.core import database
from app.main import app
from app.rag.retrieval import hybrid
from app.services import document_service

SCOPE = {"question": "exercise", "grade": "高一", "unit_start": 1, "unit_end": 1}


@pytest.fixture
def environment(tmp_path, monkeypatch):
    config = replace(database.settings, data_dir=tmp_path, database_url="",
                     embedding_model="test", embedding_base_url="http://test",
                     embedding_dimension=1, milvus_uri="http://test")
    for module in (database, document_service, hybrid):
        monkeypatch.setattr(module, "settings", config)
    document_service.initialize_database()
    for name, subject, published in (
        ("PUBLIC", "english", True), ("DRAFT", "english", False), ("MATH", "math", True),
    ):
        doc = document_service.create_document(
            name, name, "高一", "第1单元", "", f"{name}.md", f"{name}.md", "md", 10, subject=subject,
        )
        task_id = doc["current_task_id"]
        with database.connect() as connection:
            connection.execute("UPDATE documents SET parsing_status='succeeded' WHERE id=?", (name,))
            connection.execute(
                """INSERT INTO parse_task_steps
                (id,task_id,document_id,step_key,title,status,created_at)
                VALUES (?,?,?,'embedding','embedding','succeeded',?) ON CONFLICT (task_id,step_key)
                DO UPDATE SET status='succeeded'""",
                (name, task_id, name, doc["created_at"]),
            )
            connection.execute(
                """INSERT INTO document_chunks
                (chunk_id,document_id,task_id,chunk_index,text,heading,char_count,metadata)
                VALUES (?,?,?,0,?,'',10,'{}')""",
                (name, name, task_id, f"exercise {name}"),
            )
        if published:
            document_service.set_publication(name, True)
    monkeypatch.setattr(hybrid, "embed_texts", Mock(return_value=[[1.0]]))
    # Return all IDs to exercise the second check on Milvus results.
    semantic = Mock(return_value=[{"id": name} for name in ("MATH", "DRAFT", "PUBLIC")])
    monkeypatch.setattr(hybrid.milvus, "search_vectors", semantic)
    monkeypatch.setattr(qa, "classify_intent", Mock(return_value=None))
    chat = Mock(side_effect=lambda prompt, body: (
        {"answer": "Answer [1]", "citations": [1]} if "sources" in body
        else {"query": "", "intent": "general_qa"}
    ))
    monkeypatch.setattr(qa, "chat_json", chat)
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, semantic, chat
    finally:
        client.close()


def login(client, account):
    assert client.post("/login", data={"account": account, "password": "123"}).status_code == 303


def test_student_only_retrieves_published_english(environment):
    client, semantic, chat = environment
    login(client, "student")
    for endpoint in ("search", "ask"):
        response = client.post(f"/api/v1/qa/{endpoint}", json=SCOPE)
        assert response.status_code == 200
        assert [source["chunk_id"] for source in response.json()["sources"]] == ["PUBLIC"]
    assert chat.call_args.args[1]["sources"] == [{"number": 1, "text": "exercise PUBLIC"}]
    task_id = document_service.get_document("PUBLIC")["current_task_id"]
    assert all(call.kwargs["filter_expression"] == f'task_id in ["{task_id}"]'
               for call in semantic.call_args_list)
    assert semantic.call_count == 2


def test_student_cannot_request_math_or_publish(environment):
    client, semantic, chat = environment
    login(client, "student")
    assert client.get("/api/v1/qa/scopes?subject=math").status_code == 403
    for endpoint in ("search", "ask"):
        assert client.post(f"/api/v1/qa/{endpoint}", json={**SCOPE, "subject": "math"}).status_code == 403
    assert client.put("/api/v1/documents/DRAFT/publication?published=true").status_code == 403
    semantic.assert_not_called()
    chat.assert_not_called()


def test_teacher_can_preview_drafts(environment):
    client, _, _ = environment
    login(client, "teacher")
    response = client.post("/api/v1/qa/search", json=SCOPE)
    assert response.status_code == 200
    assert {source["chunk_id"] for source in response.json()["sources"]} == {"PUBLIC", "DRAFT"}
