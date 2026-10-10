"""HTTP API (FastAPI) + статический дашборд."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from importlib import resources
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from radar import __version__, analytics
from radar.db import VacancyRepository, make_engine, session_scope
from radar.matching import rank
from radar.matching.llm import LLMAdvisor, LLMAssessment, LLMUnavailableError, llm_available
from radar.models import Level, MatchResult, Vacancy
from radar.sources.habr import HabrCareerSource

log = logging.getLogger(__name__)

WEB_DIR = resources.files("radar") / "web"


class VacancyOut(Vacancy):
    id: int


class MatchRequest(BaseModel):
    resume: str = Field(min_length=30, max_length=20_000, description="Текст резюме")
    remote_only: bool = False
    levels: list[Level] = [Level.INTERN, Level.JUNIOR]
    top_k: int = Field(10, ge=1, le=50)


class MatchOut(MatchResult):
    vacancy: VacancyOut


class AssessRequest(BaseModel):
    resume: str = Field(min_length=30, max_length=20_000)
    vacancy_id: int


def get_session(request: Request) -> Iterator[Session]:
    with session_scope(request.app.state.engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def create_app(engine: Engine | None = None) -> FastAPI:
    app = FastAPI(
        title="Internship Radar",
        version=__version__,
        description="Агрегатор IT-стажировок: аналитика рынка и матчинг резюме",
    )
    app.state.engine = engine or make_engine()

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__, "llm": llm_available()}

    @app.get("/api/vacancies", response_model=list[VacancyOut])
    def list_vacancies(
        session: SessionDep,
        level: Level | None = None,
        remote: bool | None = None,
        skill: str | None = None,
        q: str | None = None,
        limit: int = Query(50, ge=1, le=200),
        offset: int = Query(0, ge=0),
    ) -> list[VacancyOut]:
        rows = VacancyRepository(session).list(
            level=level, remote=remote, skill=skill, q=q, limit=limit, offset=offset
        )
        return [VacancyOut(id=r.id, **r.to_model().model_dump()) for r in rows]

    @app.get("/api/analytics/summary")
    def get_summary() -> dict:
        return analytics.summary(app.state.engine)

    @app.get("/api/analytics/skills")
    def get_skills(level: Level | None = None, limit: int = Query(20, ge=1, le=100)) -> list[dict]:
        return analytics.top_skills(
            app.state.engine, limit=limit, level=level.value if level else None
        )

    @app.get("/api/analytics/salaries")
    def get_salaries() -> dict:
        return {
            "by_level": analytics.salary_by_level(app.state.engine),
            "skill_premium": analytics.skill_salary_premium(app.state.engine),
        }

    @app.get("/api/analytics/trend")
    def get_trend() -> list[dict]:
        return analytics.weekly_trend(app.state.engine)

    @app.get("/api/analytics/companies")
    def get_companies(limit: int = Query(10, ge=1, le=50)) -> list[dict]:
        return analytics.top_companies(app.state.engine, limit=limit)

    @app.get("/api/analytics/skill-pairs")
    def get_skill_pairs(skill: str, limit: int = Query(10, ge=1, le=50)) -> list[dict]:
        return analytics.skill_pairs(app.state.engine, skill=skill, limit=limit)

    @app.post("/api/match", response_model=list[MatchOut])
    def match(body: MatchRequest, session: SessionDep) -> list[MatchOut]:
        repo = VacancyRepository(session)
        rows = [
            r
            for r in repo.all()
            if r.level in {lvl.value for lvl in body.levels} and (r.remote or not body.remote_only)
        ]
        by_uid = {r.to_model().uid: r.id for r in rows}
        results = rank(body.resume, [r.to_model() for r in rows], top_k=body.top_k)
        return [
            MatchOut(
                **res.model_dump(exclude={"vacancy"}),
                vacancy=VacancyOut(id=by_uid[res.vacancy.uid], **res.vacancy.model_dump()),
            )
            for res in results
        ]

    @app.post("/api/assess", response_model=LLMAssessment)
    def assess(body: AssessRequest, session: SessionDep) -> LLMAssessment:
        if not llm_available():
            raise HTTPException(503, "LLM отключён: задайте ANTHROPIC_API_KEY")
        row = VacancyRepository(session).get(body.vacancy_id)
        if row is None:
            raise HTTPException(404, "Вакансия не найдена")
        if not row.description and row.source == "habr":
            # В списке у Хабра нет описания — догружаем его один раз и кешируем в БД.
            try:
                row.description = HabrCareerSource().fetch_description(row.to_model())
            except (httpx.HTTPError, ValueError) as exc:
                # Описание — приятный бонус: без него оценка тоже работает.
                log.warning("не удалось загрузить описание вакансии %s: %s", row.id, exc)
        try:
            return LLMAdvisor().assess(body.resume, row.to_model())
        except LLMUnavailableError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(str(WEB_DIR / "index.html"))

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
    return app
