# Internship Radar — инструкции для AI-агентов

## Команды
- Установка: `pip install -e ".[dev]"`
- Тесты: `pytest` (на PostgreSQL: `RADAR_TEST_DATABASE_URL=postgresql+psycopg://... pytest`)
- Линтер: `ruff check src tests && ruff format --check src tests`
- Локальный запуск: `radar ingest --source sample && radar serve`

## Правила
- Новый источник данных — класс с `name` и `fetch(query) -> Iterator[Vacancy]` в `src/radar/sources/`,
  регистрация в `SOURCES`. Сетевые вызовы — только через `RateLimiter` и `@retry`.
- SQL в `analytics.py` должен работать и в SQLite, и в PostgreSQL. Диалектные различия — в отдельных
  функциях (как `_week_expr`). Nullable-параметры приводить через `CAST`.
- `etl.transform` остаётся чистой функцией: никакой сети и БД.
- LLM вызывается только для уже отранжированных вакансий; сервис обязан работать без ключа.
- Тесты не ходят в сеть: `httpx.MockTransport` для HTTP, заглушки для LLM.
- Данные из внешних источников в дашборде всегда экранируются (`esc()`).
