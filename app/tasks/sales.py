"""Negociación comercial (venta de equipos) y selección de oferta/producto."""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.kb import KbMixin
from app.tasks.registry import register_task
from app.utils.dates import resolve_relative_fecha, spoken_date, validate_commitment_date
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)


class _SalesCloseMixin(KbMixin):
    """Tools compartidas de cierre comercial."""

    def _sales_prompt(self, extra: str = "") -> str:
        custom = self.node_params().get("custom_instructions") or ""
        producto = self.session.variables.get("producto") or self.session.especialidad
        return (
            f"Sos {self.session.nombre_agente}, asesor de {self.session.nombre_empresa}. "
            "FASE: CIERRE COMERCIAL. Identidad ya confirmada.\n"
            f"Contacto: {self.session.nombre_deudor}. Línea/equipo: {producto}.\n"
            "No inventes precios fuera de la KB. No prometas stock que no consta.\n"
            "- confirmar_pedido(fecha_iso) si acepta comprar/reservar (fecha de entrega o cierre).\n"
            "- registrar_intencion_compra si quiere pero no cierra ahora.\n"
            "- cerrar_sin_pedido si rechaza.\n"
            "- ya_compro si dice que ya compró.\n"
            "- responder_kb para FAQ (garantía, plazos, financiamiento).\n"
            f"{extra}\n{custom}"
        )

    async def _date_ok(self, fecha_iso: str) -> tuple[bool, Optional[str], Optional[str]]:
        resolved = resolve_relative_fecha(fecha_iso, timezone=self.session.timezone)
        return validate_commitment_date(
            resolved, timezone=self.session.timezone, max_dias=self.session.max_dias
        )

    @register_tool(type="normal")
    async def confirmar_pedido(self, params, fecha_iso: str) -> None:
        """Cierra el pedido. fecha_iso = entrega o fecha de cierre (AAAA-MM-DD o mañana)."""
        ok, normalized, human = await self._date_ok(fecha_iso)
        if not ok or not normalized:
            await params.result_callback(
                {"ok": False, "invalid_date": human}, properties=_CONTINUE
            )
            return
        self.session.commitment_date = normalized
        self.session.commitment_date_spoken = spoken_date(normalized)
        self.session.final_status = "Pedido confirmado"
        landed = await self.advance("Pedido confirmado")
        if not landed:
            await self.advance("Cita agendada")
        await params.result_callback(
            {"ok": True, "outcome": "Pedido confirmado", "date": normalized},
            properties=_WAIT,
        )

    @register_tool(type="normal")
    async def registrar_intencion_compra(self, params, fecha_iso: Optional[str] = None) -> None:
        """Intención de compra sin cierre."""
        if fecha_iso:
            ok, normalized, _ = await self._date_ok(fecha_iso)
            if ok and normalized:
                self.session.commitment_date = normalized
                self.session.commitment_date_spoken = spoken_date(normalized)
        self.session.final_status = "Intención de compra"
        landed = await self.advance("Intención de compra")
        if not landed:
            await self.advance("Intención de agendar")
        await params.result_callback(
            {"ok": True, "outcome": "Intención de compra"}, properties=_WAIT
        )

    @register_tool(type="normal")
    async def cerrar_sin_pedido(self, params, razon: Optional[str] = None) -> None:
        """No hay pedido."""
        self.session.final_status = "Sin pedido"
        landed = await self.advance("Sin pedido")
        if not landed:
            await self.advance("Sin cita")
        await params.result_callback(
            {"ok": True, "outcome": "Sin pedido", "reason": razon}, properties=_WAIT
        )

    @register_tool(type="normal")
    async def ya_compro(self, params, evidencia: Optional[str] = None) -> None:
        """El comprador declara que ya compró."""
        self.session.final_status = "Ya compró"
        landed = await self.advance("Ya compró")
        if not landed:
            await self.advance("Ya atendido")
        await params.result_callback(
            {"ok": True, "outcome": "Ya compró", "evidence": evidencia}, properties=_WAIT
        )


@register_task
class NegotiationTaskV2(_SalesCloseMixin, BaseTask):
    task_type = "NegotiationTaskV2"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.negotiation") -> None:
        super().__init__(ctx, node_id=node_id)

    def system_prompt(self) -> str:
        return self._sales_prompt()

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [
            self.confirmar_pedido,
            self.registrar_intencion_compra,
            self.cerrar_sin_pedido,
            self.ya_compro,
            self.responder_kb,
        ]


@register_task
class MultiProductNegotiationTask(_SalesCloseMixin, BaseTask):
    task_type = "MultiProductNegotiationTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.negotiation_multi") -> None:
        super().__init__(ctx, node_id=node_id)

    def system_prompt(self) -> str:
        return self._sales_prompt(
            extra="- seleccionar_producto(nombre) si hay más de un equipo en la cotización, ANTES de confirmar_pedido."
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [
            self.seleccionar_producto,
            self.confirmar_pedido,
            self.registrar_intencion_compra,
            self.cerrar_sin_pedido,
            self.ya_compro,
            self.responder_kb,
        ]

    @register_tool(type="normal")
    async def seleccionar_producto(self, params, nombre: str) -> None:
        """Elige el equipo de la cotización multiproducto."""
        self.session.variables["producto"] = (nombre or "").strip()
        await params.result_callback(
            {"ok": True, "producto": self.session.variables["producto"]},
            properties=_CONTINUE,
        )


@register_task
class OfferSelectionTask(BaseTask):
    task_type = "OfferSelectionTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.offer_selection") -> None:
        super().__init__(ctx, node_id=node_id)

    def system_prompt(self) -> str:
        custom = self.node_params().get("custom_instructions") or ""
        return (
            f"Sos {self.session.nombre_agente} de {self.session.nombre_empresa}. "
            "FASE: SELECCIÓN DE OFERTA/PLAN.\n"
            "Presentá las alternativas del nodo y esperá que elija UNA.\n"
            "- seleccionar_oferta(opcion) con la etiqueta que eligió.\n"
            "- rechazar_ofertas si no quiere ninguna.\n"
            f"{custom}"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [self.seleccionar_oferta, self.rechazar_ofertas]

    @register_tool(type="normal")
    async def seleccionar_oferta(self, params, opcion: str) -> None:
        """Registra la oferta o plan elegido."""
        self.session.variables["oferta"] = (opcion or "").strip()
        self.session.final_status = "Seleccion"
        await self.advance("Seleccion")
        await params.result_callback(
            {"ok": True, "outcome": "Seleccion", "oferta": self.session.variables["oferta"]},
            properties=_WAIT,
        )

    @register_tool(type="normal")
    async def rechazar_ofertas(self, params, razon: Optional[str] = None) -> None:
        """No acepta ninguna oferta."""
        await self.advance("Rechaza")
        await params.result_callback(
            {"ok": True, "outcome": "Rechaza", "reason": razon}, properties=_WAIT
        )
