"""Tool registry: name → spec, and the JSON schemas the model is given (SPEC §6).

Schemas are strict (`additionalProperties: false` at every level) and simplified for
OpenAI-compatible providers: nested models are inlined (no `$ref`), optional fields are plain
types (no `anyOf` with null), and money is a number.
"""

from __future__ import annotations

from typing import Any

from ai_backend.tools.definitions import P0_READ_TOOLS, ToolSpec
from ai_backend.tools.files import FILE_TOOLS
from ai_backend.tools.payments import HandoffArgs, PayBillArgs, TransferMoneyArgs
from ai_backend.tools.recurring import RECURRING_TOOLS

P0_ACTION_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "transfer_money",
        "Move money from one of the customer's accounts: to one of their own products (e.g. to "
        "pay their credit card or loan), to another person's account at Banco LATAM, or to "
        "another bank in México, Colombia or Argentina. Ask for any missing detail (source "
        "account, destination, amount) first. The system shows the customer a confirmation "
        "built from the bank's preview: don't ask for confirmation yourself, and never say it's "
        "done.",
        TransferMoneyArgs,
        "write",
    ),
    ToolSpec(
        "pay_bill",
        "Pay a bill with its barcode (44 to 48 digits) from an account, debit card or credit "
        "card. Ask for any missing detail first. The system asks the customer to confirm.",
        PayBillArgs,
        "write",
    ),
    ToolSpec(
        "handoff_to_human",
        "Transfer the conversation to a human agent. Use it when the customer doesn't "
        "recognise a charge (unrecognized_charge), wants to negotiate or arrange a debt "
        "(debt_arrangement), wants follow-up on a pending or reversed transaction (follow_up), "
        "or asks for a person (customer_request). Summarise what they need.",
        HandoffArgs,
        "escalate",
    ),
)

REGISTRY: dict[str, ToolSpec] = {
    t.name: t for t in (*P0_READ_TOOLS, *P0_ACTION_TOOLS, *FILE_TOOLS, *RECURRING_TOOLS)
}


def get_tool(name: str) -> ToolSpec | None:
    return REGISTRY.get(name)


def tool_schemas(tools: dict[str, ToolSpec] | None = None) -> list[dict[str, Any]]:
    """OpenAI-format function definitions, accepted by every LangChain chat model."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": parameters_schema(spec),
            },
        }
        for spec in (tools or REGISTRY).values()
    ]


def parameters_schema(spec: ToolSpec) -> dict[str, Any]:
    schema = spec.args_model.model_json_schema(by_alias=True)
    return _object(schema, schema.get("$defs", {}))


def _object(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            name: _simplify(prop, defs) for name, prop in schema.get("properties", {}).items()
        },
        "required": schema.get("required", []),
        "additionalProperties": False,
    }


def _simplify(prop: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    prop = {k: v for k, v in prop.items() if k not in ("title", "default")}
    variants = prop.pop("anyOf", None)
    if variants:
        non_null = [v for v in variants if v.get("type") != "null"]
        types = {v.get("type") for v in non_null}
        if types == {"number", "string"}:  # pydantic's Decimal: send it as a number
            prop.update(type="number")
        elif len(non_null) == 1:
            prop.update({k: v for k, v in non_null[0].items() if k != "title"})
    if "$ref" in prop:
        target = defs[prop.pop("$ref").rsplit("/", 1)[-1]]
        prop = {**_object(target, defs), **{k: v for k, v in prop.items() if k != "$ref"}}
    if prop.get("type") == "array" and isinstance(prop.get("items"), dict):
        prop["items"] = _simplify(prop["items"], defs)
    # Keep ID patterns (PRD-…); drop pydantic's Decimal-as-string pattern.
    pattern = prop.get("pattern", "")
    if prop.get("type") == "string" and pattern and not pattern.startswith("^PRD-"):
        prop.pop("pattern")
    return prop
