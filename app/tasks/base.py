"""Protocolo de tasks independientes compatibles con Pipecat."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence

from loguru import logger

from app.session.call_session import CallSession
from app.utils.templates import render_value

SpeakFn = Callable[[str], Awaitable[None]]
PhaseFn = Callable[[str], Awaitable[None]]
EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


AdvanceFn = Callable[[str, str], Awaitable[Optional[str]]]


@dataclass
class TaskContext:
    """Contexto compartido entre tasks de un mismo flujo."""

    session: CallSession
    flow: dict[str, Any]
    speak: SpeakFn
    set_phase: PhaseFn
    say_node: Callable[[str], Awaitable[None]]
    advance: Optional[AdvanceFn] = None
    # Canal opcional hacia el frontend (data channel de Studio). Lo usan las
    # tools que producen visualizaciones; si no está cableado, es None.
    emit: Optional[EmitFn] = None


class BaseTask(ABC):
    """Una task = un script independiente (tools + prompt de fase)."""

    task_type: str = "BaseTask"
    phase: str = "identity"
    tool_choice: str = "required"

    def __init__(self, ctx: TaskContext, *, node_id: Optional[str] = None) -> None:
        self.ctx = ctx
        self.node_id = node_id or ""

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

    async def advance(self, label: str) -> Optional[str]:
        if not self.ctx.advance:
            return None
        return await self.ctx.advance(self.node_id or "", label)

    async def emit_visual(self, payload: dict[str, Any]) -> bool:
        """Envía un mensaje tipado al frontend. False si no hay canal o falla.

        Una falla de visualización NO rompe la conversación: el texto hablado
        sigue su curso igual.
        """
        emit = self.ctx.emit
        if emit is None:
            return False
        try:
            await emit(payload)
            return True
        except Exception:
            logger.warning("emit_visual falló para {}", self.task_type)
            return False

    def node_params(self, node_id: Optional[str] = None) -> dict[str, Any]:
        nid = node_id or self.node_id
        nodes = self.flow.get("flow_graph", {}).get("nodes") or {}
        raw = dict((nodes.get(nid) or {}).get("params") or {})
        return render_value(raw, self.session.as_template_vars())

    @abstractmethod
    def system_prompt(self) -> str:
        ...

    @abstractmethod
    def tools(self) -> Sequence[Callable[..., Any]]:
        """Métodos async listos para LLMContext(tools=...)."""
        ...
