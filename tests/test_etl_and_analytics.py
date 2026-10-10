from radar import analytics
from radar.db import VacancyRepository, session_scope
from radar.etl import canonical_skill, run_pipeline, transform
from radar.sources import SampleSource, SearchQuery

from .conftest import make_vacancy


def test_transform_dedupes_and_normalizes():
    df = transform(
        [
            make_vacancy(1, skills=["python3", "Postgres", " SQL ", "Python"]),
            make_vacancy(1, title="  Обновлённый заголовок  "),  # дубль — побеждает последний
            make_vacancy(2, salary_from=1000, salary_to=2000, salary_currency="USD"),
            make_vacancy(3, salary_from=50, salary_currency="RUR"),  # мусорная зарплата
        ]
    )
    assert len(df) == 3
    first = df[df.external_id == "1"].iloc[0]
    assert first.title == "Обновлённый заголовок"
    assert df[df.external_id == "2"].iloc[0].salary_mid_rub == 135_000
    assert df[df.external_id == "3"].salary_mid_rub.isna().all()


def test_canonical_skill_merges_aliases():
    assert canonical_skill("python3") == canonical_skill("Python 3") == "Python"
    assert canonical_skill("K8s") == "Kubernetes"
    assert canonical_skill("FastAPI") == "FastAPI"


def test_pipeline_is_idempotent(engine):
    source, query = SampleSource(), SearchQuery()
    first = run_pipeline(source, query, engine)
    second = run_pipeline(source, query, engine)
    assert first.inserted == first.fetched > 0
    assert second.inserted == 0 and second.updated == first.fetched


def test_repository_filters(seeded_engine):
    with session_scope(seeded_engine) as s:
        repo = VacancyRepository(s)
        assert {r.external_id for r in repo.list(skill="docker")} == {"2", "4"}
        assert all(r.remote for r in repo.list(remote=True))


def test_top_skills_ranks_and_shares(seeded_engine):
    top = analytics.top_skills(seeded_engine)
    assert top[0] == {"skill": "Python", "vacancies": 3, "share_pct": 60.0, "rank": 1}
    # SQL тоже в 3 вакансиях — DENSE_RANK даёт то же место, порядок по имени
    assert (top[1]["skill"], top[1]["rank"]) == ("SQL", 1)
    assert (top[2]["skill"], top[2]["rank"]) == ("Docker", 2)


def test_salary_median_by_level(seeded_engine):
    rows = {r["level"]: r for r in analytics.salary_by_level(seeded_engine)}
    # стажёры: 50k, 70k, 100k → медиана 70k
    assert rows["intern"]["median_salary"] == 70_000
    # junior: 130k и 90k (1000 USD) → медиана — среднее двух
    assert rows["junior"]["median_salary"] == 110_000


def test_weekly_trend_has_running_total(seeded_engine):
    trend = analytics.weekly_trend(seeded_engine)
    assert [w["new_vacancies"] for w in trend] == [1, 4]
    assert trend[-1]["running_total"] == 5


def test_skill_pairs(seeded_engine):
    pairs = {p["skill"]: p["together"] for p in analytics.skill_pairs(seeded_engine, "python")}
    assert pairs == {"SQL": 2, "Docker": 2}
