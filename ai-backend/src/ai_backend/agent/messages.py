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
    "handoff": {
        "es": "Te voy a comunicar con un agente del banco, que ya tendrá el contexto de esta "
        "conversación. Tu número de referencia es {handoff_id}.",
        "pt": "Vou transferir você para um atendente do banco, que já terá o contexto desta "
        "conversa. Seu número de referência é {handoff_id}.",
    },
    "cancelled": {
        "es": "Listo, cancelé la operación. No se movió dinero.",
        "pt": "Pronto, cancelei a operação. Nenhum dinheiro foi movimentado.",
    },
    "expired": {
        "es": "La confirmación venció, así que no ejecuté la operación. Si quieres, "
        "empecemos de nuevo.",
        "pt": "A confirmação expirou, então não executei a operação. Se quiser, "
        "começamos de novo.",
    },
    "no_pending": {
        "es": "No hay ninguna operación pendiente de confirmación.",
        "pt": "Não há nenhuma operação pendente de confirmação.",
    },
    "out_of_scope": {
        "es": "Eso no lo puedo resolver por aquí. Te puedo ayudar con saldos, movimientos, "
        "estado de pagos, transferencias, pago de cuentas, extractos y comprobantes en PDF y "
        "planillas de Excel; para lo demás, comunícate con el banco por sus canales oficiales.",
        "pt": "Isso eu não consigo resolver por aqui. Posso ajudar com saldos, extrato, status "
        "de pagamentos, transferências, pagamento de contas, extratos e comprovantes em PDF e "
        "planilhas de Excel; para o resto, fale com o banco pelos canais oficiais.",
    },
    "bank_refused_execution": {
        "es": "El banco no aceptó la operación al ejecutarla. No se movió dinero.",
        "pt": "O banco não aceitou a operação ao executá-la. Nenhum dinheiro foi movimentado.",
    },
}


def message(key: str, language: Lang | None, **values: str) -> str:
    texts = _BY_LANGUAGE[key]
    return texts.get(language or "es", texts["es"]).format(**values)


# Short answers to a pending confirmation, after lowercasing and removing accents/punctuation.
YES = frozenset(
    {
        "si", "sim", "yes", "ok", "okay", "confirmo", "confirmar", "confirmado", "confirma",
        "dale", "claro", "de acuerdo", "pode", "pode sim", "isso", "correcto", "correto",
        "si confirmo", "sim confirmo", "adelante", "pode seguir",
    }
)
NO = frozenset(
    {
        "no", "nao", "cancelar", "cancela", "cancelo", "no quiero", "nao quero",
        "mejor no", "melhor nao", "no gracias", "nao obrigado", "nao obrigada",
    }
)
