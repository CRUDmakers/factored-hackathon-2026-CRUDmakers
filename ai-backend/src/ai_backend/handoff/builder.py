"""Build the handoff from state (code, not the model)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from ai_backend.handoff.models import (
    Evidence,
    GeneratedList,
    GeneratedText,
    Handoff,
    HandoffAction,
    HandoffFact,
)
from ai_backend.policy.models import HIGH_PRIORITY, ReasonCode


def build(
    *,
    conversation_id: str,
    customer_id: str,
    language: str,
    reason_codes: list[str],
    verified_facts: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    trace_id: str,
    now: datetime,
    model_id: str,
    summary: str | None = None,
    open_questions: list[str] | None = None,
    customer_message: str | None = None,
) -> Handoff:
    codes = list(dict.fromkeys(reason_codes))  # keep order, drop repeats
    facts = _unique_facts(verified_facts)
    transaction_ids = list(
        dict.fromkeys(
            [f["record_id"] for f in facts if str(f.get("record_id", "")).startswith("TRX-")]
            + [a["transaction_id"] for a in actions if a.get("transaction_id")]
        )
    )
    return Handoff(
        handoff_id=f"HND-{uuid.uuid4().hex[:12].upper()}",
        conversation_id=conversation_id,
        customer_id=customer_id,
        language="pt" if language == "pt" else "es",
        priority="high" if any(c in HIGH_PRIORITY for c in codes) else "normal",
        reason_codes=codes,
        customer_message=customer_message,
        request_summary=(
            GeneratedText(text=summary, generated_by=f"model:{model_id}")
            if summary
            else GeneratedText(text=_system_summary(codes), generated_by="system")
        ),
        verified_facts=[
            HandoffFact(fact=f["fact"], source=f["source_tool"], record_id=f.get("record_id"))
            for f in facts
        ],
        actions_taken=[
            HandoffAction(
                type=a["method"],
                status=a["status"],
                verified=a["verified"],
                record_id=a.get("transaction_id"),
            )
            for a in actions
        ],
        evidence=Evidence(transaction_ids=transaction_ids, trace_id=trace_id),
        open_questions=GeneratedList(
            items=list(open_questions or []),
            generated_by=f"model:{model_id}" if open_questions else "system",
        ),
        created_at=now,
    )


_SUMMARIES = {
    ReasonCode.FRAUD_RISK: "A transaction the customer asked about is flagged for fraud.",
    ReasonCode.PRODUCT_BLOCKED: "The customer's product involved is blocked or suspended.",
    ReasonCode.AMOUNT_OVER_LIMIT: "The requested payment exceeds the automatic limit.",
    ReasonCode.OUTCOME_UNKNOWN: "A confirmed payment timed out and could not be found afterwards.",
    ReasonCode.VERIFY_MISMATCH: "A payment's read-back did not match what the customer confirmed.",
    ReasonCode.LIMIT_REACHED: "The request needed more steps than the assistant may take.",
    ReasonCode.ASSISTANT_FAILURE: "The assistant's model failed or refused to answer.",
    ReasonCode.BANK_UNAVAILABLE: "The bank's systems did not answer, even after retries.",
    ReasonCode.HUMAN_ROUTE: "The triage model found that this request needs a person.",
    ReasonCode.REPEAT_CONTACT: "The customer has asked about the same problem in earlier "
    "conversations this week.",
    ReasonCode.CROSS_CUSTOMER: "The bank refused a record as belonging to another customer.",
}


def _system_summary(codes: list[str]) -> str:
    parts = [_SUMMARIES.get(ReasonCode(c), f"Escalated: {c}.") for c in codes]
    return " ".join(parts)


def _unique_facts(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None]] = set()
    unique = []
    for f in facts:
        key = (f["fact"], f.get("record_id"))
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique
