"""CLI: radar ingest | radar serve | radar stats | radar match."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from radar import analytics
from radar.db import VacancyRepository, make_engine, session_scope
from radar.etl import run_pipeline
from radar.matching import rank
from radar.models import Level
from radar.sources import SOURCES, SearchQuery, SourceUnavailableError, get_source


def _levels(value: str) -> tuple[Level, ...]:
    return tuple(Level(v.strip()) for v in value.split(","))


def cmd_ingest(args: argparse.Namespace) -> int:
    engine = make_engine(args.db)
    query = SearchQuery(
        text=args.query, levels=args.levels, remote_only=args.remote, max_pages=args.pages
    )
    try:
        report = run_pipeline(get_source(args.source), query, engine, limit=args.limit)
    except SourceUnavailableError as exc:
        print(f"Источник недоступен: {exc}", file=sys.stderr)
        return 2
    print(
        f"{report.source}: получено {report.fetched}, новых {report.inserted}, "
        f"обновлено {report.updated} за {report.seconds:.1f}с"
    )
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    engine = make_engine(args.db)
    print(
        json.dumps(
            {
                "summary": analytics.summary(engine),
                "top_skills": analytics.top_skills(engine, limit=10),
                "salary_by_level": analytics.salary_by_level(engine),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


def cmd_match(args: argparse.Namespace) -> int:
    resume = Path(args.resume).read_text(encoding="utf-8")
    engine = make_engine(args.db)
    with session_scope(engine) as session:
        vacancies = [r.to_model() for r in VacancyRepository(session).all()]
    for i, res in enumerate(rank(resume, vacancies, top_k=args.top), start=1):
        v = res.vacancy
        print(
            f"{i:>2}. [{res.score:.2f}] {v.title} — {v.company} "
            f"{'(удалённо)' if v.remote else ''}\n    {v.url}"
        )
        if res.missing_skills:
            print(f"    не хватает: {', '.join(res.missing_skills[:6])}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from radar.api import create_app

    uvicorn.run(create_app(make_engine(args.db)), host=args.host, port=args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="radar", description=__doc__)
    parser.add_argument("--db", help="SQLAlchemy URL (по умолчанию RADAR_DATABASE_URL)")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="Собрать вакансии из источника в БД")
    p.add_argument("--source", choices=list(SOURCES), default="habr")
    p.add_argument("--query", default="", help="Поисковый запрос, например 'python'")
    p.add_argument(
        "--levels",
        type=_levels,
        default=(Level.INTERN, Level.JUNIOR),
        help="Через запятую: intern,junior,middle,senior",
    )
    p.add_argument("--remote", action="store_true", help="Только удалёнка")
    p.add_argument("--pages", type=int, default=5)
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("stats", help="Краткая аналитика по БД")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("match", help="Подобрать вакансии под резюме")
    p.add_argument("resume", help="Путь к резюме в .txt/.md")
    p.add_argument("--top", type=int, default=10)
    p.set_defaults(func=cmd_match)

    p = sub.add_parser("serve", help="Запустить API и дашборд")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
