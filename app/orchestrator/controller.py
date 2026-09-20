"""Orquestador Pipecat: swap de fase + tools desde tasks independientes."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from app.orchestrator.loader import say_text
from app.session.call_session import CallSession
from app.tasks.appointment import AppointmentSchedulingTask
from app.tasks.base import BaseTask, TaskContext
from app.tasks.identity import IdentityVerificationTask
from app.tasks.registry import ensure_builtin_tasks_loaded, get_task_class

SpeakFn = Callable[[str], Awaitable[None]]
PhaseFn = Callable[[str], Awaitable[None]]

ensure_builtin_tasks_loaded()

# phase → task_type preferido (override por nodo del spec si existe)
_PHASE_TASK_TYPES = {
    "identity": "IdentityVerificationTask",
    "negotiation": "AppointmentSchedulingTask",
}


class FlowController:
    """Expone prompts/tools de la task activa; compatible con bot Pipecat."""

    def __init__(
        self,
        session: CallSession,
        flow: dict[str, Any],
        *,
        speak: SpeakFn,
        on_phase: Optional[PhaseFn] = None,
    ) -> None:
        self.session = session
        self.flow = flow
        self._speak = speak
        self._on_phase = on_phase
        self._tasks: dict[str, BaseTask] = {}
        self._active: BaseTask = self._build_task_for_phase(session.phase)

    def _make_ctx(self) -> TaskContext:
        return TaskContext(
            session=self.session,
            flow=self.flow,
            speak=self._speak,
            set_phase=self._set_phase,
            say_node=self._say_node,
        )

    async def _say_node(self, node_id: str) -> None:
        await self._speak(say_text(self.flow, node_id, self.session))

    def _task_type_for_phase(self, phase: str) -> str:
        nodes = self.flow.get("flow_graph", {}).get("nodes") or {}
        if phase == "identity":
            start = self.flow.get("flow_graph", {}).get("start")
            node = nodes.get(start) or nodes.get("task.identity_verification") or {}
            return str(node.get("task_type") or _PHASE_TASK_TYPES["identity"])
        if phase == "negotiation":
            node = nodes.get("task.negotiation") or {}
            return str(node.get("task_type") or _PHASE_TASK_TYPES["negotiation"])
        return _PHASE_TASK_TYPES.get(phase, "IdentityVerificationTask")

    def _build_task_for_phase(self, phase: str) -> BaseTask:
        if phase in self._tasks:
            return self._tasks[phase]
        if phase == "done":
            # Reutiliza la última task de negocio sin tools
            task = self._tasks.get("negotiation") or self._tasks.get("identity")
            if task:
                return task
        task_type = self._task_type_for_phase(phase if phase != "done" else "identity")
        try:
            cls = get_task_class(task_type)
        except (KeyError, NotImplementedError):
            # Fallback médico built-in
            cls = (
                IdentityVerificationTask
                if phase == "identity"
                else AppointmentSchedulingTask
            )
        node_id = (
            "task.identity_verification"
            if phase == "identity"
            else "task.negotiation"
        )
        task = cls(self._make_ctx(), node_id=node_id)
        self._tasks[phase if phase != "done" else "negotiation"] = task
        return task

    async def _set_phase(self, phase: str) -> None:
        self.session.phase = phase
        if phase != "done":
            self._active = self._build_task_for_phase(phase)
        if not self._on_phase:
            return
        try:
            await self._on_phase(phase)
        except Exception:
            logger.exception("on_phase failed phase={}", phase)

    def identity_system_prompt(self) -> str:
        task = self._tasks.get("identity") or self._build_task_for_phase("identity")
        return task.system_prompt()

    def negotiation_system_prompt(self) -> str:
        task = self._tasks.get("negotiation") or self._build_task_for_phase(
            "negotiation"
        )
        return task.system_prompt()

    def tools_for_phase(self, phase: Optional[str] = None) -> list:
        p = phase or self.session.phase
        if p == "done":
            return []
        task = self._build_task_for_phase(p)
        return list(task.tools())

    def tool_choice_for_phase(self, phase: Optional[str] = None) -> str:
        p = phase or self.session.phase
        if p == "done":
            return "none"
        task = self._build_task_for_phase(p)
        return getattr(task, "tool_choice", "auto")

    # --- Delegación de tools (API estable para tests / LLMContext) ---

    @property
    def esperar_titular(self):
        return self._identity().esperar_titular

    @property
    def registrar_resultado_identidad(self):
        return self._identity().registrar_resultado_identidad

    @property
    def agendar_cita(self):
        return self._appointment().agendar_cita

    @property
    def cliente_dispuesto(self):
        return self._appointment().cliente_dispuesto

    @property
    def finalizar(self):
        return self._appointment().finalizar

    @property
    def responder_kb(self):
        return self._appointment().responder_kb

    def _identity(self) -> IdentityVerificationTask:
        task = self._tasks.get("identity") or self._build_task_for_phase("identity")
        assert isinstance(task, IdentityVerificationTask)
        return task

    def _appointment(self) -> AppointmentSchedulingTask:
        task = self._tasks.get("negotiation") or self._build_task_for_phase(
            "negotiation"
        )
        assert isinstance(task, AppointmentSchedulingTask)
        return task
