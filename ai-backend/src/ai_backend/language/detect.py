"""Which language the customer is writing in: `es`, `pt` or `other` (SPEC §8.1 preprocess).

Short replies ("sim", "ok", "gracias") are ambiguous, so they keep the conversation's language.
A message counts as `other` only when it is clearly in another language and long enough to tell.

The statistical detector confuses short Portuguese requests with Spanish ("Quero pagar um boleto"),
so words and spellings that exist in only one of the two languages decide between them first.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from lingua import Language, LanguageDetector, LanguageDetectorBuilder

Lang = Literal["es", "pt", "other"]

# Candidates: our two languages plus the ones customers are most likely to use instead.
_CANDIDATES = (
    Language.SPANISH,
    Language.PORTUGUESE,
    Language.ENGLISH,
    Language.FRENCH,
    Language.ITALIAN,
)
_MIN_WORDS = 3
_OURS_MIN = 0.5  # confidence needed to pick es/pt outright
_OTHER_MIN = 0.6  # confidence needed to call a message "other"


# Words used in only one of the two languages (a banking chat's vocabulary), and spellings:
# ç, ã, õ, "nh"/"lh" are Portuguese; ñ, "ll", "ción" are Spanish.
def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


_PT_WORDS = _words(
    "quero queria meu minha meus minhas você voce vocês não nao um uma uns umas pra pro das "
    "do ontem hoje extrato obrigado obrigada preciso falar conta contas tem errado sair fazer "
    "qual quanto quantos dá em na nas nos nova ao aos às é está estou isso esse essa até "
    "também tambem cadê fatura boleto dinheiro pagamento transferência cartão cartao atendente"
)
_ES_WORDS = (
    _words(
        "quiero quisiera mi mis tu cuenta cuentas tarjeta usted ustedes qué cuánto cuanto "
        "cuántos dónde donde ayer hoy una un unos del el los hay yo gracias dinero factura "
        "necesito hablar tengo hacer cuál cual está estoy eso ese esa hasta también tampoco pago "
        "pagos transferencia movimiento movimientos saldo"
    )
    - _PT_WORDS
)
_PT_SPELLING = re.compile(r"[çãõ]|nh|lh")
_ES_SPELLING = re.compile(r"ñ|ll|ción\b")


def _lexical(text: str) -> Lang | None:
    """es or pt when the words and spellings point one way only; None when they don't."""
    t = text.lower()
    words = re.findall(r"\w+", t)
    pt = sum(w in _PT_WORDS for w in words) + len(_PT_SPELLING.findall(t))
    es = sum(w in _ES_WORDS for w in words) + len(_ES_SPELLING.findall(t))
    if pt > es:
        return "pt"
    if es > pt:
        return "es"
    return None


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
    lexical = _lexical(text)
    ours: Lang = lexical or ("es" if es >= pt else "pt")

    if words < _MIN_WORDS:
        # Too short to override the conversation, unless there's no conversation yet.
        return previous if previous in ("es", "pt") else ours
    if max(es, pt) >= _OURS_MIN:
        return ours
    if other >= _OTHER_MIN:
        return "other"
    return lexical or fallback
