"""Script independiente: agenda de consultas médicas o confirmación de turno (+ KB)."""
from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Sequence

from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.graph import edge_for, has_node
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

    def _confirm_mode(self) -> bool:
        mode = str(self.node_params(self.node_id).get("mode") or "").strip()
        return mode == "confirm_attendance"

    def system_prompt(self) -> str:
        params = self.node_params(self.node_id)
        custom = params.get("custom_instructions") or ""
        # Índice compacto de temas: la respuesta determinista sale de
        # responder_kb (matcheo en código, run_llm=False). Incrustar las
        # respuestas completas costaba ~400-600 tokens en CADA request.
        kb_topics = "; ".join(
            topic.strip()
            for item in self.session.knowledge_base[:15]
            for topic in str(item.get("question", "")).split("|")[:1]
        )
        hoy = today_in_tz(self.session.timezone).isoformat()
        manana = resolve_relative_fecha("mañana", timezone=self.session.timezone)
        if self._confirm_mode():
            return (
                f"Sos {self.session.nombre_agente}, asistente de {self.session.nombre_empresa}.\n"
                "FASE: CONFIRMAR ASISTENCIA. Identidad YA confirmada.\n"
                "PROHIBIDO llamar registrar_resultado_identidad o esperar_titular.\n"
                "NO das diagnósticos, tratamientos ni recetas por teléfono.\n"
                f"Paciente: {self.session.nombre_deudor}. "
                f"Especialidad: {self.session.especialidad}. "
                f"Médico: {self.session.nombre_medico}. "
                f"Sucursal: {self.session.sucursal}.\n"
                f"TURNO YA AGENDADO: {self.session.fecha_turno_spoken} "
                f"a {self.session.hora_turno_spoken} "
                f"(ISO {self.session.fecha_turno}).\n"
                f"Hoy={hoy}. 'mañana'={manana}. Reprogramar hasta={self.session.fecha_limite} "
                f"(máx {self.session.max_dias} días).\n"
                "\n"
                "CÓMO RESPONDER:\n"
                "- Podés HABLAR en texto libre (empatía, repetir día y hora, repreguntar).\n"
                "- Si confirma que VA / 'sí asisto' / 'ahí voy' / 'todo bien' → "
                "confirmar_asistencia.\n"
                "- Si no puede esa fecha y propone otra → reagendar_cita(fecha_iso).\n"
                "- Si no quiere el turno / cancela → cancelar_cita.\n"
                "- responder_kb SOLO ante FAQ (dirección, documentos, costo, hora, médico). "
                "Después volvé a pedir la confirmación de asistencia.\n"
                "- finalizar(reagendar_despues) si pide que lo llamen otro día.\n"
                "No verbalices nombres de tools.\n"
                f"{custom}\n"
                "TEMAS FAQ (ante una de estos, llamá responder_kb con la pregunta "
                f"literal del usuario y volvé a pedir la confirmación de asistencia; "
                f"NO improvises la respuesta): {kb_topics}.\n"
            )
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
            "TEMAS FAQ (ante una de estos, llamá responder_kb con la pregunta "
            f"literal del usuario; NO improvises la respuesta): {kb_topics}.\n"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        if self._confirm_mode():
            # agendar_cita == reagendar_cita en confirm mode: una sola tool
            # (menos tokens de schema por request y menos ambigüedad de routing).
            return [
                self.confirmar_asistencia,
                self.reagendar_cita,
                self.cancelar_cita,
                self.finalizar,
                self.responder_kb,
            ]
        return [self.agendar_cita, self.finalizar, self.responder_kb]

    async def _advance_first(self, labels: Sequence[str]) -> bool:
        for label in labels:
            if not edge_for(self.flow, self.node_id, label):
                continue
            landed = await self.advance(label)
            if landed:
                return True
        return False

    async def _guard_phase(self, params) -> bool:
        if self.session.phase == "identity":
            await params.result_callback(
                {
                    "ok": False,
                    "error": "Todavía en identidad. Primero registrar_resultado_identidad.",
                },
                properties=_CONTINUE,
            )
            return False
        if self.session.phase == "done":
            await params.result_callback(
                {"ok": False, "error": "Llamada ya cerrada.", "status": self.session.final_status},
                properties=_WAIT,
            )
            return False
        return True

    @register_tool(type="normal")
    async def confirmar_asistencia(self, params, evidencia: Optional[str] = None) -> None:
        """El paciente confirma que va a asistir al turno ya agendado."""
        if not await self._guard_phase(params):
            return
        fecha = self.session.fecha_turno or self.session.commitment_date
        self.session.commitment_date = fecha
        self.session.commitment_date_spoken = (
            self.session.fecha_turno_spoken or spoken_date(fecha or "")
        )
        self.session.final_status = "Asistencia confirmada"
        landed = await self._advance_first(
            ("Asistencia confirmada", "Ya tenía cita", "Ya atendido")
        )
        if not landed:
            if has_node(self.flow, "intent.confirm_attendance"):
                await self.say_node("intent.confirm_attendance")
            if has_node(self.flow, "final.end_confirmed"):
                await self.say_node("final.end_confirmed")
            await self.set_phase("done")
        await params.result_callback(
            {
                "ok": True,
                "outcome": "Asistencia confirmada",
                "appointment_date": fecha,
                "evidence": evidencia,
            },
            properties=_WAIT,
        )

    @register_tool(type="normal")
    async def cancelar_cita(self, params, razon: Optional[str] = None) -> None:
        """Cancela el turno ya agendado. No reprograma."""
        if not await self._guard_phase(params):
            return
        self.session.final_status = "Cita cancelada"
        landed = await self._advance_first(("Cita cancelada", "Sin cita"))
        if not landed:
            if has_node(self.flow, "intent.soft_close_cancelled"):
                await self.say_node("intent.soft_close_cancelled")
            if has_node(self.flow, "final.end_cancelled"):
                await self.say_node("final.end_cancelled")
            await self.set_phase("done")
        await params.result_callback(
            {"ok": True, "outcome": "Cita cancelada", "reason": razon},
            properties=_WAIT,
        )

    @register_tool(type="normal")
    async def reagendar_cita(self, params, fecha_iso: str) -> None:
        """Reprograma el turno existente a otra fecha (AAAA-MM-DD o hoy/mañana)."""
        await self._book_date(params, fecha_iso, confirm_mode=True)

    @register_tool(type="normal")
    async def agendar_cita(self, params, fecha_iso: str) -> None:
        """Agenda o reprograma la consulta. fecha_iso: AAAA-MM-DD o relativa (hoy/mañana)."""
        await self._book_date(params, fecha_iso, confirm_mode=self._confirm_mode())

    async def _book_date(self, params, fecha_iso: str, *, confirm_mode: bool) -> None:
        if not await self._guard_phase(params):
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
            if confirm_mode:
                self.session.final_status = "Cita reagendada"
                labels = ("Cita reagendada", "Cita agendada")
                fallbacks = ("intent.confirm_reschedule", "final.end_rescheduled", "final.end_commitment")
            else:
                self.session.final_status = "Cita agendada"
                labels = ("Cita agendada", "Cita reagendada")
                fallbacks = ("intent.confirm_commitment", "final.end_commitment")
            landed = await self._advance_first(labels)
            if not landed:
                for node_id in fallbacks:
                    if has_node(self.flow, node_id):
                        await self.say_node(node_id)
                await self.set_phase("done")
            await params.result_callback(
                {
                    "ok": True,
                    "outcome": self.session.final_status,
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
            landed = await self._advance_first(("Reagendar después",))
            if not landed:
                if has_node(self.flow, "final.end_callback"):
                    await self.say_node("final.end_callback")
                elif has_node(self.flow, "final.end_intencion_de_pago"):
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
        if resultado == "ya_agendada" and self._confirm_mode():
            await self.confirmar_asistencia(params, evidencia=razon)
            return
        if resultado == "sin_cita" and self._confirm_mode():
            await self.cancelar_cita(params, razon=razon)
            return
        mapping = {
            "sin_cita": ("Sin cita", ("Sin cita", "Cita cancelada")),
            "ya_agendada": ("Ya tenía cita", ("Ya tenía cita", "Ya atendido", "Asistencia confirmada")),
            "reagendar_despues": ("Reagendar después", ("Reagendar después",)),
        }
        status, labels = mapping[resultado]
        self.session.final_status = status
        landed = await self._advance_first(labels)
        if not landed:
            fallbacks = {
                "sin_cita": ("intent.soft_close_no_commitment", "intent.soft_close_cancelled", "final.end_cancelled", "final.end_no_commitment"),
                "ya_agendada": ("intent.confirm_attendance", "final.end_confirmed", "final.end_paid"),
                "reagendar_despues": ("final.end_callback", "final.end_intencion_de_pago"),
            }
            for node_id in fallbacks[resultado]:
                if has_node(self.flow, node_id):
                    await self.say_node(node_id)
            await self.set_phase("done")
        await params.result_callback(
            {"ok": True, "outcome": status, "reason": razon}, properties=_WAIT
        )
