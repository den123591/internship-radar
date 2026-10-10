from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки из переменных окружения (префикс RADAR_) или файла .env."""

    model_config = SettingsConfigDict(env_prefix="RADAR_", env_file=".env", extra="ignore")

    # SQLite по умолчанию, чтобы проект запускался без инфраструктуры.
    # В docker-compose подставляется PostgreSQL.
    database_url: str = "sqlite:///radar.db"

    # Вежливый скрейпинг: не чаще одного запроса в секунду.
    request_interval_s: float = 1.0
    user_agent: str = "InternshipRadar/0.1 (+https://github.com/den123591/internship-radar)"

    # Токен приложения hh.ru — анонимный доступ к API у hh закрыт.
    hh_token: str | None = None

    # LLM-матчинг включается, только если есть ключ Anthropic.
    llm_model: str = "claude-opus-5-5"
    llm_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
