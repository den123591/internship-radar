from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from radar import api as api_module
from radar.api import create_app
from radar.matching.llm import LLMAdvisor, LLMAssessment

RESUME = "Студент 4 курса. Python, SQL, Docker, Git. Делал pet-проект на FastAPI."


@pytest.fixture
def client(seeded_engine):
    return TestClient(create_app(seeded_engine))


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"


def test_list_and_filter_vacancies(client):
    assert len(client.get("/api/vacancies").json()) == 5
    juniors = client.get("/api/vacancies", params={"level": "junior"}).json()
    assert {v["level"] for v in juniors} == {"junior"}
    assert client.get("/api/vacancies", params={"level": "boss"}).status_code == 422


def test_analytics_endpoints(client):
    assert client.get("/api/analytics/summary").json()["total"] == 5
    assert client.get("/api/analytics/skills").json()[0]["skill"] == "Python"
    assert "by_level" in client.get("/api/analytics/salaries").json()
    assert client.get("/api/analytics/trend").json()
    assert client.get("/api/analytics/skill-pairs", params={"skill": "SQL"}).json()


def test_match_respects_filters(client):
    res = client.post(
        "/api/match",
        json={"resume": RESUME, "remote_only": True, "levels": ["intern"], "top_k": 10},
    )
    assert res.status_code == 200
    items = res.json()
    assert items and all(
        i["vacancy"]["remote"] and i["vacancy"]["level"] == "intern" for i in items
    )
    assert items == sorted(items, key=lambda i: i["score"], reverse=True)


def test_match_validates_resume_length(client):
    assert client.post("/api/match", json={"resume": "коротко"}).status_code == 422


def test_assess_without_key_returns_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    res = client.post("/api/assess", json={"resume": RESUME, "vacancy_id": 1})
    assert res.status_code == 503


def test_assess_with_stubbed_llm(client, monkeypatch):
    expected = LLMAssessment(
        fit_score=72,
        strengths=["Python"],
        gaps=["Docker"],
        advice="Подтяни Docker",
        cover_letter="Здравствуйте!",
    )
    monkeypatch.setattr(api_module, "llm_available", lambda: True)
    monkeypatch.setattr(LLMAdvisor, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(LLMAdvisor, "assess", lambda self, resume, vacancy: expected)

    res = client.post("/api/assess", json={"resume": RESUME, "vacancy_id": 1})
    assert res.status_code == 200
    assert res.json()["fit_score"] == 72
    assert client.post("/api/assess", json={"resume": RESUME, "vacancy_id": 999}).status_code == 404


def test_llm_advisor_builds_structured_request():
    captured = {}
    assessment = LLMAssessment(fit_score=50, strengths=[], gaps=[], advice="-", cover_letter="-")

    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=assessment)

    fake = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    from .conftest import make_vacancy

    result = LLMAdvisor(client=fake, model="test-model").assess(RESUME, make_vacancy(1))
    assert result is assessment
    assert captured["model"] == "test-model"
    assert captured["output_format"] is LLMAssessment
    assert "<resume>" in captured["messages"][0]["content"]


def test_index_page_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Internship Radar" in res.text
