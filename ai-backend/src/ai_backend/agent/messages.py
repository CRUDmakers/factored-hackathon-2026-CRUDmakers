"""Fixed customer-facing messages (not model-generated), in the customer's language."""

from __future__ import annotations

from ai_backend.language.detect import Lang

UNSUPPORTED_LANGUAGE = (
    "Por ahora solo puedo atenderte en español o portugués. "
    "/ Por enquanto só posso atender em espanhol ou português."
)
LOGIN_REQUIRED = (
    "Tu sesión terminó. Inicia sesión de nuevo para continuar. "
    "/ Sua sessão terminou. Entre novamente para continuar."
)

_BY_LANGUAGE: dict[str, dict[str, str]] = {
    "llm_failed": {
        "es": "Lo siento, no pude procesar tu mensaje en este momento. Inténtalo de nuevo "
        "en unos minutos o comunícate con un agente del banco.",
        "pt": "Desculpe, não consegui processar sua mensagem agora. Tente novamente em "
        "alguns minutos ou fale com um atendente do banco.",
    },
    "limit_reached": {
        "es": "Esta consulta necesita más pasos de los que puedo dar aquí. Te recomiendo "
        "hablar con un agente del banco.",
        "pt": "Esta consulta precisa de mais passos do que consigo fazer aqui. Recomendo "
        "falar com um atendente do banco.",
    },
}


def message(key: str, language: Lang | None) -> str:
    texts = _BY_LANGUAGE[key]
    return texts.get(language or "es", texts["es"])
