"""Script independiente: verificación de identidad del paciente."""
from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Sequence

from loguru import logger
from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.graph import edge_for, has_node
from app.tasks.registry import register_task
from app.utils.templates import render_template
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)

_RESULTADO_ALIASES = {
    "tercero": "recado",
    "tercero_conocido": "recado",
    "third_party": "recado",
    "wrong_person": "persona_equivocada",
    "equivocado": "persona_equivocada",
    "mailbox": "buzon",
    "voicemail": "buzon",
    "fallecido": "titular_fallecido",
}

_CONFIRM_MARKERS = (
    "sí",
    "si ",
    "si,",
    "soy yo",
    "correcto",
    "así es",
    "asi es",
    "claro",
    "dígame",
    "digame",
    "habla con él",
    "habla con el",
    "habla con ella",
    "con él",
    "con ella",
)
_DENY_MARKERS = (
    "no soy",
    "no es",
    "equivocad",
    "número equivocado",
    "numero equivocado",
    "se equivocó",
    "se equivoco",
    "no me llamo",
    "persona equivocada",
    "no es ella",
    "no es él",
    "no es el",
)


def _fold_name(raw: str) -> str:
    import unicodedata

    norm = unicodedata.normalize("NFD", (raw or "").lower())
    return "".join(ch for ch in norm if unicodedata.category(ch) != "Mn")


def _first_name(raw: str) -> str:
    parts = _fold_name(raw).replace(",", " ").split()
    return parts[0] if parts else ""


def _names_close(heard: str, expected: str) -> bool:
    a, b = _fold_name(heard), _fold_name(expected)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4]


def _looks_like_denial(evidencia: str) -> bool:
    low = (evidencia or "").strip().lower()
    return any(marker in low for marker in _DENY_MARKERS)


def _looks_like_confirmation(evidencia: str, nombre: str) -> bool:
    raw = (evidencia or "").strip()
    if not raw:
        return False
    if _looks_like_denial(raw):
        return False
    low = raw.lower()
    if any(marker in low for marker in _CONFIRM_MARKERS):
        return True
    expected = _first_name(nombre)
    for token in _fold_name(raw).split():
        if expected and _names_close(token, expected):
            return True
    return False


