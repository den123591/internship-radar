from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Level(StrEnum):
    INTERN = "intern"
    JUNIOR = "junior"
    MIDDLE = "middle"
    SENIOR = "senior"
    UNKNOWN = "unknown"


class Vacancy(BaseModel):
    """Нормализованная вакансия — общий формат для всех источников."""

    source: str
    external_id: str
    title: str
    company: str
    url: str
    level: Level = Level.UNKNOWN
    remote: bool = False
    city: str | None = None
    salary_from: int | None = None
    salary_to: int | None = None
    salary_currency: str | None = None
    salary_is_predicted: bool = False
    skills: list[str] = Field(default_factory=list)
    specializations: list[str] = Field(default_factory=list)
    description: str | None = None
    published_at: datetime | None = None

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.external_id}"


class MatchResult(BaseModel):
    vacancy: Vacancy
    score: float = Field(ge=0, le=1, description="Итоговая оценка соответствия 0..1")
    matched_skills: list[str]
    missing_skills: list[str]
    explanation: str | None = None
