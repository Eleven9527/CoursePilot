from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints import study
from app.main import app

URL = "/api/v1/study/plan"
SCOPE = dict(subject="english", grade="高一", unit_start=1, unit_end=2, days=2, minutes_per_day=30)
SOURCE = {"text": "Review the present perfect.", "chunk_id": "example"}
DAY = {"topic": "Present perfect", "activities": [{"task": "Review the examples", "minutes": 20, "source": 1}]}


@pytest.fixture
def plan_client(monkeypatch):
    retrieval = Mock(return_value=[SOURCE])
    model = Mock(return_value={"days": [DAY, DAY]})
    monkeypatch.setattr(study, "retrieve", retrieval)
    monkeypatch.setattr(study, "chat_json", model)
    client = TestClient(app, follow_redirects=False)
    try:
        yield client, retrieval, model
    finally:
        client.close()


def login_student(client):
    assert client.post("/login", data={"account": "student", "password": "123"}).status_code == 303


def test_study_plan_checks_access_before_retrieval(plan_client):
    client, retrieval, model = plan_client
    assert client.post(URL, json=SCOPE).status_code == 401
    login_student(client)
    assert client.post(URL, json={**SCOPE, "subject": "math"}).status_code == 403
    retrieval.assert_not_called()
    model.assert_not_called()


def test_study_plan_returns_grounded_tasks(plan_client):
    client, retrieval, model = plan_client
    login_student(client)
    response = client.post(URL, json=SCOPE)
    assert response.status_code == 200
    assert retrieval.call_args.args[1:4] == ("高一", 1, 2)
    assert retrieval.call_args.kwargs == {"subject": "english", "include_drafts": False}
    assert model.call_args.args[1]["sources"] == [{"number": 1, "text": SOURCE["text"]}]
    assert response.json() == {"days": [DAY, DAY], "sources": [{**SOURCE, "number": 1}]}


@pytest.mark.parametrize("days", [
    [DAY],
    [DAY, {**DAY, "activities": DAY["activities"] * 2}],
    [DAY, {**DAY, "activities": [{**DAY["activities"][0], "source": 2}]}],
], ids=["wrong-day-count", "over-budget", "unknown-citation"])
def test_study_plan_rejects_invalid_model_output(plan_client, days):
    client, _, model = plan_client
    login_student(client)
    model.return_value = {"days": days}
    assert client.post(URL, json=SCOPE).status_code == 502
    assert model.call_count == 2
    assert model.call_args.args[1]["validation_errors"]


def test_study_plan_accepts_corrected_response(plan_client):
    client, retrieval, model = plan_client
    login_student(client)
    model.side_effect = [{"days": [DAY]}, {"days": [DAY, DAY]}]
    response = client.post(URL, json=SCOPE)
    assert response.status_code == 200
    assert model.call_args.args[1]["validation_errors"] == ["需要 2 天，实际返回 1 天"]
    assert retrieval.call_count == 1
