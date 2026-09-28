"""A chat model that plays back a script, for testing the graph without a real LLM."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

Step = AIMessage | Callable[[list[BaseMessage]], AIMessage]
USAGE = {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}


def tool_call(name: str, args: dict[str, Any] | None = None, call_id: str = "call_1") -> AIMessage:
    return AIMessage(
        "",
        tool_calls=[{"name": name, "args": args or {}, "id": call_id, "type": "tool_call"}],
        usage_metadata=USAGE,
    )


def answer(text: str) -> AIMessage:
    return AIMessage(text, usage_metadata=USAGE)


class ScriptedChatModel(BaseChatModel):
    # Any, not Step: pydantic would try to coerce the callables into AIMessages.
    script: list[Any] = Field(default_factory=list)
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[Any] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        self.bound_tools = list(tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Any = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        if not self.script:
            raise AssertionError("the model was called more times than scripted")
        step = self.script.pop(0)
        message = step(messages) if callable(step) else step
        return ChatResult(generations=[ChatGeneration(message=message)])
