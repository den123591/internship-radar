from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

from radar.models import Level, Vacancy


@dataclass(frozen=True)
class SearchQuery:
    text: str = ""
    levels: tuple[Level, ...] = (Level.INTERN, Level.JUNIOR)
    remote_only: bool = False
    max_pages: int = 5


class VacancySource(Protocol):
    """Источник вакансий. Новые площадки добавляются реализацией этого протокола."""

    name: str

    def fetch(self, query: SearchQuery) -> Iterator[Vacancy]:
        """Лениво отдаёт вакансии страница за страницей."""
        ...


class SourceUnavailableError(RuntimeError):
    """Источник не может отдать данные (нет токена, сайт недоступен и т.п.)."""
