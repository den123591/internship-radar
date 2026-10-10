"""Источник: hh.ru API.

С 2025 года hh.ru закрыл анонимный доступ к поиску вакансий — нужен токен
приложения (https://dev.hh.ru). Без RADAR_HH_TOKEN источник честно сообщает,
что недоступен, вместо того чтобы молча вернуть пустой список.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx

from radar.config import get_settings
from radar.models import Level, Vacancy
from radar.sources.base import SearchQuery, SourceUnavailableError
from radar.utils import RateLimiter, retry

API_URL = "https://api.hh.ru"
LEVEL_TO_EXPERIENCE = {Level.INTERN: "noExperience", Level.JUNIOR: "between1And3"}


def parse_vacancy(item: dict[str, Any]) -> Vacancy:
    salary = item.get("salary") or {}
    title = item["name"].strip()
    lowered = title.lower()
    level = Level.INTERN if ("стаж" in lowered or "intern" in lowered) else Level.JUNIOR
    snippet = item.get("snippet") or {}
    description = " ".join(
        filter(None, [snippet.get("requirement"), snippet.get("responsibility")])
    )
    return Vacancy(
        source="hh",
        external_id=str(item["id"]),
        title=title,
        company=((item.get("employer") or {}).get("name") or "—").strip(),
        url=item.get("alternate_url") or f"https://hh.ru/vacancy/{item['id']}",
        level=level,
        remote=(item.get("schedule") or {}).get("id") == "remote",
        city=(item.get("area") or {}).get("name"),
        salary_from=salary.get("from"),
        salary_to=salary.get("to"),
        salary_currency=salary.get("currency"),
        skills=[s["name"] for s in item.get("key_skills") or []],
        description=description.replace("<highlighttext>", "").replace("</highlighttext>", "")
        or None,
        published_at=datetime.fromisoformat(item["published_at"])
        if item.get("published_at")
        else None,
    )


class HeadHunterSource:
    name = "hh"

    def __init__(self, token: str | None = None, client: httpx.Client | None = None):
        settings = get_settings()
        self._token = token or settings.hh_token
        self._client = client or httpx.Client(
            base_url=API_URL, headers={"User-Agent": settings.user_agent}, timeout=15.0
        )
        self._limiter = RateLimiter(settings.request_interval_s)

    @retry((httpx.TransportError,), attempts=3)
    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        self._limiter.wait()
        response = self._client.get(
            "/vacancies", params=params, headers={"Authorization": f"Bearer {self._token}"}
        )
        if response.status_code == 403:
            raise SourceUnavailableError("hh.ru вернул 403 — проверьте RADAR_HH_TOKEN")
        response.raise_for_status()
        return response.json()

    def fetch(self, query: SearchQuery) -> Iterator[Vacancy]:
        if not self._token:
            raise SourceUnavailableError(
                "hh.ru требует токен приложения: задайте RADAR_HH_TOKEN (https://dev.hh.ru)"
            )
        for level in query.levels:
            experience = LEVEL_TO_EXPERIENCE.get(level)
            if experience is None:
                continue
            for page in range(query.max_pages):
                params: dict[str, Any] = {
                    "text": query.text or "стажер",
                    "experience": experience,
                    "page": page,
                    "per_page": 50,
                }
                if query.remote_only:
                    params["schedule"] = "remote"
                data = self._get(params)
                for item in data.get("items", []):
                    yield parse_vacancy(item)
                if page + 1 >= int(data.get("pages") or 0):
                    break
