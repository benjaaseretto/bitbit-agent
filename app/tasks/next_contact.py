"""NextContactTask y captura de fecha de intención."""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.registry import register_task
from app.utils.dates import resolve_relative_fecha, spoken_date, validate_commitment_date
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)


@register_task
class NextContactTask(BaseTask):
    task_type = "NextContactTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.next_contact") -> None:
        super().__init__(ctx, node_id=node_id)

    def system_prompt(self) -> str:
        custom = self.node_params().get("custom_instructions") or ""
        return (
            f"Sos {self.session.nombre_agente} de {self.session.nombre_empresa}. "
            "FASE: PRÓXIMO CONTACTO. El usuario no puede ahora.\n"
            "Pedí un día concreto para volver a llamar.\n"
            "- agendar_proximo_contacto(fecha_iso) si da fecha (hoy/mañana/AAAA-MM-DD).\n"
            "- cancelar_proximo_contacto si no quiere que lo llamen.\n"
            f"Hoy ventana hasta {self.session.fecha_limite}.\n{custom}"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [self.agendar_proximo_contacto, self.cancelar_proximo_contacto]

    @register_tool(type="normal")
    async def agendar_proximo_contacto(self, params, fecha_iso: str) -> None:
        """Registra cuándo volver a contactar. fecha_iso AAAA-MM-DD o relativa."""
        resolved = resolve_relative_fecha(fecha_iso, timezone=self.session.timezone)
        ok, normalized, human = validate_commitment_date(
            resolved, timezone=self.session.timezone, max_dias=self.session.max_dias
        )
        if not ok or not normalized:
            await params.result_callback(
                {
                    "ok": False,
                    "invalid_date": human,
                    "hint": f"Pedí una fecha entre hoy y {self.session.fecha_limite}.",
                },
                properties=_CONTINUE,
            )
            return
        self.session.variables["next_contact_date"] = normalized
        self.session.commitment_date = normalized
        self.session.commitment_date_spoken = spoken_date(normalized)
        self.session.final_status = "Próximo contacto"
        await self.advance("Próximo contacto")
        await params.result_callback(
            {"ok": True, "outcome": "Próximo contacto", "date": normalized},
            properties=_WAIT,
        )

    @register_tool(type="normal")
    async def cancelar_proximo_contacto(self, params, razon: Optional[str] = None) -> None:
        """No se agenda recontacto."""
        self.session.final_status = "Cancelado"
        await self.advance("Cancelado")
        await params.result_callback(
            {"ok": True, "outcome": "Cancelado", "reason": razon}, properties=_WAIT
        )


@register_task
class PaymentIntentionDateTask(BaseTask):
    task_type = "PaymentIntentionDateTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(
        self, ctx: TaskContext, *, node_id: str = "task.payment_intention_date"
    ) -> None:
        super().__init__(ctx, node_id=node_id)

    def system_prompt(self) -> str:
        custom = self.node_params().get("custom_instructions") or ""
        return (
            f"Sos {self.session.nombre_agente} de {self.session.nombre_empresa}. "
            "FASE: CAPTURAR FECHA DE INTENCIÓN (agenda o compra).\n"
            "No cierres aún un pedido/cita definitivo: solo la fecha tentativa.\n"
            "- capturar_fecha_intencion(fecha_iso) si da un día.\n"
            "- sin_fecha_intencion si no puede dar ninguna.\n"
            f"{custom}"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [self.capturar_fecha_intencion, self.sin_fecha_intencion]

    @register_tool(type="normal")
    async def capturar_fecha_intencion(self, params, fecha_iso: str) -> None:
        """Guarda fecha tentativa de cita o compra."""
        resolved = resolve_relative_fecha(fecha_iso, timezone=self.session.timezone)
        ok, normalized, human = validate_commitment_date(
            resolved, timezone=self.session.timezone, max_dias=self.session.max_dias
        )
        if not ok or not normalized:
            await params.result_callback(
                {"ok": False, "invalid_date": human}, properties=_CONTINUE
            )
            return
        self.session.variables["fecha_intencion"] = normalized
        self.session.commitment_date = normalized
        self.session.commitment_date_spoken = spoken_date(normalized)
        for label in (
            "Fecha tentativa capturada",
            "Intención de agendar",
            "Intención de compra",
        ):
            landed = await self.advance(label)
            if landed:
                break
        await params.result_callback(
            {"ok": True, "date": normalized}, properties=_WAIT
        )

    @register_tool(type="normal")
    async def sin_fecha_intencion(self, params, razon: Optional[str] = None) -> None:
        """No hay fecha tentativa."""
        await self.advance("Sin fecha")
        await params.result_callback(
            {"ok": True, "outcome": "Sin fecha", "reason": razon}, properties=_WAIT
        )
