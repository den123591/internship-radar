"""Матчинг резюме с вакансиями.

score = 0.6 * cosine(TF-IDF резюме, TF-IDF вакансии) + 0.4 * покрытие навыков

Покрытие навыков — доля навыков вакансии, найденных в резюме. Это делает оценку
объяснимой: пользователь видит, каких именно навыков не хватает.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from functools import lru_cache

from radar.matching.tfidf import TfidfIndex, tokenize
from radar.models import MatchResult, Vacancy

TEXT_WEIGHT = 0.6
SKILL_WEIGHT = 0.4
SKILL_BOOST = 3  # навыки важнее слов из описания — повторяем их в документе


@lru_cache(maxsize=512)
def _skill_pattern(skill: str) -> re.Pattern[str]:
    # \b не работает для «C++», «C#», «.NET», поэтому границы задаём явно.
    return re.compile(rf"(?<![\w+#.]){re.escape(skill.lower())}(?![\w+#])")


def find_skills(text: str, skills: Sequence[str]) -> list[str]:
    lowered = text.lower()
    return [s for s in skills if _skill_pattern(s).search(lowered)]


def vacancy_tokens(v: Vacancy) -> list[str]:
    skill_tokens = tokenize(" ".join(v.skills)) * SKILL_BOOST
    text = " ".join([v.title, *v.specializations, v.description or ""])
    return tokenize(text) + skill_tokens


def rank(resume: str, vacancies: Sequence[Vacancy], top_k: int = 10) -> list[MatchResult]:
    if not vacancies:
        return []
    index = TfidfIndex().fit([vacancy_tokens(v) for v in vacancies])
    similarities = index.query(tokenize(resume))

    results: list[MatchResult] = []
    for vacancy, sim in zip(vacancies, similarities, strict=True):
        matched = find_skills(resume, vacancy.skills)
        missing = [s for s in vacancy.skills if s not in matched]
        coverage = len(matched) / len(vacancy.skills) if vacancy.skills else 0.0
        score = TEXT_WEIGHT * sim + SKILL_WEIGHT * coverage
        results.append(
            MatchResult(
                vacancy=vacancy,
                score=round(min(score, 1.0), 4),
                matched_skills=matched,
                missing_skills=missing,
            )
        )
    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_k]
