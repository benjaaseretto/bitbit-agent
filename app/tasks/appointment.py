"""Script independiente: agenda de consultas médicas (+ KB FAQ)."""
from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Sequence

from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.graph import has_node
from app.tasks.kb import KbMixin
from app.tasks.registry import register_task
from app.utils.dates import (
    resolve_relative_fecha,
    spoken_date,
    today_in_tz,
    validate_commitment_date,
)
from app.utils.templates import render_template
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)


@register_task
class AppointmentSchedulingTask(KbMixin, BaseTask):
    task_type = "AppointmentSchedulingTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.negotiation") -> None:
        super().__init__(ctx)
        self.node_id = node_id

    def system_prompt(self) -> str:
        params = self.node_params(self.node_id)
        custom = params.get("custom_instructions") or ""
        kb_lines = [
            f"- Q: {item.get('question')}\n  A: {item.get('answer')}"
            for item in self.session.knowledge_base[:15]
        ]
        hoy = today_in_tz(self.session.timezone).isoformat()
        manana = resolve_relative_fecha("mañana", timezone=self.session.timezone)
        return (
            f"Sos {self.session.nombre_agente}, asistente de agenda de {self.session.nombre_empresa}.\n"
            "FASE: AGENDAR CONSULTA. Identidad YA confirmada.\n"
            "PROHIBIDO llamar registrar_resultado_identidad o esperar_titular.\n"
            "NO das diagnósticos, tratamientos ni recetas por teléfono.\n"
            f"Paciente: {self.session.nombre_deudor}. "
            f"Especialidad: {self.session.especialidad}. "
            f"Médico: {self.session.nombre_medico}. "
            f"Sucursal: {self.session.sucursal}.\n"
            f"Hoy={hoy}. 'mañana'={manana}. Agenda hasta={self.session.fecha_limite} "
            f"(máx {self.session.max_dias} días).\n"
            "\n"
            "CÓMO RESPONDER:\n"
            "- Podés HABLAR en texto libre (empatía, proponer día, repreguntar). "
            "NO hace falta tool en cada turno.\n"
            "- Si el paciente cuenta síntomas o dudas clínicas: empatizá y ofrecé "
            "agendar cuanto antes. NO inventes consejo médico.\n"
            "- Si dice una fecha (hoy/mañana/día concreto): "
            "agendar_cita(fecha_iso AAAA-MM-DD).\n"
            "- responder_kb SOLO ante FAQ clara (precio, dirección, documentos, horarios). "
            "Pasá la pregunta del usuario, NO copies títulos de la KB.\n"
            "- Nunca repitas la misma respuesta KB. Tras responder, pedí una fecha.\n"
            "- finalizar(sin_cita) si no quiere turnos; "
            "finalizar(ya_agendada) si ya tenía cita; "
            "finalizar(reagendar_despues) si pide que lo llamen otro día.\n"
            "No verbalices nombres de tools.\n"
            f"{custom}\n"
            f"KB (referencia):\n" + "\n".join(kb_lines)
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [self.agendar_cita, self.finalizar, self.responder_kb]

    @register_tool(type="normal")
    async def agendar_cita(self, params, fecha_iso: str) -> None:
        """Agenda la consulta. fecha_iso: AAAA-MM-DD o relativa (hoy/mañana)."""
        if self.session.phase == "identity":
            await params.result_callback(
                {
                    "ok": False,
                    "error": "Todavía en identidad. Primero registrar_resultado_identidad.",
                },
                properties=_CONTINUE,
            )
            return
        if self.session.phase == "done":
            await params.result_callback(
                {"ok": False, "error": "Llamada ya cerrada.", "status": self.session.final_status},
                properties=_WAIT,
            )
            return

        resolved = resolve_relative_fecha(fecha_iso, timezone=self.session.timezone)
        ok, normalized, human = validate_commitment_date(
            resolved,
            timezone=self.session.timezone,
            max_dias=self.session.max_dias,
        )
        node_params = self.node_params(self.node_id)
        if ok and normalized:
            self.session.commitment_date = normalized
            self.session.commitment_date_spoken = spoken_date(normalized)
            self.session.final_status = "Cita agendada"
            landed = await self.advance("Cita agendada")
            if not landed:
                if has_node(self.flow, "intent.confirm_commitment"):
                    await self.say_node("intent.confirm_commitment")
                if has_node(self.flow, "final.end_commitment"):
                    await self.say_node("final.end_commitment")
                await self.set_phase("done")
            await params.result_callback(
                {
                    "ok": True,
                    "outcome": "Cita agendada",
                    "appointment_date": normalized,
                    "resolved_from": fecha_iso,
                },
                properties=_WAIT,
            )
            return

        self.session.dates_intentions.append(fecha_iso)
        self.session.negotiation_attempts += 1
        max_attempts = int(node_params.get("max_attempts") or 3)
        if self.session.negotiation_attempts >= max_attempts:
            self.session.final_status = "Reagendar después"
            await self.say_node("final.end_intencion_de_pago")
            await self.set_phase("done")
            await params.result_callback(
                {"ok": True, "outcome": "Reagendar después"}, properties=_WAIT
            )
            return

        template = (
            node_params["invalid_date_message"]
            if self.session.negotiation_attempts == 1
            else node_params["invalid_date_retry_message"]
        )
        msg = render_template(
            template,
            {
                **self.session.as_template_vars(),
                "fecha_limite": spoken_date(self.session.fecha_limite),
            },
        )
        await self.speak(msg)
        await params.result_callback(
            {
                "ok": False,
                "invalid_date": human,
                "input": fecha_iso,
                "resolved": resolved,
                "hint": f"Pedí una fecha entre hoy y {self.session.fecha_limite} (AAAA-MM-DD).",
            },
            properties=_WAIT,
        )

    async def cliente_dispuesto(self, params, fecha_iso: str) -> None:
        """Alias histórico."""
        await self.agendar_cita(params, fecha_iso=fecha_iso)

    @register_tool(type="normal")
    async def finalizar(
        self,
        params,
        resultado: Literal["sin_cita", "ya_agendada", "reagendar_despues"],
        razon: Optional[str] = None,
    ) -> None:
        """Cierra agenda: sin_cita | ya_agendada | reagendar_despues."""
        if self.session.phase == "identity":
            await params.result_callback(
                {"ok": False, "error": "Todavía en identidad; no cierres aún."},
                properties=_CONTINUE,
            )
            return
        if self.session.phase == "done":
            await params.result_callback(
                {
                    "ok": True,
                    "already": True,
                    "status": self.session.final_status,
                    "appointment_date": self.session.commitment_date,
                    "note": "Llamada ya cerrada. No cambies el resultado.",
                },
                properties=_WAIT,
            )
            return
        mapping = {
            "sin_cita": ("Sin cita", "Sin cita"),
            "ya_agendada": ("Ya tenía cita", "Ya atendido"),
            "reagendar_despues": ("Reagendar después", "Intención de agendar"),
        }
        status, label = mapping[resultado]
        self.session.final_status = status
        landed = await self.advance(label)
        if not landed:
            fallbacks = {
                "sin_cita": ("intent.soft_close_no_commitment", "final.end_no_commitment"),
                "ya_agendada": (None, "final.end_paid"),
                "reagendar_despues": (None, "final.end_intencion_de_pago"),
            }
            soft, final_id = fallbacks[resultado]
            if soft and has_node(self.flow, soft):
                await self.say_node(soft)
            if final_id and has_node(self.flow, final_id):
                await self.say_node(final_id)
            await self.set_phase("done")
        await params.result_callback(
            {"ok": True, "outcome": status, "reason": razon}, properties=_WAIT
        )
