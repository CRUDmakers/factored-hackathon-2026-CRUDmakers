"""The systems under evaluation (SPEC §11.2), behind one interface.

- S:  the full system (ChatService: policy engine, classifier triage, confirmation, handoff).
- B1: the same model, tools and prompt in a plain tool loop: no policy engine, no classifier,
      writes run immediately. It lives here, never in the service, because it is unsafe.
- B0: a keyword FAQ bot on the baseline rules, with canned answers from the bank's data.

Every system gets the same per-case environment: a fresh copy of the fake bank, the scenario's
clock, faults, patches and session, and the same auth check at the door.
"""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from types import SimpleNamespace
from typing import Any, Protocol

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage, ToolMessage

from ai_backend.agent import messages as text
from ai_backend.agent.nodes import _content_text, _frame, system_prompt
from ai_backend.agent.service import ChatService, LoginRequired
from ai_backend.auth.session import Session
from ai_backend.bank.client import AuthExpired, BankError
from ai_backend.bank.fake_client import FakeBankClient
from ai_backend.bank.faults import BankFault, FaultyBankClient
from ai_backend.bank.fixture import BankFixture
from ai_backend.classifier import baseline_rules
from ai_backend.conversations.store import MemoryConversationStore
from ai_backend.handoff.store import MemoryHandoffStore
from ai_backend.language.detect import detect
from ai_backend.observability.store import MemoryTraceStore
from ai_backend.policy.rules import HANDOFF_REASONS
from ai_backend.storage import InProcessLock
from ai_backend.tools.definitions import ToolContext, ToolResult
from ai_backend.tools.payments import HandoffArgs, to_payment_request
from ai_backend.tools.registry import REGISTRY
from eval.scenarios import Scenario
from eval.transcript import Transcript, TurnRecord

CONFIRMATION_TEXT = {"approve": "Confirmo.", "reject": "Cancelo."}
MAX_STEPS = 6


# ---------- the per-case environment ----------


class CaseEnv:
    def __init__(self, scenario: Scenario, fixture: BankFixture) -> None:
        self.scenario = scenario
        now = datetime.combine(scenario.today, dtime(12, 0), tzinfo=UTC)
        self.clock = lambda: now
        fx = copy.deepcopy(fixture)
        for patch in scenario.bank_patches:
            setattr(fx.transactions[patch.transaction_id], patch.field, patch.value)
        self.fake = FakeBankClient(fx, clock=self.clock)
        faults = [BankFault(**f.model_dump(exclude_none=True)) for f in scenario.bank_faults]
        self.bank: Any = FaultyBankClient(self.fake, faults) if faults else self.fake
        self.token = self._token(scenario)

    def _token(self, scenario: Scenario) -> str | None:
        if scenario.session == "missing":
            return None
        ttl = timedelta(seconds=-1) if scenario.session == "expired" else timedelta(minutes=15)
        session = self.fake.issue_test_session(scenario.customer_id, ttl=ttl)
        token = session.token.get_secret_value()  # type: ignore[union-attr]
        if scenario.session == "revoked":
            self.fake.revoke_session(token)
        return token

    async def authenticate(self) -> Session:
        """The API's auth check, identical for every system."""
        if not self.token:
            raise LoginRequired()
        try:
            return await self.fake.get_session(self.token)
        except AuthExpired as exc:
            raise LoginRequired() from exc

    def payments(self) -> list[tuple[str, str, str]]:
        return sorted(
            (t.transaction_id, t.payment_method or "", t.status)
            for t in self.fake.fixture.transactions.values()
            if t.origin == "simulated"
            and t.customer_id == self.scenario.customer_id
            and t.transaction_type in ("Payment", "Transfer")
        )


def turn_texts(scenario: Scenario) -> list[tuple[str, str | None]]:
    """(text shown to text-only systems, confirmation decision or None) per turn."""
    return [
        (t.user, None) if t.user is not None else (CONFIRMATION_TEXT[t.confirm], t.confirm)  # type: ignore[index]
        for t in scenario.turns
    ]


class System(Protocol):
    name: str

    async def run(self, env: CaseEnv) -> Transcript: ...


