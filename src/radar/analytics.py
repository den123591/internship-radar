"""Аналитика рынка стажировок на чистом SQL (оконные функции, CTE, self-join).

Все запросы совместимы с SQLite ≥ 3.25 и PostgreSQL. Единственное расхождение
диалектов — группировка по неделям — вынесено в _week_expr().
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, text


def _rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def _week_expr(engine: Engine, column: str) -> str:
    if engine.dialect.name == "postgresql":
        return f"to_char(date_trunc('week', {column}), 'YYYY-MM-DD')"
    # SQLite: понедельник недели
    return f"date({column}, 'weekday 0', '-6 days')"


def top_skills(engine: Engine, limit: int = 20, level: str | None = None) -> list[dict]:
    """Самые востребованные навыки: число вакансий, доля и место в рейтинге."""
    sql = """
    WITH filtered AS (
        SELECT id FROM vacancies
        WHERE CAST(:level AS VARCHAR) IS NULL OR level = CAST(:level AS VARCHAR)
    ),
    counts AS (
        SELECT s.name AS skill, COUNT(*) AS vacancies
        FROM vacancy_skills vs
        JOIN filtered f ON f.id = vs.vacancy_id
        JOIN skills s ON s.id = vs.skill_id
        GROUP BY s.name
    )
    SELECT
        skill,
        vacancies,
        ROUND(100.0 * vacancies / (SELECT COUNT(*) FROM filtered), 1) AS share_pct,
        DENSE_RANK() OVER (ORDER BY vacancies DESC) AS rank
    FROM counts
    ORDER BY vacancies DESC, skill
    LIMIT :limit
    """
    return _rows(engine, sql, limit=limit, level=level)


def salary_by_level(engine: Engine) -> list[dict]:
    """Средняя и медианная зарплата по уровням. Медиана — через ROW_NUMBER/COUNT,
    потому что в SQLite нет percentile_cont."""
    sql = """
    WITH ranked AS (
        SELECT
            level,
            salary_mid_rub AS salary,
            ROW_NUMBER() OVER (PARTITION BY level ORDER BY salary_mid_rub) AS rn,
            COUNT(*)     OVER (PARTITION BY level) AS n
        FROM vacancies
        WHERE salary_mid_rub IS NOT NULL
    )
    SELECT
        level,
        MAX(n) AS vacancies_with_salary,
        CAST(ROUND(AVG(salary)) AS INTEGER) AS avg_salary,
        CAST(ROUND(AVG(CASE WHEN rn IN ((n + 1) / 2, (n + 2) / 2) THEN salary END))
             AS INTEGER) AS median_salary,
        MIN(salary) AS min_salary,
        MAX(salary) AS max_salary
    FROM ranked
    GROUP BY level
    ORDER BY avg_salary
    """
    return _rows(engine, sql)


def skill_salary_premium(engine: Engine, min_vacancies: int = 3, limit: int = 15) -> list[dict]:
    """Насколько вакансии с навыком платят больше/меньше среднего по рынку."""
    sql = """
    WITH per_skill AS (
        SELECT s.name AS skill,
               COUNT(*) AS vacancies,
               AVG(v.salary_mid_rub) AS avg_salary
        FROM vacancies v
        JOIN vacancy_skills vs ON vs.vacancy_id = v.id
        JOIN skills s ON s.id = vs.skill_id
        WHERE v.salary_mid_rub IS NOT NULL
        GROUP BY s.name
        HAVING COUNT(*) >= :min_vacancies
    )
    SELECT
        skill,
        vacancies,
        CAST(ROUND(avg_salary) AS INTEGER) AS avg_salary,
        CAST(ROUND(avg_salary - AVG(avg_salary) OVER ()) AS INTEGER) AS premium_vs_avg
    FROM per_skill
    ORDER BY premium_vs_avg DESC
    LIMIT :limit
    """
    return _rows(engine, sql, min_vacancies=min_vacancies, limit=limit)


def weekly_trend(engine: Engine) -> list[dict]:
    """Новые вакансии по неделям + нарастающий итог."""
    week = _week_expr(engine, "published_at")
    sql = f"""
    WITH weekly AS (
        SELECT {week} AS week, COUNT(*) AS new_vacancies
        FROM vacancies
        WHERE published_at IS NOT NULL
        GROUP BY {week}
    )
    SELECT
        week,
        new_vacancies,
        SUM(new_vacancies) OVER (ORDER BY week ROWS UNBOUNDED PRECEDING) AS running_total
    FROM weekly
    ORDER BY week
    """
    return _rows(engine, sql)


def top_companies(engine: Engine, limit: int = 10) -> list[dict]:
    sql = """
    SELECT
        company,
        COUNT(*) AS vacancies,
        ROUND(100.0 * SUM(CASE WHEN remote THEN 1 ELSE 0 END) / COUNT(*), 0) AS remote_pct
    FROM vacancies
    GROUP BY company
    ORDER BY vacancies DESC, company
    LIMIT :limit
    """
    return _rows(engine, sql, limit=limit)


def skill_pairs(engine: Engine, skill: str, limit: int = 10) -> list[dict]:
    """С какими навыками чаще всего требуют данный — «что учить вместе с Python»."""
    sql = """
    SELECT s2.name AS skill, COUNT(*) AS together
    FROM vacancy_skills a
    JOIN skills s1 ON s1.id = a.skill_id
    JOIN vacancy_skills b ON b.vacancy_id = a.vacancy_id AND b.skill_id <> a.skill_id
    JOIN skills s2 ON s2.id = b.skill_id
    WHERE LOWER(s1.name) = LOWER(:skill)
    GROUP BY s2.name
    ORDER BY together DESC, s2.name
    LIMIT :limit
    """
    return _rows(engine, sql, skill=skill, limit=limit)


def summary(engine: Engine) -> dict[str, Any]:
    sql = """
    SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN remote THEN 1 ELSE 0 END) AS remote,
        SUM(CASE WHEN level = 'intern' THEN 1 ELSE 0 END) AS interns,
        COUNT(DISTINCT company) AS companies,
        CAST(ROUND(AVG(salary_mid_rub)) AS INTEGER) AS avg_salary
    FROM vacancies
    """
    return _rows(engine, sql)[0]
