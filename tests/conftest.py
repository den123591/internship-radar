import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from radar.db import Base, VacancyRepository, make_engine, session_scope
from radar.etl import _to_records, transform
from radar.models import Level, Vacancy

FIXTURES = Path(__file__).parent / "fixtures"


def make_vacancy(i: int, **overrides) -> Vacancy:
    data = {
        "source": "test",
        "external_id": str(i),
        "title": f"Стажёр Python-разработчик {i}",
        "company": "Acme",
        "url": f"https://example.com/{i}",
        "level": Level.INTERN,
        "remote": True,
        "skills": ["Python", "SQL"],
        "published_at": datetime(2026, 10, 6, tzinfo=UTC),
    }
    data.update(overrides)
    return Vacancy(**data)


@pytest.fixture
def engine():
    # В CI тесты дополнительно гоняются на PostgreSQL: RADAR_TEST_DATABASE_URL=postgresql+psycopg://...
    engine = make_engine(os.getenv("RADAR_TEST_DATABASE_URL", "sqlite://"))
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def seeded_engine(engine):
    vacancies = [
        make_vacancy(1, salary_from=40_000, salary_to=60_000, salary_currency="RUR"),
        make_vacancy(
            2,
            salary_from=60_000,
            salary_to=80_000,
            salary_currency="RUR",
            skills=["Python", "Docker"],
            remote=False,
        ),
        make_vacancy(
            3,
            salary_from=100_000,
            salary_currency="RUR",
            skills=["Java", "SQL"],
            company="Beta",
            published_at=datetime(2026, 9, 29, tzinfo=UTC),
        ),
        make_vacancy(
            4,
            level=Level.JUNIOR,
            salary_from=120_000,
            salary_to=140_000,
            salary_currency="RUR",
            skills=["Python", "SQL", "Docker"],
            company="Beta",
        ),
        make_vacancy(
            5,
            level=Level.JUNIOR,
            salary_from=1_000,
            salary_currency="USD",
            skills=["Go"],
            company="Gamma",
        ),
    ]
    with session_scope(engine) as session:
        VacancyRepository(session).upsert(_to_records(transform(vacancies)))
    return engine
