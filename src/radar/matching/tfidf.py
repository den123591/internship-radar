"""TF-IDF и косинусная близость, реализованные с нуля — без scikit-learn.

Зачем своё: показать, как это работает внутри, и не тянуть тяжёлую зависимость
ради пары сотен документов.

    tf(t, d)  = count(t, d) / len(d)
    idf(t)    = ln((1 + N) / (1 + df(t))) + 1       # сглаженный, как в sklearn
    w(t, d)   = tf(t, d) * idf(t)
    cos(a, b) = (a · b) / (|a| * |b|)
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable, Sequence

TOKEN_RE = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9+#]*(?:\.[a-z]+)?", re.IGNORECASE)

STOPWORDS = frozenset(
    """
    и в во на с со по для от до из к ко у о об а но или не что как это мы вы
    будет будете быть есть наш наша наши ваш ваша работа работы работать опыт
    the a an and or of to in on for with at by is are be we you our your
    """.split()
)

# Грубый стеммер для русского: срезаем самые частые окончания.
# Для матчинга «разработка/разработчик/разработки» этого достаточно.
_RU_SUFFIXES = sorted(
    "ами ями ого его ому ему ыми ими ая яя ое ее ые ие ой ей ий ый ов ев ам ям ах ях ом ем "
    "ия ья ию ью а я о е ы и у ю".split(),
    key=len,
    reverse=True,
)
_CYRILLIC = re.compile(r"[а-яё]")


def stem(token: str) -> str:
    if not _CYRILLIC.search(token) or len(token) <= 4:
        return token
    for suffix in _RU_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text: str) -> list[str]:
    tokens = (t.lower() for t in TOKEN_RE.findall(text or ""))
    return [stem(t) for t in tokens if t not in STOPWORDS and len(t) > 1]


Vector = dict[str, float]


class TfidfIndex:
    """Индекс над коллекцией документов: fit один раз, потом быстрые запросы."""

    def __init__(self) -> None:
        self.idf: dict[str, float] = {}
        self.vectors: list[Vector] = []

    def fit(self, documents: Sequence[Iterable[str]]) -> TfidfIndex:
        docs = [list(d) for d in documents]
        n = len(docs)
        df: Counter[str] = Counter()
        for doc in docs:
            df.update(set(doc))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
        self.vectors = [self.vectorize(doc) for doc in docs]
        return self

    def vectorize(self, tokens: Iterable[str]) -> Vector:
        counts = Counter(tokens)
        total = sum(counts.values())
        if total == 0:
            return {}
        # Термины, которых нет в корпусе, получают максимальный idf.
        default_idf = max(self.idf.values(), default=1.0)
        return {t: (c / total) * self.idf.get(t, default_idf) for t, c in counts.items()}

    def query(self, tokens: Iterable[str]) -> list[float]:
        q = self.vectorize(tokens)
        return [cosine(q, v) for v in self.vectors]


def cosine(a: Vector, b: Vector) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):  # итерируемся по меньшему словарю
        a, b = b, a
    dot = sum(w * b.get(t, 0.0) for t, w in a.items())
    norm = math.sqrt(sum(w * w for w in a.values())) * math.sqrt(sum(w * w for w in b.values()))
    return dot / norm if norm else 0.0
