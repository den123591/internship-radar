"""LLM-слой: объяснение соответствия резюме вакансии и черновик сопроводительного письма.

Используется только поверх детерминированного ранжирования (TF-IDF + навыки):
LLM получает уже отобранные топ-N вакансий, а не всю базу — так дешевле и
предсказуемее. Если ключа нет, сервис работает без этого слоя.
"""

from __future__ import annotations

import logging
import os

import anthropic
from pydantic import BaseModel, Field

from radar.config import get_settings
from radar.models import Vacancy

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Ты — карьерный консультант для студентов, которые ищут первую IT-стажировку.
Тебе дают резюме кандидата и вакансию. Оцени соответствие честно: не завышай
оценку и не придумывай опыт, которого нет в резюме. Пиши по-русски, коротко и
конкретно. В сопроводительном письме опирайся только на факты из резюме."""


class LLMAssessment(BaseModel):
    fit_score: int = Field(description="Соответствие от 0 до 100")
    strengths: list[str] = Field(description="2–4 сильные стороны кандидата под эту вакансию")
    gaps: list[str] = Field(description="Чего не хватает, 1–3 пункта")
    advice: str = Field(description="Одно предложение: что подтянуть перед откликом")
    cover_letter: str = Field(description="Сопроводительное письмо, 5–7 предложений")


class LLMUnavailableError(RuntimeError):
    pass


def llm_available() -> bool:
    settings = get_settings()
    has_credentials = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
    return settings.llm_enabled and has_credentials


def _vacancy_prompt(v: Vacancy) -> str:
    parts = [
        f"Должность: {v.title}",
        f"Компания: {v.company}",
        f"Уровень: {v.level.value}",
        f"Формат: {'удалённо' if v.remote else 'офис/гибрид'}",
        f"Навыки: {', '.join(v.skills) or 'не указаны'}",
    ]
    if v.description:
        parts.append(f"Описание:\n{v.description}")
    return "\n".join(parts)


class LLMAdvisor:
    def __init__(self, client: anthropic.Anthropic | None = None, model: str | None = None):
        self.client = client or anthropic.Anthropic()
        self.model = model or get_settings().llm_model

    def assess(self, resume: str, vacancy: Vacancy) -> LLMAssessment:
        try:
            response = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=4000,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": f"<resume>\n{resume}\n</resume>\n\n"
                        f"<vacancy>\n{_vacancy_prompt(vacancy)}\n</vacancy>",
                    }
                ],
                output_format=LLMAssessment,
                output_config={"effort": "low"},
                # Если модель откажет по соображениям безопасности, API сам
                # повторит запрос на рекомендованной резервной модели.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailableError("Превышен лимит запросов к Claude API") from exc
        except anthropic.AuthenticationError as exc:
            raise LLMUnavailableError("Неверный ключ ANTHROPIC_API_KEY") from exc
        except anthropic.APIStatusError as exc:
            raise LLMUnavailableError(f"Claude API error {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError("Нет соединения с Claude API") from exc

        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise LLMUnavailableError("Модель не вернула оценку")
        return response.parsed_output