def _record_payments(env: CaseEnv, before: set, turn: int, transcript: Transcript) -> set:
    now = set(env.payments())
    for _, method, status in sorted(now - before):
        transcript.payments.append({"method": method, "status": status, "turn": turn})
    return now


# ---------- S: the full system ----------


class FullSystem:
    name = "S"

    def __init__(self, service: ChatService) -> None:
        self.base = service

    async def run(self, env: CaseEnv) -> Transcript:
        s = env.scenario
        service = replace(
            self.base,
            bank=env.bank,
            clock=env.clock,
            conversations=MemoryConversationStore(),
            traces=MemoryTraceStore(),
            handoffs=MemoryHandoffStore(),
            locks=InProcessLock(),
        )
        # The auth check in the service uses the (possibly faulty) bank; faults target other
        # methods, so the session check behaves like everywhere else.
        transcript = Transcript(s.id, self.name)
        conversation_id: str | None = None
        pending: str | None = None
        seen = set(env.payments())
        for i, (shown, decision) in enumerate(turn_texts(s)):
            start = time.perf_counter()
            try:
                if decision is not None:
                    confirmation = {"action_id": pending or "act_none", "decision": decision}
                    result = await service.turn(env.token, None, conversation_id, confirmation)
                else:
                    result = await service.turn(env.token, shown, conversation_id)
            except LoginRequired:
                transcript.turns.append(
                    TurnRecord(shown, "login_required", text.LOGIN_REQUIRED, _ms(start))
                )
                break
            conversation_id = result.conversation_id
            pending = (result.pending_action or {}).get("action_id") or pending
            transcript.turns.append(TurnRecord(shown, result.status, result.message, _ms(start)))
            seen = _record_payments(env, seen, i, transcript)
        if conversation_id:
            await self._collect(service, conversation_id, transcript)
        return transcript

    async def _collect(self, service: ChatService, conversation_id: str, t: Transcript) -> None:
        events = await service.traces.for_conversation(conversation_id)
        turn_tokens: dict[str, list[int]] = {}
        for e in events:
            if e.node == "tool" and e.tool:
                t.tools_called.append(e.tool)
            if e.node == "prepare_write" and e.tool:
                t.tools_called.append(e.tool)
            if e.node == "policy_gate" and e.outcome:
                for part in e.outcome.split(", "):
                    name, _, rest = part.partition("=")
                    if rest.startswith(("deny", "escalate")):
                        t.tools_called.append(name)
            if e.reason_code and e.node in (
                "route",
                "handoff",
                "escalation_check",
                "prepare_write",
            ):
                t.reason_codes.append(e.reason_code)
            if e.node == "agent":
                acc = turn_tokens.setdefault(e.turn_id, [0, 0])
                acc[0] += e.tokens_in or 0
                acc[1] += e.tokens_out or 0
        for record in service.handoffs.all():  # type: ignore[attr-defined]
            t.reason_codes.extend(record.reason_codes)
        turns = list(dict.fromkeys(e.turn_id for e in events))
        for turn_record, turn_id in zip(t.turns, turns, strict=False):
            turn_record.tokens_in, turn_record.tokens_out = turn_tokens.get(turn_id, [0, 0])


# ---------- B1: LLM + tools, no policy, no classifier ----------


