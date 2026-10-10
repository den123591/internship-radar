import math

import pytest

from radar.matching import find_skills, rank
from radar.matching.tfidf import TfidfIndex, cosine, stem, tokenize

from .conftest import make_vacancy


def test_cosine_basic_properties():
    a = {"python": 1.0, "sql": 2.0}
    assert cosine(a, a) == pytest.approx(1.0)
    assert cosine(a, {"java": 1.0}) == 0.0
    assert cosine({}, a) == 0.0


def test_idf_penalizes_common_terms():
    index = TfidfIndex().fit([["python", "sql"], ["python", "java"], ["python", "go"]])
    assert index.idf["python"] < index.idf["java"]
    assert index.idf["python"] == pytest.approx(math.log(4 / 4) + 1)


def test_russian_stemming_groups_word_forms():
    assert stem("разработки") == stem("разработка")
    assert stem("python") == "python"


def test_tokenize_keeps_tech_tokens():
    assert tokenize("Знаю C++, C# и Node.js") == ["знаю", "c++", "c#", "node.js"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Опыт с C++ и Git", ["C++", "Git"]),
        ("Пишу на C", ["C"]),
        ("Знаю JavaScript", []),  # «Java» не должна находиться внутри «JavaScript»
    ],
)
def test_find_skills_respects_boundaries(text, expected):
    assert find_skills(text, ["C++", "C", "Git", "Java"]) == expected


def test_rank_prefers_vacancy_with_matching_skills():
    vacancies = [
        make_vacancy(1, title="Стажёр Java-разработчик", skills=["Java", "Spring"]),
        make_vacancy(2, title="Стажёр Python-разработчик", skills=["Python", "FastAPI", "SQL"]),
        make_vacancy(3, title="Стажёр дизайнер", skills=["Figma"]),
    ]
    results = rank("Python, FastAPI, немного SQL и Git", vacancies, top_k=2)
    assert [r.vacancy.external_id for r in results] == ["2", "1"]
    best = results[0]
    assert best.matched_skills == ["Python", "FastAPI", "SQL"]
    assert best.missing_skills == []
    assert 0 < best.score <= 1


def test_rank_empty():
    assert rank("anything", []) == []