def coerce_identity_resultado(resultado: str, evidencia: str, nombre: str) -> str:
    """STT confunde nombres (Carla→Carlos). No colgar sin negativa clara."""
    if resultado != "persona_equivocada":
        return resultado
    if _looks_like_confirmation(evidencia, nombre):
        logger.warning(
            "identity: equivocado anulado (confirmación/STT) evidencia={!r}", evidencia
        )
        return "titular_confirmado"
    if not _looks_like_denial(evidencia):
        logger.warning(
            "identity: equivocado anulado (sin negativa) evidencia={!r}", evidencia
        )
        return "repregunta"
    return resultado


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
            "Estás en VERIFICACIÓN DE IDENTIDAD del contacto.\n"
            f"Apertura: {apertura}\n"
            f"Pregunta clave: ¿Hablo con {self.session.nombre_deudor}?\n"
            "Usá SOLO tools. No des diagnósticos ni recetas. No digas nombres de tools.\n"
            "\n"
            "REGLAS ESTRICTAS:\n"
            f"- Si dice SÍ / 'sí soy yo' / 'correcto' / un nombre parecido a "
            f"{self.session.nombre_deudor} (el STT confunde Carla/Carlos) → "
            "registrar_resultado_identidad(titular_confirmado) con evidencia literal.\n"
            "- persona_equivocada SOLO con negativa clara ('no soy', 'número equivocado'). "
            "Audio raro → repregunta_identidad. NUNCA cuelgues por un nombre mal transcrito.\n"
            "- Si es tercero que lo conoce y deja recado → recado.\n"
            "- Si es buzón → buzon.\n"
            "- esperar_titular SOLO si dice explícitamente que VA A PASAR al contacto "
            "('se lo paso', 'un momento', 'espere'). NO la uses con audio confuso.\n"
            "- Si pregunta de parte de quién / quién habla / me repite → "
            "aclarar_quien_habla. NO uses recado ni repregunta sola.\n"
            "- Si no entendiste / ruido / no responde claro → repregunta_identidad.\n"
            "- resultado SOLO: titular_confirmado | persona_equivocada | recado | "
            "buzon | titular_fallecido. NUNCA 'tercero'.\n"
            "- NUNCA llames esperar_titular dos veces seguidas ni con frases sin sentido."
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [
            self.esperar_titular,
            self.repregunta_identidad,
            self.aclarar_quien_habla,
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
    async def aclarar_quien_habla(self, params) -> None:
        """Si pregunta de parte de quién, quién habla, o pide que le repitas."""
        if self.session.phase != "identity":
            await params.result_callback(
                {"ok": False, "error": "Ya no estás en identidad.", "phase": self.session.phase},
                properties=_CONTINUE,
            )
            return
        await self.speak(
            f"Soy {self.session.nombre_agente}, de {self.session.nombre_empresa}. "
            f"¿Hablo con {self.session.nombre_deudor}?"
        )
        await params.result_callback({"ok": True, "action": "identify"}, properties=_WAIT)

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
            "titular_fallecido",
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
            "titular_confirmado": ("Entregado", "Entregado"),
            "persona_equivocada": ("Equivocado", "Equivocado"),
            "recado": ("Recado conocido", "Recado conocido"),
            "buzon": ("Buzon de Voz", "Buzon de Voz"),
            "titular_fallecido": ("Fallecido", "Fallecido"),
        }
        resultado = _RESULTADO_ALIASES.get(str(resultado), resultado)
        resultado = coerce_identity_resultado(
            str(resultado), evidencia or "", self.session.nombre_deudor
        )
        if resultado == "repregunta":
            await self.speak(
                f"Disculpe, ¿me confirma si hablo con {self.session.nombre_deudor}?"
            )
            await params.result_callback(
                {
                    "ok": False,
                    "reprompt": True,
                    "note": "No cuelgues. Pedí confirmación otra vez.",
                },
                properties=_WAIT,
            )
            return
        if resultado not in mapping:
            await self.speak(
                f"Disculpe, ¿me confirma si hablo con {self.session.nombre_deudor}?"
            )
            await params.result_callback(
                {
                    "ok": False,
                    "error": f"resultado inválido: {resultado}",
                    "allowed": list(mapping),
                },
                properties=_WAIT,
            )
            return
        if resultado == "titular_confirmado" and not (evidencia or "").strip():
            await params.result_callback(
                {"error": "Falta evidencia literal del turno que confirma identidad."},
                properties=_CONTINUE,
            )
            return

        status, label = mapping[resultado]
        if not edge_for(self.flow, self.node_id, label):
            # Specs sin Fallecido: no inventar el outcome.
            if resultado == "titular_fallecido":
                status, label = "Recado conocido", "Recado conocido"
        self.session.final_status = status
        logger.info("identity outcome={} label={}", status, label)

        if resultado == "titular_confirmado":
            await self.advance("Entregado")
            if self.session.phase == "identity":
                await self.set_phase("negotiation")
            await params.result_callback(
                {
                    "ok": True,
                    "status": status,
                    "next_phase": "negotiation",
                    "note": "Identidad OK. Esperá respuesta y usá las tools de la fase de negocio.",
                },
                properties=_WAIT,
            )
            return

        landed = await self.advance(label)
        if not landed:
            fallback = {
                "Equivocado": "final.end_wrong",
                "Recado conocido": "final.end_recado",
                "Buzon de Voz": "final.end_mailbox",
                "Fallecido": "final.end_wrong",
            }.get(label)
            if fallback and has_node(self.flow, fallback):
                await self.say_node(fallback)
            await self.set_phase("done")
        await params.result_callback(
            {"ok": True, "status": status, "end": True}, properties=_WAIT
        )
