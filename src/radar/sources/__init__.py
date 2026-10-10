from radar.sources.base import SearchQuery, SourceUnavailableError, VacancySource
from radar.sources.habr import HabrCareerSource
from radar.sources.hh import HeadHunterSource
from radar.sources.sample import SampleSource

SOURCES: dict[str, type] = {
    "habr": HabrCareerSource,
    "hh": HeadHunterSource,
    "sample": SampleSource,
}


def get_source(name: str) -> VacancySource:
    try:
        return SOURCES[name]()
    except KeyError:
        raise ValueError(f"Unknown source {name!r}. Available: {', '.join(SOURCES)}") from None


__all__ = [
    "SOURCES",
    "HabrCareerSource",
    "HeadHunterSource",
    "SampleSource",
    "SearchQuery",
    "SourceUnavailableError",
    "VacancySource",
    "get_source",
]
