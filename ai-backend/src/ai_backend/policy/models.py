"""Policy decisions and reason codes (ARCHITECTURE §9)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal

Decision = Literal["allow", "confirm", "deny", "escalate"]


class ReasonCode(StrEnum):
    AUTH_EXPIRED = "AUTH_EXPIRED"
    TOOL_UNKNOWN = "TOOL_UNKNOWN"
    WRITE_NEEDS_CONFIRMATION = "WRITE_NEEDS_CONFIRMATION"
    ONE_ACTION_AT_A_TIME = "ONE_ACTION_AT_A_TIME"
    AMOUNT_OVER_LIMIT = "AMOUNT_OVER_LIMIT"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    CARD_EXPIRED = "CARD_EXPIRED"
    INVALID_DESTINATION = "INVALID_DESTINATION"
    INVALID_REQUEST = "INVALID_REQUEST"
    PRODUCT_BLOCKED = "PRODUCT_BLOCKED"
    FRAUD_RISK = "FRAUD_RISK"
    UNRECOGNIZED_CHARGE = "UNRECOGNIZED_CHARGE"
    DELINQUENT = "DELINQUENT"
    FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    REPEAT_CONTACT = "REPEAT_CONTACT"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    VERIFY_MISMATCH = "VERIFY_MISMATCH"
    LIMIT_REACHED = "LIMIT_REACHED"
    ASSISTANT_FAILURE = "ASSISTANT_FAILURE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    CROSS_CUSTOMER = "CROSS_CUSTOMER"


# Reasons that make a handoff urgent.
HIGH_PRIORITY = frozenset(
    {
        ReasonCode.FRAUD_RISK,
        ReasonCode.UNRECOGNIZED_CHARGE,
        ReasonCode.CROSS_CUSTOMER,
        ReasonCode.OUTCOME_UNKNOWN,
        ReasonCode.VERIFY_MISMATCH,
    }
)


@dataclass(frozen=True)
class PolicyDecision:
    decision: Decision
    reason_code: ReasonCode | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def message_key(self) -> str | None:
        """Key of the fixed customer message for this decision, if any."""
        return self.reason_code.value.lower() if self.reason_code else None


ALLOW = PolicyDecision("allow")
