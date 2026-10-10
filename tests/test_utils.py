import pytest

from radar.utils import RateLimiter, retry, timed


def test_retry_succeeds_after_transient_failures():
    sleeps: list[float] = []
    calls = {"n": 0}

    @retry((ConnectionError,), attempts=3, base_delay=1.0, sleep=sleeps.append)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ConnectionError("boom")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3
    assert len(sleeps) == 2
    assert 0.5 <= sleeps[0] <= 1.0 and 1.0 <= sleeps[1] <= 2.0  # экспонента с jitter


def test_retry_reraises_after_last_attempt_and_ignores_other_errors():
    @retry((ConnectionError,), attempts=2, sleep=lambda _: None)
    def always_fails():
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        always_fails()

    @retry((ConnectionError,), attempts=5, sleep=lambda _: None)
    def wrong_type():
        raise ValueError("not retried")

    with pytest.raises(ValueError):
        wrong_type()


def test_retry_preserves_function_metadata():
    @retry((Exception,))
    def documented():
        """docstring"""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "docstring"


def test_rate_limiter_waits_only_remaining_interval():
    now = {"t": 100.0}
    slept: list[float] = []

    def fake_sleep(s: float) -> None:
        slept.append(s)
        now["t"] += s

    limiter = RateLimiter(1.0, clock=lambda: now["t"], sleep=fake_sleep)
    limiter.wait()  # первый вызов — без ожидания
    now["t"] += 0.3
    limiter.wait()  # прошло 0.3с — ждём ещё 0.7
    now["t"] += 5
    limiter.wait()  # интервал уже прошёл
    assert slept == [pytest.approx(0.7)]


def test_timed_reports_duration_even_on_error():
    with pytest.raises(RuntimeError), timed("block") as result:
        raise RuntimeError
    assert result["seconds"] >= 0
