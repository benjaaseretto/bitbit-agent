"""Script independiente: verificación de identidad del paciente."""
from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Sequence

from loguru import logger
from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.registry import register_task
from app.utils.templates import render_template
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)

_HANDOFF_MARKERS = (
    "paso",
    "pasar",
    "pásalo",
    "pasalo",
    "se lo paso",
    "un momento",
    "ahorita",
    "espere",
    "esperá",
    "espera",
    "lo llamo",
    "te lo paso",
)


@register_task
class IdentityVerificationTask(BaseTask):
    task_type = "IdentityVerificationTask"
    phase = "identity"
    tool_choice = "required"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.identity_verification") -> None:
        super().__init__(ctx)
        self.node_id = node_id

    def system_prompt(self) -> str:
        params = self.node_params(self.node_id)
        apertura = render_template(
            str(params.get("identity_identificacion_breve") or ""),
            self.session.as_template_vars(),
        )
        return (
            f"Sos {self.session.nombre_agente}, asistente de voz de {self.session.nombre_empresa}. "
            "Estás en VERIFICACIÓN DE IDENTIDAD del paciente.\n"
            f"Apertura: {apertura}\n"
            f"Pregunta clave: ¿Hablo con {self.session.nombre_deudor}?\n"
            "Usá SOLO tools. No des diagnósticos ni recetas. No digas nombres de tools.\n"
            "\n"
            "REGLAS ESTRICTAS:\n"
            f"- Si dice que SÍ es {self.session.nombre_deudor} / 'sí soy yo' / 'habla con él' → "
            "registrar_resultado_identidad(titular_confirmado) con evidencia literal.\n"
            "- Si no es y no lo conoce → persona_equivocada.\n"
            "- Si es tercero que lo conoce y deja recado → recado.\n"
            "- Si es buzón → buzon.\n"
            "- esperar_titular SOLO si dice explícitamente que VA A PASAR al paciente "
            "('se lo paso', 'un momento', 'espere'). NO la uses con audio confuso.\n"
            "- Si no entendiste / ruido / no responde claro → repregunta_identidad.\n"
            "- NUNCA llames esperar_titular dos veces seguidas ni con frases sin sentido."
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [
            self.esperar_titular,
            self.repregunta_identidad,
            self.registrar_resultado_identidad,
        ]

    @register_tool(type="normal")
    async def repregunta_identidad(self, params) -> None:
        """Si el audio es confuso o no confirma ni niega, vuelve a preguntar quién es."""
        if self.session.phase != "identity":
            await params.result_callback(
                {"ok": False, "error": "Ya no estás en identidad.", "phase": self.session.phase},
                properties=_CONTINUE,
            )
            return
        await self.speak(
            f"Disculpe, ¿me confirma si hablo con {self.session.nombre_deudor}?"
        )
        await params.result_callback({"ok": True, "action": "reprompt"}, properties=_WAIT)

    @register_tool(type="normal")
    async def esperar_titular(self, params, evidencia: Optional[str] = None) -> None:
        """SOLO si el usuario dice que va a pasar al paciente. evidencia = frase literal."""
        if self.session.phase != "identity":
            await params.result_callback(
                {"ok": False, "error": "Ya no estás en identidad.", "phase": self.session.phase},
                properties=_CONTINUE,
            )
            return

        waits = int(self.session.variables.get("esperar_titular_count") or 0)
        evidence = (evidencia or "").strip().lower()
        handoff = any(m in evidence for m in _HANDOFF_MARKERS) if evidence else False
        if waits >= 1 or not handoff:
            await self.speak(
                f"Disculpe, ¿hablo con {self.session.nombre_deudor}?"
            )
            await params.result_callback(
                {
                    "ok": False,
                    "rejected": True,
                    "note": (
                        "No uses esperar_titular sin evidencia de 'pasar al paciente'. "
                        "Si confirma identidad → registrar_resultado_identidad. "
                        "Si no se entiende → repregunta_identidad."
                    ),
                },
                properties=_WAIT,
            )
            return

        self.session.variables["esperar_titular_count"] = waits + 1
        await self.speak("Perfecto, espero.")
        await params.result_callback({"ok": True, "action": "wait"}, properties=_WAIT)

    @register_tool(type="normal")
    async def registrar_resultado_identidad(
        self,
        params,
        resultado: Literal[
            "titular_confirmado",
            "persona_equivocada",
            "recado",
            "buzon",
        ],
        evidencia: Optional[str] = None,
    ) -> None:
        """Registra el resultado de verificación de identidad del paciente."""
        if self.session.phase in ("negotiation", "done"):
            await params.result_callback(
                {
                    "ok": True,
                    "already": True,
                    "phase": self.session.phase,
                    "status": self.session.final_status,
                    "note": (
                        "Identidad ya resuelta. Usá agendar_cita(fecha_iso) o finalizar. "
                        "NO vuelvas a llamar esta tool."
                    ),
                },
                properties=_CONTINUE,
            )
            return

        mapping = {
            "titular_confirmado": ("Entregado", "intent.opening"),
            "persona_equivocada": ("Equivocado", "final.end_wrong"),
            "recado": ("Recado conocido", "final.end_recado"),
            "buzon": ("Buzon de Voz", "final.end_mailbox"),
        }
        if resultado == "titular_confirmado" and not (evidencia or "").strip():
            await params.result_callback(
                {"error": "Falta evidencia literal del turno que confirma identidad."},
                properties=_CONTINUE,
            )
            return

        status, next_id = mapping[resultado]
        self.session.final_status = status
        logger.info("identity outcome={} next={}", status, next_id)

        if resultado == "titular_confirmado":
            self.session.current_node_id = "task.negotiation"
            await self.say_node("intent.opening")
            await self.set_phase("negotiation")
            await params.result_callback(
                {
                    "ok": True,
                    "status": status,
                    "next_phase": "negotiation",
                    "note": (
                        "Agenda activa. Esperá la respuesta; después agendar_cita(fecha_iso) "
                        "o finalizar."
                    ),
                },
                properties=_WAIT,
            )
            return

        await self.say_node(next_id)
        self.session.current_node_id = next_id
        await self.set_phase("done")
        await params.result_callback(
            {"ok": True, "status": status, "end": True}, properties=_WAIT
        )
