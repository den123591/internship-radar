"""Схема БД и репозиторий. Работает и с SQLite (по умолчанию), и с PostgreSQL."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Engine,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.pool import StaticPool

from radar.config import get_settings
from radar.models import Level, Vacancy


class Base(DeclarativeBase):
    pass


vacancy_skills = Table(
    "vacancy_skills",
    Base.metadata,
    Column("vacancy_id", ForeignKey("vacancies.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
)


class SkillRow(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)


class VacancyRow(Base):
    __tablename__ = "vacancies"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_source_external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200), index=True)
    url: Mapped[str] = mapped_column(String(500))
    level: Mapped[str] = mapped_column(String(20), index=True)
    remote: Mapped[bool] = mapped_column(Boolean, index=True)
    city: Mapped[str | None] = mapped_column(String(100))
    salary_from: Mapped[int | None] = mapped_column(Integer)
    salary_to: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(8))
    # Середина вилки в рублях — считается на этапе transform, чтобы SQL был простым.
    salary_mid_rub: Mapped[int | None] = mapped_column(Integer, index=True)
    salary_is_predicted: Mapped[bool] = mapped_column(Boolean, default=False)
    specializations: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    skills: Mapped[list[SkillRow]] = relationship(secondary=vacancy_skills, lazy="selectin")

    def to_model(self) -> Vacancy:
        return Vacancy(
            source=self.source,
            external_id=self.external_id,
            title=self.title,
            company=self.company,
            url=self.url,
            level=Level(self.level),
            remote=self.remote,
            city=self.city,
            salary_from=self.salary_from,
            salary_to=self.salary_to,
            salary_currency=self.salary_currency,
            salary_is_predicted=self.salary_is_predicted,
            skills=sorted(s.name for s in self.skills),
            specializations=list(self.specializations or []),
            description=self.description,
            published_at=self.published_at,
        )


def make_engine(url: str | None = None) -> Engine:
    url = url or get_settings().database_url
    kwargs: dict = {}
    if url.startswith("sqlite"):
        # FastAPI обслуживает запросы в пуле потоков — разрешаем общий коннект SQLite.
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool  # одна in-memory БД на все соединения
    engine = create_engine(url, **kwargs)
    Base.metadata.create_all(engine)
    return engine


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    """Единица работы: commit при успехе, rollback при исключении."""
    session = Session(engine, expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class VacancyRepository:
    def __init__(self, session: Session):
        self.session = session
        self._skill_cache: dict[str, SkillRow] = {}

    def _skill(self, name: str) -> SkillRow:
        key = name.strip()
        if key in self._skill_cache:
            return self._skill_cache[key]
        row = self.session.scalar(select(SkillRow).where(SkillRow.name == key))
        if row is None:
            row = SkillRow(name=key)
            self.session.add(row)
        self._skill_cache[key] = row
        return row

    def upsert(self, records: Iterable[dict]) -> tuple[int, int]:
        """Вставляет новые вакансии и обновляет существующие. Возвращает (inserted, updated).

        Поиск по (source, external_id) + insert/update — переносимо между SQLite и
        PostgreSQL; на объёмах в тысячи строк этого достаточно.
        """
        now = datetime.now(UTC)
        inserted = updated = 0
        for rec in records:
            row = self.session.scalar(
                select(VacancyRow).where(
                    VacancyRow.source == rec["source"],
                    VacancyRow.external_id == rec["external_id"],
                )
            )
            skills = [self._skill(s) for s in dict.fromkeys(rec.pop("skills", []))]
            if row is None:
                row = VacancyRow(**rec, first_seen_at=now, last_seen_at=now)
                self.session.add(row)
                inserted += 1
            else:
                for key, value in rec.items():
                    setattr(row, key, value)
                row.last_seen_at = now
                updated += 1
            row.skills = skills
        self.session.flush()
        return inserted, updated

    def list(
        self,
        *,
        level: Level | None = None,
        remote: bool | None = None,
        skill: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VacancyRow]:
        stmt = select(VacancyRow).order_by(VacancyRow.published_at.desc().nulls_last())
        if level is not None:
            stmt = stmt.where(VacancyRow.level == level.value)
        if remote is not None:
            stmt = stmt.where(VacancyRow.remote == remote)
        if skill:
            stmt = stmt.where(VacancyRow.skills.any(SkillRow.name.ilike(skill)))
        if q:
            stmt = stmt.where(VacancyRow.title.ilike(f"%{q}%"))
        return list(self.session.scalars(stmt.limit(limit).offset(offset)))

    def all(self) -> list[VacancyRow]:
        return list(self.session.scalars(select(VacancyRow)))

    def get(self, vacancy_id: int) -> VacancyRow | None:
        return self.session.get(VacancyRow, vacancy_id)
