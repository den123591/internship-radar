"""Офлайн-источник: снимок реальных вакансий, сохранённый в репозитории.

Нужен для демо без сети и для воспроизводимых тестов.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from importlib import resources
from pathlib import Path

from radar.models import Vacancy
from radar.sources.base import SearchQuery


def _default_path() -> Path:
    return Path(str(resources.files("radar") / "data" / "sample_vacancies.json"))


class SampleSource:
    name = "sample"

    def __init__(self, path: Path | None = None):
        self.path = path or _default_path()

    def fetch(self, query: SearchQuery) -> Iterator[Vacancy]:
        records = json.loads(self.path.read_text(encoding="utf-8"))
        text = query.text.lower()
        for record in records:
            vacancy = Vacancy.model_validate(record)
            if query.levels and vacancy.level not in query.levels:
                continue
            if query.remote_only and not vacancy.remote:
                continue
            haystack = " ".join([vacancy.title, *vacancy.skills]).lower()
            if text and text not in haystack:
                continue
            yield vacancy