class ToolLoopSystem:
    name = "B1"

    def __init__(self, llm: Any, history_end: Any) -> None:
        self.llm = llm
        self.history_end = history_end

    async def run(self, env: CaseEnv) -> Transcript:
        s = env.scenario
        transcript = Transcript(s.id, self.name)
        try:
            session = await env.authenticate()
        except LoginRequired:
            transcript.turns.append(
                TurnRecord(turn_texts(s)[0][0], "login_required", text.LOGIN_REQUIRED, 0.0)
            )
            return transcript
        ctx = SimpleNamespace(today=s.today, history_end=self.history_end)
        tool_ctx = ToolContext(bank=env.bank, session=session, today=s.today)
        history: list[AnyMessage] = []
        seen = set(env.payments())
        language = "es"
        for i, (shown, _) in enumerate(turn_texts(s)):
            start = time.perf_counter()
            detected = detect(shown, language)
            language = detected if detected != "other" else language
            history.append(HumanMessage(shown))
            status, reply, tokens = await self._turn(history, ctx, tool_ctx, language, transcript)
            transcript.turns.append(
                TurnRecord(shown, status, reply, _ms(start), tokens[0], tokens[1])
            )
            seen = _record_payments(env, seen, i, transcript)
            if status in ("handed_off", "login_required"):
                break
        return transcript

    async def _turn(self, history, ctx, tool_ctx, language, transcript):  # noqa: ANN001
        tokens = [0, 0]
        for _ in range(MAX_STEPS):
            prompt = [SystemMessage(system_prompt(ctx, language)), *history]  # type: ignore[arg-type]
            try:
                ai: AIMessage = await self.llm.ainvoke(prompt)
            except Exception as exc:  # the baseline has no fallback: an empty answer
                transcript.error = f"{type(exc).__name__}: {exc}"[:200]
                return "answered", "", tokens
            usage = ai.usage_metadata or {}
            tokens[0] += usage.get("input_tokens", 0)
            tokens[1] += usage.get("output_tokens", 0)
            history.append(ai)
            if not ai.tool_calls:
                return "answered", _content_text(ai), tokens
            for call in ai.tool_calls:
                transcript.tools_called.append(call["name"])
                result = await self._call(call, tool_ctx)
                if result == "handoff":
                    args = (
                        HandoffArgs.model_validate(call.get("args") or {})
                        if call.get("args")
                        else None
                    )
                    code = HANDOFF_REASONS.get(args.reason if args else "", None)
                    transcript.reason_codes.append(code.value if code else "CUSTOMER_REQUEST")
                    return (
                        "handed_off",
                        text.message("handoff", language, handoff_id="HND-B1"),
                        tokens,
                    )
                if result == "login_required":
                    return "login_required", text.LOGIN_REQUIRED, tokens
                history.append(
                    ToolMessage(
                        _frame(call["name"], result), tool_call_id=call["id"], name=call["name"]
                    )
                )
        return "answered", "", tokens

    async def _call(self, call: dict[str, Any], ctx: ToolContext) -> ToolResult | str:
        spec = REGISTRY.get(call["name"])
        if spec is None:
            return ToolResult.error("unknown_tool", "No such tool.")
        if spec.kind == "escalate":
            return "handoff"
        try:
            if spec.kind == "read":
                return await spec.run(ctx, call.get("args") or {})
            args = spec.parse(call.get("args") or {})
            if isinstance(args, ToolResult):
                return args
            result = await ctx.bank.execute_payment(  # no preview, no confirmation, no policy
                ctx.session,
                to_payment_request(call["name"], args),
                uuid.uuid4().hex,  # type: ignore[arg-type]
            )
            return ToolResult(ok=True, data=result.model_dump(mode="json", by_alias=True))
        except AuthExpired:
            return "login_required"
        except BankError as exc:
            return ToolResult.error("bank_error", str(exc)[:200])


# ---------- B0: keyword FAQ bot ----------


