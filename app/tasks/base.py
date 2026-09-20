"""Protocolo de tasks independientes compatibles con Pipecat."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence

from app.session.call_session import CallSession

SpeakFn = Callable[[str], Awaitable[None]]
PhaseFn = Callable[[str], Awaitable[None]]


@dataclass
class TaskContext:
    """Contexto compartido entre tasks de un mismo flujo."""

    session: CallSession
    flow: dict[str, Any]
    speak: SpeakFn
    set_phase: PhaseFn
    say_node: Callable[[str], Awaitable[None]]


class BaseTask(ABC):
    """Una task = un script independiente (tools + prompt de fase)."""

    task_type: str = "BaseTask"
    phase: str = "identity"
    tool_choice: str = "required"

    def __init__(self, ctx: TaskContext) -> None:
        self.ctx = ctx

    @property
    def session(self) -> CallSession:
        return self.ctx.session

    @property
    def flow(self) -> dict[str, Any]:
        return self.ctx.flow

    async def speak(self, text: str) -> None:
        await self.ctx.speak(text)

    async def say_node(self, node_id: str) -> None:
        await self.ctx.say_node(node_id)

    async def set_phase(self, phase: str) -> None:
        await self.ctx.set_phase(phase)

    def node_params(self, node_id: str) -> dict[str, Any]:
        return dict(self.flow["flow_graph"]["nodes"][node_id].get("params") or {})

    @abstractmethod
    def system_prompt(self) -> str:
        ...

    @abstractmethod
    def tools(self) -> Sequence[Callable[..., Any]]:
        """Métodos async listos para LLMContext(tools=...)."""
        ...
