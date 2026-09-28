"""Individual policy rules: pure functions that return a decision, or None to pass.

Every threshold comes from `PolicyConfig` (config/policy.yaml); nothing here reads the
environment, the bank or the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from ai_backend.config import PolicyConfig
from ai_backend.policy.models import PolicyDecision, ReasonCode

# handoff_to_human's `reason` argument → reason code
HANDOFF_REASONS: dict[str, ReasonCode] = {
    "unrecognized_charge": ReasonCode.UNRECOGNIZED_CHARGE,
    "debt_arrangement": ReasonCode.DELINQUENT,
    "follow_up": ReasonCode.FOLLOW_UP_REQUIRED,
    "customer_request": ReasonCode.CUSTOMER_REQUEST,
}
BLOCKED_STATUSES = frozenset({"Blocked", "Suspended"})
# Node 422 codes about the destination (the customer can correct them)
DESTINATION_ERRORS = frozenset({"invalid_destination", "country_not_supported", "invalid_barcode"})


@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict[str, Any]
    kind: str | None  # read | write | escalate; None when the tool doesn't exist
    index_among_writes: int = 0  # 0 for the first write call in a model message


@dataclass(frozen=True)
class TurnFacts:
    """What the engine knows about the turn so far."""

    now: datetime
    session_expires_at: datetime
    tool_steps: int
    clarifications: int
    forbidden_seen: bool


def session_valid(facts: TurnFacts) -> PolicyDecision | None:
    if facts.now >= facts.session_expires_at:
        return PolicyDecision("deny", ReasonCode.AUTH_EXPIRED)
    return None


def tool_known(call: ToolCall) -> PolicyDecision | None:
    if call.kind is None:
        return PolicyDecision("deny", ReasonCode.TOOL_UNKNOWN, {"tool": call.name})
    return None


def no_cross_customer(facts: TurnFacts) -> PolicyDecision | None:
    # After Node refused a record as another customer's, nothing else runs in this turn.
    if facts.forbidden_seen:
        return PolicyDecision("escalate", ReasonCode.CROSS_CUSTOMER)
    return None


def within_budget(facts: TurnFacts, config: PolicyConfig) -> PolicyDecision | None:
    limits = config.limits
    if facts.tool_steps >= limits.max_tool_steps_per_turn:
        return PolicyDecision("escalate", ReasonCode.LIMIT_REACHED, {"limit": "tool_steps"})
    if facts.clarifications > limits.max_clarifications:
        return PolicyDecision("escalate", ReasonCode.LIMIT_REACHED, {"limit": "clarifications"})
    return None


def escalation_requested(call: ToolCall) -> PolicyDecision | None:
    if call.kind != "escalate":
        return None
    reason = HANDOFF_REASONS.get(str(call.args.get("reason")), ReasonCode.CUSTOMER_REQUEST)
    return PolicyDecision("escalate", reason)


def write_needs_confirmation(call: ToolCall) -> PolicyDecision | None:
    if call.kind != "write":
        return None
    if call.index_among_writes > 0:
        return PolicyDecision("deny", ReasonCode.ONE_ACTION_AT_A_TIME)
    return PolicyDecision("confirm", ReasonCode.WRITE_NEEDS_CONFIRMATION)


# ---------- payment previews ----------


def rejected_request(rejection_code: str | None) -> PolicyDecision | None:
    if rejection_code is None:
        return None
    reason = (
        ReasonCode.INVALID_DESTINATION
        if rejection_code in DESTINATION_ERRORS
        else ReasonCode.INVALID_REQUEST
    )
    return PolicyDecision("deny", reason, {"bank_code": rejection_code})


def amount_within_limit(amount_usd: Decimal | None, config: PolicyConfig) -> PolicyDecision | None:
    limit = config.limits.write_amount_limit_usd
    if amount_usd is None:
        # No USD rate to check against the limit: a human decides.
        return PolicyDecision("escalate", ReasonCode.AMOUNT_OVER_LIMIT, {"amount_usd": None})
    if amount_usd > limit:
        return PolicyDecision(
            "escalate", ReasonCode.AMOUNT_OVER_LIMIT, {"amount_usd": str(amount_usd)}
        )
    return None


_DECLINES: dict[str, PolicyDecision] = {
    "05": PolicyDecision("escalate", ReasonCode.PRODUCT_BLOCKED, {"bank_code": "05"}),
    "51": PolicyDecision("deny", ReasonCode.INSUFFICIENT_FUNDS, {"bank_code": "51"}),
    "54": PolicyDecision("deny", ReasonCode.CARD_EXPIRED, {"bank_code": "54"}),
    "14": PolicyDecision("deny", ReasonCode.INVALID_DESTINATION, {"bank_code": "14"}),
}


def preview_declined(status: str, response_code: str) -> PolicyDecision | None:
    if status != "Declined":
        return None
    unknown = PolicyDecision("deny", ReasonCode.INVALID_REQUEST, {"bank_code": response_code})
    return _DECLINES.get(response_code, unknown)


# ---------- facts that came back from reads ----------


def fraud_risk(fact: dict[str, Any], config: PolicyConfig) -> PolicyDecision | None:
    score = fact.get("fraud_score")
    threshold = config.thresholds.fraud_score_escalate
    if fact.get("flagged_as_fraud") or (score is not None and Decimal(str(score)) >= threshold):
        return PolicyDecision(
            "escalate", ReasonCode.FRAUD_RISK, {"transaction_id": fact.get("transaction_id")}
        )
    return None


def product_blocked(fact: dict[str, Any]) -> PolicyDecision | None:
    if fact.get("product_status") in BLOCKED_STATUSES:
        return PolicyDecision(
            "escalate", ReasonCode.PRODUCT_BLOCKED, {"product_id": fact.get("product_id")}
        )
    return None


def bank_unavailable(fact: dict[str, Any]) -> PolicyDecision | None:
    # Node failed even after the client's retries: the customer shouldn't wait on the model.
    if fact.get("kind") == "bank_unavailable":
        return PolicyDecision("escalate", ReasonCode.BANK_UNAVAILABLE, {"tool": fact.get("tool")})
    return None


# ---------- read-back after a payment ----------


def readback_matches(expected: dict[str, Any], actual: dict[str, Any]) -> PolicyDecision | None:
    fields = ("payment_method", "amount", "currency", "product_id")
    wrong = [f for f in fields if str(expected.get(f)) != str(actual.get(f))]
    if wrong:
        return PolicyDecision("escalate", ReasonCode.VERIFY_MISMATCH, {"fields": wrong})
    return None
