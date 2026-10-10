"""Небольшие инфраструктурные утилиты: ретраи, rate limiting, замер времени."""

from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import ParamSpec, TypeVar

log = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def retry(
    exceptions: tuple[type[BaseException], ...],
    attempts: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 8.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Повторяет вызов при указанных исключениях с экспоненциальной задержкой и jitter.

    `sleep` можно подменить в тестах, чтобы они не ждали реальное время.
    """
    if attempts < 1:
        raise ValueError("attempts must be >= 1")

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(1, attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    if attempt == attempts:
                        raise
                    delay = min(max_delay, base_delay * 2 ** (attempt - 1))
                    delay *= random.uniform(0.5, 1.0)
                    log.warning(
                        "%s failed (%s), retry %d/%d in %.2fs",
                        func.__name__,
                        exc,
                        attempt,
                        attempts - 1,
                        delay,
                    )
                    sleep(delay)
            raise AssertionError("unreachable")

        return wrapper

    return decorator


class RateLimiter:
    """Гарантирует минимальный интервал между вызовами `wait()`."""

    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval_s = interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self.interval_s - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now += remaining
        self._last = now


@contextmanager
def timed(label: str) -> Iterator[dict[str, float]]:
    """Контекстный менеджер: логирует длительность блока и отдаёт её наружу."""
    result: dict[str, float] = {}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["seconds"] = time.perf_counter() - start
        log.info("%s took %.2fs", label, result["seconds"])
