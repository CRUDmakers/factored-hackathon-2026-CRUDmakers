"""The policy engine (SPEC §7): rules in a fixed order, first match wins.

Pure functions: same input, same decision. The graph asks; code decides.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ai_backend.config import PolicyConfig
from ai_backend.policy import rules
from ai_backend.policy.models import ALLOW, PolicyDecision, ReasonCode
from ai_backend.policy.rules import ToolCall, TurnFacts


def evaluate(call: ToolCall, facts: TurnFacts, config: PolicyConfig) -> PolicyDecision:
    """Before a tool runs. Order: session, unknown tool, cross-customer, budget, escalation,
    write → confirmation, otherwise allow."""
    return (
        rules.session_valid(facts)
        or rules.tool_known(call)
        or rules.no_cross_customer(facts)
        or rules.within_budget(facts, config)
        or rules.escalation_requested(call)
        or rules.write_needs_confirmation(call)
        or ALLOW
    )


def check_preview(
    *,
    rejection_code: str | None,
    status: str | None,
    response_code: str | None,
    amount_usd: Decimal | None,
    config: PolicyConfig,
) -> PolicyDecision:
    """After Node's dry run. Order: rejected request, amount limit, decline, otherwise confirm."""
    return (
        rules.rejected_request(rejection_code)
        or rules.amount_within_limit(amount_usd, config)
        or rules.preview_declined(status or "", response_code or "")
        or PolicyDecision("confirm", ReasonCode.WRITE_NEEDS_CONFIRMATION)
    )


def post_tool_checks(
    policy_facts: list[dict[str, Any]], config: PolicyConfig
) -> list[PolicyDecision]:
    """After reads: escalations the model didn't ask for (fraud flag, blocked product)."""
    decisions: list[PolicyDecision] = []
    for fact in policy_facts:
        if fact.get("kind") != "transaction":
            continue
        for decision in (rules.fraud_risk(fact, config), rules.product_blocked(fact)):
            if decision is not None:
                decisions.append(decision)
    return decisions


def verify_readback(expected: dict[str, Any], actual: dict[str, Any]) -> PolicyDecision:
    """After a payment: is what Node recorded what the customer confirmed?"""
    return rules.readback_matches(expected, actual) or ALLOW
