import json

import httpx
import pytest

from radar.models import Level
from radar.sources import SampleSource, SearchQuery, SourceUnavailableError
from radar.sources.habr import HabrCareerSource, extract_ssr_state, html_to_text, parse_vacancy
from radar.sources.hh import HeadHunterSource

from .conftest import FIXTURES


def test_extract_ssr_state_from_real_page_snapshot():
    state = extract_ssr_state((FIXTURES / "habr_search.html").read_text())
    assert len(state["vacancies"]["list"]) == 2


def test_extract_ssr_state_raises_on_unknown_markup():
    with pytest.raises(ValueError, match="SSR state not found"):
        extract_ssr_state("<html><body>nothing here</body></html>")


def test_parse_vacancy_uses_predicted_salary_when_real_is_missing():
    item = extract_ssr_state((FIXTURES / "habr_search.html").read_text())["vacancies"]["list"][0]
    v = parse_vacancy(item)
    assert v.title == "Стажер AI-разработчик"
    assert v.company == "AGIMA"
    assert v.level is Level.INTERN
    assert v.remote is True
    assert v.skills == ["Git", "Linux", "Python", "LLM"]
    assert (v.salary_from, v.salary_to, v.salary_currency) == (20000, 52000, "RUR")
    assert v.salary_is_predicted is True
    assert v.url == "https://career.habr.com/vacancies/1000167929"


def test_html_to_text_strips_tags_and_entities():
    assert (
        html_to_text("<p>Python &amp; <b>SQL</b></p>\n<ul><li>Git</li></ul>") == "Python & SQL Git"
    )
    assert html_to_text(None) is None


def _page(items: list[dict], page: int, total_pages: int) -> str:
    state = {"vacancies": {"list": items, "meta": {"currentPage": page, "totalPages": total_pages}}}
    payload = json.dumps(state).replace('"', "&quot;")
    return f'<script data-ssr-state="true">{payload}</script>'


def _item(i: int) -> dict:
    return {
        "id": i,
        "href": f"/vacancies/{i}",
        "title": f"Job {i}",
        "company": {"title": "X"},
        "qualification": "Intern",
    }


def test_habr_source_paginates_until_last_page():
    calls: list[httpx.QueryParams] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params)
        page = int(request.url.params["page"])
        return httpx.Response(200, text=_page([_item(page * 10), _item(page * 10 + 1)], page, 2))

    client = httpx.Client(
        base_url="https://career.habr.com", transport=httpx.MockTransport(handler)
    )
    source = HabrCareerSource(client=client, interval_s=0)
    result = list(
        source.fetch(SearchQuery(text="python", levels=(Level.INTERN,), remote_only=True))
    )

    assert [v.external_id for v in result] == ["10", "11", "20", "21"]
    assert len(calls) == 2  # третью страницу не запрашиваем
    assert calls[0]["q"] == "python" and calls[0]["remote"] == "true" and calls[0]["qid"] == "1"


def test_habr_source_wraps_http_errors():
    client = httpx.Client(
        base_url="https://career.habr.com",
        transport=httpx.MockTransport(lambda r: httpx.Response(404)),
    )
    source = HabrCareerSource(client=client, interval_s=0)
    with pytest.raises(SourceUnavailableError):
        list(source.fetch(SearchQuery(levels=(Level.INTERN,))))


def test_hh_source_requires_token(monkeypatch):
    monkeypatch.delenv("RADAR_HH_TOKEN", raising=False)
    with pytest.raises(SourceUnavailableError, match="RADAR_HH_TOKEN"):
        list(HeadHunterSource(token=None).fetch(SearchQuery()))


def test_sample_source_filters():
    source = SampleSource()
    everything = list(source.fetch(SearchQuery()))
    remote = list(source.fetch(SearchQuery(remote_only=True)))
    assert everything, "снимок данных не должен быть пустым"
    assert all(v.remote for v in remote)
    assert len(remote) < len(everything)
