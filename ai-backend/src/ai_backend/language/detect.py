"""Which language the customer is writing in: `es`, `pt` or `other` (SPEC §8.1 preprocess).

Short replies ("sim", "ok", "gracias") are ambiguous, so they keep the conversation's language.
A message counts as `other` only when it is clearly in another language and long enough to tell.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

Lang = Literal["es", "pt", "other"]

# Candidates: our two languages plus the ones customers are most likely to use instead.
_CANDIDATES = (
    Language.SPANISH, Language.PORTUGUESE, Language.ENGLISH, Language.FRENCH, Language.ITALIAN,
)
_MIN_WORDS = 3
_OURS_MIN = 0.5  # confidence needed to pick es/pt outright
_OTHER_MIN = 0.6  # confidence needed to call a message "other"


@lru_cache(maxsize=1)
def _detector() -> LanguageDetector:
    return LanguageDetectorBuilder.from_languages(*_CANDIDATES).build()


def detect(text: str, previous: Lang | None = None) -> Lang:
    words = len(text.split())
    fallback: Lang = previous if previous in ("es", "pt") else "es"
    if not any(ch.isalpha() for ch in text):
        return fallback

    scores = {v.language: v.value for v in _detector().compute_language_confidence_values(text)}
    es, pt = scores.get(Language.SPANISH, 0.0), scores.get(Language.PORTUGUESE, 0.0)
    other = max(
        (v for lang, v in scores.items() if lang not in (Language.SPANISH, Language.PORTUGUESE)),
        default=0.0,
    )
    ours: Lang = "es" if es >= pt else "pt"

    if words < _MIN_WORDS:
        # Too short to override the conversation, unless there's no conversation yet.
        return previous if previous in ("es", "pt") else ours
    if max(es, pt) >= _OURS_MIN:
        return ours
    if other >= _OTHER_MIN:
        return "other"
    return fallback
