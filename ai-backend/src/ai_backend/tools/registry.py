"""Tool registry: name → spec, and the JSON schemas the model is given (SPEC §6).

Schemas are strict (`additionalProperties: false`) and simplified for OpenAI-compatible
providers: optional fields are plain types (not `anyOf` with null), and money is a number.
"""

from __future__ import annotations

from typing import Any

from ai_backend.tools.definitions import P0_READ_TOOLS, ToolSpec

REGISTRY: dict[str, ToolSpec] = {t.name: t for t in P0_READ_TOOLS}


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
    properties = {name: _simplify(prop) for name, prop in schema.get("properties", {}).items()}
    return {
        "type": "object",
        "properties": properties,
        "required": schema.get("required", []),
        "additionalProperties": False,
    }


def _simplify(prop: dict[str, Any]) -> dict[str, Any]:
    prop = {k: v for k, v in prop.items() if k not in ("title", "default")}
    variants = prop.pop("anyOf", None)
    if variants:
        non_null = [v for v in variants if v.get("type") != "null"]
        types = {v.get("type") for v in non_null}
        if types == {"number", "string"}:  # pydantic's Decimal: send it as a number
            prop.update(type="number")
        elif len(non_null) == 1:
            prop.update({k: v for k, v in non_null[0].items() if k != "title"})
    if prop.get("type") == "string" and "pattern" in prop and "format" not in prop:
        prop.pop("pattern")  # Decimal's string pattern; not useful to the model
    return prop
