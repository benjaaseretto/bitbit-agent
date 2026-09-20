"""FieldVerificationTask y KBATask: autenticación extra post-identidad."""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.registry import register_task, TASK_REGISTRY
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)


@register_task
class FieldVerificationTask(BaseTask):
    task_type = "FieldVerificationTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.primera_validacion") -> None:
        super().__init__(ctx, node_id=node_id)

    def system_prompt(self) -> str:
        custom = self.node_params().get("custom_instructions") or ""
        return (
            f"Sos {self.session.nombre_agente} de {self.session.nombre_empresa}. "
            "FASE: VERIFICACIÓN DE CAMPO (documento, fecha, código).\n"
            "Pedí el dato y validá con verificar_campo. No reveles el valor esperado.\n"
            f"{custom}"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [self.verificar_campo, self.fallo_verificacion]

    @register_tool(type="normal")
    async def verificar_campo(self, params, campo: str, valor: str) -> None:
        """Registra el dato de verificación. En demo se acepta si no está vacío."""
        value = (valor or "").strip()
        if len(value) < 2:
            await params.result_callback(
                {"ok": False, "error": "Dato incompleto. Volvé a pedirlo."},
                properties=_CONTINUE,
            )
            return
        self.session.variables[campo or "verificacion"] = value
        await self.advance("Completado")
        await params.result_callback({"ok": True, "field": campo, "value": value}, properties=_WAIT)

    @register_tool(type="normal")
    async def fallo_verificacion(self, params, razon: Optional[str] = None) -> None:
        """Agota intentos o el usuario no puede verificar."""
        await self.advance("MaxTriesExceeded")
        await params.result_callback(
            {"ok": True, "outcome": "MaxTriesExceeded", "reason": razon}, properties=_WAIT
        )


@register_task
class KBATask(BaseTask):
    task_type = "KBATask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.kba") -> None:
        super().__init__(ctx, node_id=node_id)

    def system_prompt(self) -> str:
        custom = self.node_params().get("custom_instructions") or ""
        return (
            f"Sos {self.session.nombre_agente} de {self.session.nombre_empresa}. "
            "FASE: PREGUNTA DE CONOCIMIENTO (KBA).\n"
            "Hacé la pregunta del nodo. No des pistas del valor correcto.\n"
            "- registrar_kba(respuesta) con la respuesta literal.\n"
            "- fallo_kba si no sabe o no coincide tras reintentos.\n"
            f"{custom}"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [self.registrar_kba, self.fallo_kba]

    @register_tool(type="normal")
    async def registrar_kba(self, params, respuesta: str) -> None:
        """Guarda la respuesta KBA."""
        value = (respuesta or "").strip()
        if len(value) < 1:
            await params.result_callback(
                {"ok": False, "error": "Respuesta vacía."}, properties=_CONTINUE
            )
            return
        self.session.variables["kba"] = value
        await self.advance("Completado")
        await params.result_callback({"ok": True, "kba": value}, properties=_WAIT)

    @register_tool(type="normal")
    async def fallo_kba(self, params, razon: Optional[str] = None) -> None:
        """No superó el KBA."""
        await self.advance("MaxTriesExceeded")
        await params.result_callback(
            {"ok": True, "outcome": "MaxTriesExceeded", "reason": razon}, properties=_WAIT
        )


# Alias de specs colly
TASK_REGISTRY.setdefault("KbaTask", KBATask)
