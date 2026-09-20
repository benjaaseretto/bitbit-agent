"""Orquestador Pipecat: swap de fase + tools desde tasks independientes."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from loguru import logger

from app.orchestrator.loader import say_text
from app.session.call_session import CallSession
from app.tasks.appointment import AppointmentSchedulingTask
from app.tasks.base import BaseTask, TaskContext
from app.tasks.graph import advance_graph, negotiation_task_node
from app.tasks.identity import IdentityVerificationTask
from app.tasks.registry import ensure_builtin_tasks_loaded, get_task_class

SpeakFn = Callable[[str], Awaitable[None]]
PhaseFn = Callable[[str], Awaitable[None]]

ensure_builtin_tasks_loaded()

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
            advance=self._advance,
        )

    async def _say_node(self, node_id: str) -> None:
        text = say_text(self.flow, node_id, self.session)
        if text:
            await self._speak(text)

    async def _advance(self, from_node: str, label: str) -> Optional[str]:
        return await advance_graph(
            flow=self.flow,
            session=self.session,
            from_node=from_node,
            label=label,
            say_node=self._say_node,
            set_phase=self._set_phase,
        )

    def _identity_node_id(self) -> str:
        start = self.flow.get("flow_graph", {}).get("start")
        if start:
            return str(start)
        return "task.identity_verification"

    def _node_id_for_phase(self, phase: str) -> str:
        if phase == "identity":
            return self._identity_node_id()
        current = self.session.current_node_id
        return negotiation_task_node(self.flow, current, self.session)

    def _task_type_for_node(self, node_id: str, phase: str) -> str:
        nodes = self.flow.get("flow_graph", {}).get("nodes") or {}
        node = nodes.get(node_id) or {}
        return str(node.get("task_type") or _PHASE_TASK_TYPES.get(phase) or "IdentityVerificationTask")

    def _build_task_for_phase(self, phase: str) -> BaseTask:
        if phase == "done":
            task = self._tasks.get("negotiation") or self._tasks.get("identity")
            if task:
                return task
            phase = "identity"
        node_id = self._node_id_for_phase(phase)
        cache_key = f"{phase}:{node_id}"
        if cache_key in self._tasks:
            self._active = self._tasks[cache_key]
            return self._tasks[cache_key]
        task_type = self._task_type_for_node(node_id, phase)
        try:
            cls = get_task_class(task_type)
        except (KeyError, NotImplementedError):
            logger.warning("task_type={} missing; fallback phase={}", task_type, phase)
            cls = (
                IdentityVerificationTask
                if phase == "identity"
                else AppointmentSchedulingTask
            )
        task = cls(self._make_ctx(), node_id=node_id)
        self._tasks[cache_key] = task
        if phase != "identity":
            self._tasks["negotiation"] = task
        else:
            self._tasks["identity"] = task
        self._active = task
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
        task = self._build_task_for_phase("identity")
        return task.system_prompt()

    def negotiation_system_prompt(self) -> str:
        task = self._build_task_for_phase("negotiation")
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

    @property
    def esperar_titular(self):
        return self._identity().esperar_titular

    @property
    def repregunta_identidad(self):
        return self._identity().repregunta_identidad

    @property
    def aclarar_quien_habla(self):
        return self._identity().aclarar_quien_habla

    @property
    def registrar_resultado_identidad(self):
        return self._identity().registrar_resultado_identidad

    @property
    def agendar_cita(self):
        return self._appointment().agendar_cita

    @property
    def confirmar_asistencia(self):
        return self._appointment().confirmar_asistencia

    @property
    def cancelar_cita(self):
        return self._appointment().cancelar_cita

    @property
    def reagendar_cita(self):
        return self._appointment().reagendar_cita

    @property
    def cliente_dispuesto(self):
        return self._appointment().cliente_dispuesto

    @property
    def finalizar(self):
        return self._appointment().finalizar

    @property
    def responder_kb(self):
        task = self._build_task_for_phase(
            "negotiation" if self.session.phase != "identity" else "negotiation"
        )
        fn = getattr(task, "responder_kb", None)
        if fn:
            return fn
        return self._appointment().responder_kb

    def _identity(self) -> IdentityVerificationTask:
        task = self._build_task_for_phase("identity")
        assert isinstance(task, IdentityVerificationTask)
        return task

    def _appointment(self) -> AppointmentSchedulingTask:
        task = self._tasks.get("negotiation")
        if isinstance(task, AppointmentSchedulingTask):
            return task
        built = self._build_task_for_phase("negotiation")
        if isinstance(built, AppointmentSchedulingTask):
            return built
        # Specs de venta no tienen AppointmentSchedulingTask; construí una para tests.
        appt = AppointmentSchedulingTask(self._make_ctx(), node_id=self._node_id_for_phase("negotiation"))
        return appt