class KeywordBot:
    name = "B0"

    async def run(self, env: CaseEnv) -> Transcript:
        s = env.scenario
        transcript = Transcript(s.id, self.name)
        try:
            session = await env.authenticate()
        except LoginRequired:
            transcript.turns.append(
                TurnRecord(turn_texts(s)[0][0], "login_required", text.LOGIN_REQUIRED, 0.0)
            )
            return transcript
        ctx = ToolContext(bank=env.bank, session=session, today=s.today)
        language = "es"
        for shown, _ in turn_texts(s):
            start = time.perf_counter()
            detected = detect(shown, language)
            if detected == "other":
                transcript.turns.append(
                    TurnRecord(shown, "refused", text.UNSUPPORTED_LANGUAGE, _ms(start))
                )
                continue
            language = detected
            status, reply = await self._answer(shown, language, ctx, transcript)
            transcript.turns.append(TurnRecord(shown, status, reply, _ms(start)))
            if status in ("handed_off", "login_required"):
                break
        return transcript

    async def _answer(
        self, message: str, lang: str, ctx: ToolContext, t: Transcript
    ) -> tuple[str, str]:
        route = baseline_rules.route(message)
        es = lang == "es"
        if route == "human":
            t.reason_codes.append("HUMAN_ROUTE")
            return "handed_off", text.message("handoff", lang, handoff_id="HND-B0")  # type: ignore[arg-type]
        if route == "out_of_scope":
            return "refused", text.message("out_of_scope", lang)  # type: ignore[arg-type]
        if route == "clarify":
            return "answered", "¿Puedes darme más detalles?" if es else "Pode me dar mais detalhes?"
        n = baseline_rules.normalise(message)
        has = baseline_rules.contains
        try:
            if has(n, PAYMENT_WORDS) and not has(n, STATUS_QUESTION_WORDS):
                return "answered", (
                    "Para pagos y transferencias, usa la app o la banca en línea."
                    if es
                    else "Para pagamentos e transferências, use o aplicativo ou o internet banking."
                )
            if has(n, BALANCE_WORDS) and not has(n, STATUS_QUESTION_WORDS):
                t.tools_called.append("get_balances")
                return "answered", _balances_text(await REGISTRY["get_balances"].run(ctx, {}), es)
            if has(n, FX_WORDS) and not has(n, STATUS_QUESTION_WORDS):
                return "answered", (
                    "Consulta el tipo de cambio del día en la app."
                    if es
                    else "Consulte o câmbio do dia no aplicativo."
                )
            t.tools_called.append("search_transactions")
            result = await REGISTRY["search_transactions"].run(ctx, {"limit": 5})
            return "answered", _transactions_text(result, es)
        except AuthExpired:
            return "login_required", text.LOGIN_REQUIRED


PAYMENT_WORDS = ("transfer", "pagar", "paga", "boleto", "factura", "mandar", "enviar")
STATUS_QUESTION_WORDS = ("rechaz", "recus", "paso", "passou", "aprob", "aprov", "por que", "por qu")
BALANCE_WORDS = (
    "saldo",
    "cuanto",
    "quanto",
    "debo",
    "devo",
    "limite",
    "vence",
    "validade",
    "disponible",
    "disponivel",
)
FX_WORDS = ("cambio", "dolar", "convert", "cotiz", "cotac")
STATUS_TEXT = {
    True: {
        "Approved": "aprobada",
        "Declined": "rechazada",
        "Pending": "pendiente",
        "Reversed": "reversada",
    },
    False: {
        "Approved": "aprovada",
        "Declined": "recusada",
        "Pending": "pendente",
        "Reversed": "estornada",
    },
}


def _balances_text(result: ToolResult, es: bool) -> str:
    if not result.ok:
        return "No pude consultar tus saldos." if es else "Não consegui consultar seus saldos."
    lines = ["Tus productos:" if es else "Seus produtos:"]
    for a in result.data["accounts"]:
        lines.append(
            f"- {a['product_type']} {a['product_number'] or ''}: {a['balance']} {a['currency']}"
        )
    owes, available, expires = (
        ("debe", "disponible", "vence") if es else ("deve", "disponível", "vence")
    )
    for c in result.data["credit_cards"]:
        lines.append(
            f"- Tarjeta Crédito {c['product_number'] or ''}: {owes} {c['invoice_amount']}, "
            f"{available} {c['available_credit']} {c['currency']}, {expires} {c['expiration_date']}"
        )
    return "\n".join(lines)


def _transactions_text(result: ToolResult, es: bool) -> str:
    if not result.ok:
        return (
            "No pude consultar tus movimientos."
            if es
            else "Não consegui consultar suas movimentações."
        )
    lines = ["Tus últimos movimientos:" if es else "Suas últimas movimentações:"]
    for tx in result.data["transactions"]:
        code = (
            f" ({'código' if es else 'código'} {tx['response_code']})"
            if tx.get("response_code")
            else ""
        )
        status = STATUS_TEXT[es].get(tx["transaction_status"], tx["transaction_status"])
        lines.append(
            f"- {tx['transaction_date'][:10]} {tx['transaction_type']} {tx['amount']} "
            f"{tx['currency']} {tx.get('merchant_name') or ''}: {status}{code}"
        )
    return "\n".join(lines)


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)
