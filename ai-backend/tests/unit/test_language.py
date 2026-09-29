import pytest

from ai_backend.language.detect import detect


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Meu pagamento de ontem na Uber foi aprovado?", "pt"),
        ("¿Mi pago de ayer en Uber fue aprobado?", "es"),
        ("Quanto tenho na conta corrente?", "pt"),
        ("Cuánto tengo en la cuenta de ahorro", "es"),
        ("Did my payment go through yesterday?", "other"),
        ("Est-ce que mon paiement est passé hier ?", "other"),
    ],
)
def test_full_sentences(text, expected):
    assert detect(text) == expected


@pytest.mark.parametrize("short", ["sim", "ok", "gracias", "👍", "123"])
def test_short_replies_keep_the_conversation_language(short):
    assert detect(short, previous="pt") == "pt"
    assert detect(short, previous="es") == "es"


def test_short_first_message_picks_es_or_pt():
    assert detect("obrigado") == "pt"
    assert detect("123") == "es"  # nothing to go on: default


def test_a_clear_switch_is_followed():
    assert detect("¿Y cuánto debo en la tarjeta de crédito?", previous="pt") == "es"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The statistical detector alone reads these as Spanish.
        ("Quero pagar um boleto", "pt"),
        ("quero ver meu saldo", "pt"),
        ("Qual é o meu score de crédito?", "pt"),
        ("me cobraron dos veces la misma compra", "es"),
        ("Quiero pagar una cuenta", "es"),
    ],
)
def test_words_of_one_language_only_decide_between_es_and_pt(text, expected):
    assert detect(text) == expected
