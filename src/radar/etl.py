"""ETL-пайплайн: extract (источник) → transform (pandas) → load (БД)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import islice

import pandas as pd
from sqlalchemy import Engine

from radar.db import VacancyRepository, session_scope
from radar.models import Vacancy
from radar.sources.base import SearchQuery, VacancySource
from radar.utils import timed

log = logging.getLogger(__name__)

# Фиксированные курсы для сопоставимости зарплат. Для аналитики «порядка величин»
# точность ЦБ не нужна, зато результат детерминирован.
RUB_RATES: dict[str, float] = {"RUR": 1.0, "RUB": 1.0, "USD": 90.0, "EUR": 100.0, "KZT": 0.18}
SALARY_BOUNDS_RUB = (5_000, 1_500_000)

# Разные написания одного навыка → каноническое имя.
SKILL_ALIASES: dict[str, str] = {
    "python3": "Python",
    "python 3": "Python",
    "postgres": "PostgreSQL",
    "postgresql": "PostgreSQL",
    "js": "JavaScript",
    "javascript": "JavaScript",
    "ts": "TypeScript",
    "typescript": "TypeScript",
    "k8s": "Kubernetes",
    "ml": "Machine Learning",
    "машинное обучение": "Machine Learning",
    "golang": "Go",
}


def canonical_skill(name: str) -> str:
    cleaned = " ".join(name.split())
    return SKILL_ALIASES.get(cleaned.lower(), cleaned)


def transform(vacancies: Iterable[Vacancy]) -> pd.DataFrame:
    """Чистит и обогащает сырые вакансии. Чистая функция — легко тестировать."""
    df = pd.DataFrame([v.model_dump() for v in vacancies])
    if df.empty:
        return df

    # 1. Дубликаты: одна и та же вакансия может прийти из разных поисковых запросов.
    df = df.drop_duplicates(subset=["source", "external_id"], keep="last")

    # 2. Навыки: канонизируем и убираем повторы внутри вакансии, сохраняя порядок.
    df["skills"] = df["skills"].apply(
        lambda skills: list(dict.fromkeys(canonical_skill(s) for s in skills if s.strip()))
    )

    # 3. Зарплата: середина вилки в рублях; если указана одна граница — берём её.
    low = pd.to_numeric(df["salary_from"], errors="coerce")
    high = pd.to_numeric(df["salary_to"], errors="coerce")
    mid = pd.concat([low, high], axis=1).mean(axis=1, skipna=True)
    rate = df["salary_currency"].map(RUB_RATES)
    mid_rub = (mid * rate).round()
    lo, hi = SALARY_BOUNDS_RUB
    mid_rub = mid_rub.where(mid_rub.between(lo, hi))
    df["salary_mid_rub"] = mid_rub.astype("Int64")

    # 4. Строковые поля: обрезаем пробелы, пустые строки → None.
    for col in ("title", "company", "city"):
        df[col] = df[col].astype("string").str.strip().replace("", pd.NA)

    df["level"] = df["level"].astype(str)
    return df


def _to_records(df: pd.DataFrame) -> list[dict]:
    records = df.astype(object).where(df.notna(), None).to_dict(orient="records")
    for rec in records:
        rec["level"] = str(rec["level"])
        if rec["salary_mid_rub"] is not None:
            rec["salary_mid_rub"] = int(rec["salary_mid_rub"])
        for key in ("salary_from", "salary_to"):
            if rec[key] is not None:
                rec[key] = int(rec[key])
    return records


@dataclass
class PipelineReport:
    source: str
    fetched: int
    inserted: int
    updated: int
    seconds: float


def run_pipeline(
    source: VacancySource,
    query: SearchQuery,
    engine: Engine,
    limit: int | None = None,
) -> PipelineReport:
    with timed(f"pipeline[{source.name}]") as timing:
        raw = list(islice(source.fetch(query), limit))
        df = transform(raw)
        records = _to_records(df) if not df.empty else []
        with session_scope(engine) as session:
            inserted, updated = VacancyRepository(session).upsert(records)

    report = PipelineReport(source.name, len(raw), inserted, updated, timing["seconds"])
    log.info("pipeline done: %s", report)
    return report
