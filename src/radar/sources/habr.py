"""Источник: Хабр Карьера.

Публичного API у Хабр Карьеры нет, но страница поиска отдаёт состояние
в теге <script data-ssr-state="true"> в виде JSON. Парсим его, а не HTML-разметку:
это устойчивее к изменениям вёрстки. Раздел /vacancies разрешён в robots.txt.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx

from radar.config import get_settings
from radar.models import Level, Vacancy
from radar.sources.base import SearchQuery, SourceUnavailableError
from radar.utils import RateLimiter, retry

BASE_URL = "https://career.habr.com"

# qid — идентификатор квалификации в фильтре Хабра.
LEVEL_TO_QID: dict[Level, int] = {
    Level.INTERN: 1,
    Level.JUNIOR: 3,
    Level.MIDDLE: 4,
    Level.SENIOR: 5,
}
QUALIFICATION_TO_LEVEL: dict[str, Level] = {
    "intern": Level.INTERN,
    "junior": Level.JUNIOR,
    "middle": Level.MIDDLE,
    "senior": Level.SENIOR,
    "lead": Level.SENIOR,
}

_SSR_RE = re.compile(r'<script[^>]*data-ssr-state="true"[^>]*>(.*?)</script>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def extract_ssr_state(page: str) -> dict[str, Any]:
    match = _SSR_RE.search(page)
    if not match:
        raise ValueError("SSR state not found — разметка Хабра изменилась?")
    return json.loads(html.unescape(match.group(1)))


def html_to_text(raw: str | None) -> str | None:
    if not raw:
        return None
    text = _TAG_RE.sub(" ", raw)
    return re.sub(r"\s+", " ", html.unescape(text)).strip() or None


def parse_vacancy(item: dict[str, Any]) -> Vacancy:
    """Превращает элемент списка Хабра в нашу модель Vacancy."""
    salary = item.get("salary") or {}
    predicted = item.get("predictedSalary") or {}
    has_real_salary = bool(salary.get("from") or salary.get("to"))
    chosen = salary if has_real_salary else predicted

    published = (item.get("publishedDate") or {}).get("date")
    locations = [loc["title"] for loc in item.get("locations") or [] if loc.get("title")]
    qualification = (item.get("qualification") or "").lower()

    return Vacancy(
        source="habr",
        external_id=str(item["id"]),
        title=item["title"].strip(),
        company=((item.get("company") or {}).get("title") or "—").strip(),
        url=BASE_URL + item["href"],
        level=QUALIFICATION_TO_LEVEL.get(qualification, Level.UNKNOWN),
        remote=bool(item.get("remoteWork")),
        city=locations[0] if locations else None,
        salary_from=chosen.get("from"),
        salary_to=chosen.get("to"),
        salary_currency=(chosen.get("currency") or "").upper() or None,
        salary_is_predicted=not has_real_salary and bool(chosen.get("from") or chosen.get("to")),
        skills=[s["title"] for s in item.get("skills") or [] if s.get("title")],
        specializations=[d["title"] for d in item.get("divisions") or [] if d.get("title")],
        description=html_to_text(item.get("description")),
        published_at=datetime.fromisoformat(published) if published else None,
    )


class HabrCareerSource:
    name = "habr"

    def __init__(self, client: httpx.Client | None = None, interval_s: float | None = None):
        settings = get_settings()
        self._client = client or httpx.Client(
            base_url=BASE_URL,
            headers={"User-Agent": settings.user_agent},
            timeout=15.0,
            follow_redirects=True,
        )
        self._limiter = RateLimiter(
            settings.request_interval_s if interval_s is None else interval_s
        )

    @retry((httpx.TransportError, httpx.HTTPStatusError), attempts=3)
    def _get(self, path: str, params: dict[str, Any] | None = None) -> str:
        self._limiter.wait()
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.text

    def fetch(self, query: SearchQuery) -> Iterator[Vacancy]:
        for level in query.levels:
            qid = LEVEL_TO_QID.get(level)
            if qid is None:
                continue
            yield from self._fetch_level(query, qid)

    def _fetch_level(self, query: SearchQuery, qid: int) -> Iterator[Vacancy]:
        for page in range(1, query.max_pages + 1):
            params: dict[str, Any] = {"type": "all", "qid": qid, "page": page}
            if query.text:
                params["q"] = query.text
            if query.remote_only:
                params["remote"] = "true"
            try:
                state = extract_ssr_state(self._get("/vacancies", params))
            except httpx.HTTPError as exc:
                raise SourceUnavailableError(f"Habr Career: {exc}") from exc

            block = state.get("vacancies") or {}
            for item in block.get("list") or []:
                yield parse_vacancy(item)

            meta = block.get("meta") or {}
            if page >= int(meta.get("totalPages") or 0):
                break

    def fetch_description(self, vacancy: Vacancy) -> str | None:
        """Догружает полное описание со страницы вакансии (для LLM-матчинга)."""
        path = vacancy.url.removeprefix(BASE_URL)
        state = extract_ssr_state(self._get(path))
        return html_to_text((state.get("vacancy") or {}).get("description"))
