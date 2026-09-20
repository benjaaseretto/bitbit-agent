"""Function tools Pipecat para identidad + negociación (flujo bitbit)."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Literal, Optional

from loguru import logger
from pipecat.frames.frames import FunctionCallResultProperties

from app.pipecat_runtime.flow_data import (
    render_template,
    resolve_relative_fecha,
    say_text,
    spoken_date,
    today_in_tz,
    validate_commitment_date,
)
from app.pipecat_runtime.session import BitbitSession

SpeakFn = Callable[[str], Awaitable[None]]
PhaseFn = Callable[[str], Awaitable[None]]

# After scripted speak + wait for user (or call end): do not let the LLM invent
# another tool turn on the same user utterance.
_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)


class FlowController:
    """Avanza el grafo bitbit y expone tools al LLM de Pipecat."""

    def __init__(
        self,
        session: BitbitSession,
        flow: dict[str, Any],
        *,
        speak: SpeakFn,
        on_phase: Optional[PhaseFn] = None,
    ) -> None:
        self.session = session
        self.flow = flow
        self._speak = speak
        self._on_phase = on_phase

    async def _set_phase(self, phase: str) -> None:
        self.session.phase = phase
        if not self._on_phase:
            return
        try:
            await self._on_phase(phase)
        except Exception:
            logger.exception("on_phase failed phase={}", phase)

    def identity_system_prompt(self) -> str:
        apertura = render_template(
            self.flow["flow_graph"]["nodes"]["task.identity_verification"]["params"][
                "identity_identificacion_breve"
            ],
            self.session.as_template_vars(),
        )
        return (
            "Sos Bitbit, agente de voz de cobranza. Estás en VERIFICACIÓN DE IDENTIDAD.\n"
            f"Apertura: {apertura}\n"
            f"Confirmá si hablás con {self.session.nombre_deudor}.\n"
            "Usá SOLO tools. No inventes montos ni políticas. No digas nombres de tools.\n"
            "Si confirma ser titular → registrar_resultado_identidad(titular_confirmado) "
            "con evidencia literal del usuario.\n"
            "Si no es y no lo conoce → persona_equivocada. Si tercero que lo conoce → recado. "
            "Si buzón → buzon.\n"
            "Si van a pasar al titular → esperar_titular.\n"
            "No avances a negociación con texto libre: siempre tool."
        )

    def negotiation_system_prompt(self) -> str:
        custom = (
            self.flow["flow_graph"]["nodes"]["task.negotiation"]["params"].get(
                "custom_instructions"
            )
            or ""
        )
        kb_lines = [
            f"- Q: {item.get('question')}\n  A: {item.get('answer')}"
            for item in self.session.knowledge_base[:15]
        ]
        hoy = today_in_tz(self.session.timezone).isoformat()
        manana = resolve_relative_fecha("mañana", timezone=self.session.timezone)
        return (
            "Sos Bitbit, agente de cobranza por financiamiento celular.\n"
            "FASE: NEGOCIACIÓN. Identidad YA confirmada.\n"
            "PROHIBIDO llamar registrar_resultado_identidad o esperar_titular.\n"
            f"Cliente: {self.session.nombre_deudor}. Monto: {self.session.monto_deuda_palabras}.\n"
            f"Hoy={hoy}. 'mañana'={manana}. Plazo máximo={self.session.fecha_limite} "
            f"(máx {self.session.max_dias} días).\n"
            "\n"
            "CÓMO RESPONDER (importante):\n"
            "- Podés HABLAR en texto libre (empatía, proponer fecha, repreguntar). "
            "NO hace falta tool en cada turno.\n"
            "- Si el usuario cuenta un problema (sin trabajo, olvido, etc.): "
            "empatizá en texto y proponé pagar hoy o mañana. NO llames responder_kb.\n"
            "- Si dice una fecha (hoy/mañana/día concreto): "
            "cliente_dispuesto(fecha_iso AAAA-MM-DD).\n"
            "- responder_kb SOLO si hace una pregunta FAQ clara "
            "(¿cuánto debo?, ¿cómo pago?, ¿me bloquean?). "
            "Pasá la pregunta del usuario, NO copies títulos de la KB.\n"
            "- Nunca repitas la misma respuesta KB. Tras empatizar, pedí una fecha.\n"
            "- finalizar solo si rechaza pagar o ya pagó.\n"
            "No verbalices nombres de tools. No inventes montos.\n"
            f"{custom}\n"
            f"KB (referencia):\n" + "\n".join(kb_lines)
        )

    async def esperar_titular(self, params) -> None:
        """Espera a que pongan al titular al teléfono."""
        if self.session.phase != "identity":
            await params.result_callback(
                {"ok": False, "error": "Ya no estás en identidad.", "phase": self.session.phase},
                properties=_CONTINUE,
            )
            return
        await self._speak("Perfecto, espero.")
        await params.result_callback({"ok": True, "action": "wait"}, properties=_WAIT)

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
        """Registra el resultado de verificación de identidad."""
        # Idempotent: avoid re-opening / re-failing after phase advance
        if self.session.phase in ("negotiation", "done"):
            await params.result_callback(
                {
                    "ok": True,
                    "already": True,
                    "phase": self.session.phase,
                    "status": self.session.final_status,
                    "note": (
                        "Identidad ya resuelta. "
                        "Usá cliente_dispuesto(fecha_iso) o finalizar. "
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
        logger.info("BITBIT identity outcome={} next={}", status, next_id)

        if resultado == "titular_confirmado":
            self.session.current_node_id = "task.negotiation"
            await self._speak(say_text(self.flow, "intent.opening", self.session))
            await self._set_phase("negotiation")
            await params.result_callback(
                {
                    "ok": True,
                    "status": status,
                    "next_phase": "negotiation",
                    "note": (
                        "Negociación activa. Esperá la respuesta del usuario; "
                        "después cliente_dispuesto(fecha_iso) o finalizar."
                    ),
                },
                properties=_WAIT,
            )
            return

        await self._speak(say_text(self.flow, next_id, self.session))
        self.session.current_node_id = next_id
        await self._set_phase("done")
        await params.result_callback(
            {"ok": True, "status": status, "end": True}, properties=_WAIT
        )

    async def cliente_dispuesto(self, params, fecha_iso: str) -> None:
        """Registra disposición de pago. fecha_iso: AAAA-MM-DD o relativa (hoy/mañana)."""
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
        node_params = self.flow["flow_graph"]["nodes"]["task.negotiation"]["params"]
        if ok and normalized:
            self.session.commitment_date = normalized
            self.session.commitment_date_spoken = spoken_date(normalized)
            self.session.final_status = "Compromiso"
            await self._speak(say_text(self.flow, "intent.confirm_commitment", self.session))
            await self._speak(say_text(self.flow, "final.end_commitment", self.session))
            await self._set_phase("done")
            await params.result_callback(
                {
                    "ok": True,
                    "outcome": "Compromiso",
                    "commitment_date": normalized,
                    "resolved_from": fecha_iso,
                },
                properties=_WAIT,
            )
            return

        self.session.dates_intentions.append(fecha_iso)
        self.session.negotiation_attempts += 1
        max_attempts = int(node_params.get("max_attempts") or 3)
        if self.session.negotiation_attempts >= max_attempts:
            self.session.final_status = "Intención de pago"
            await self._speak(say_text(self.flow, "final.end_intencion_de_pago", self.session))
            await self._set_phase("done")
            await params.result_callback(
                {"ok": True, "outcome": "Intención de pago"}, properties=_WAIT
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
        await self._speak(msg)
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

    async def finalizar(
        self,
        params,
        resultado: Literal["sin_compromiso", "pagado", "intencion_de_pago"],
        razon: Optional[str] = None,
    ) -> None:
        """Cierra negociación: sin_compromiso | pagado | intencion_de_pago."""
        if self.session.phase == "identity":
            await params.result_callback(
                {"ok": False, "error": "Todavía en identidad; no cierres aún."},
                properties=_CONTINUE,
            )
            return
        mapping = {
            "sin_compromiso": (
                "Sin compromiso",
                "intent.soft_close_no_commitment",
                "final.end_no_commitment",
            ),
            "pagado": ("Pagado", None, "final.end_paid"),
            "intencion_de_pago": ("Intención de pago", None, "final.end_intencion_de_pago"),
        }
        status, soft, final_id = mapping[resultado]
        self.session.final_status = status
        if soft:
            await self._speak(say_text(self.flow, soft, self.session))
        await self._speak(say_text(self.flow, final_id, self.session))
        await self._set_phase("done")
        await params.result_callback(
            {"ok": True, "outcome": status, "reason": razon}, properties=_WAIT
        )

    async def responder_kb(self, params, pregunta: str) -> None:
        """Responde con la KB solo ante FAQ real del usuario (no loops)."""
        q_raw = (pregunta or "").strip()
        q = q_raw.lower()

        # Block FAQ-title dumps / filler turns — force negotiation speech instead
        fillers = {
            "ok",
            "ok.",
            "ok,",
            "entiendo",
            "ok entiendo",
            "ok, entiendo",
            "sí",
            "si",
            "ehm",
            "ehm...",
            "mmm",
            "ajá",
            "aja",
        }
        if q in fillers or len(q) < 8:
            await params.result_callback(
                {
                    "ok": False,
                    "skip_kb": True,
                    "note": (
                        "Eso no es una pregunta FAQ. Respondé en texto libre: "
                        "empatizá y pedí una fecha de pago (hoy/mañana). "
                        "NO vuelvas a llamar responder_kb."
                    ),
                },
                properties=_CONTINUE,
            )
            return

        best = None
        best_score = 0
        for item in self.session.knowledge_base:
            keys = [k.strip() for k in str(item.get("question", "")).lower().split("|") if k.strip()]
            # Match if a key appears in the user question, or substantial overlap
            for k in keys:
                if len(k) >= 6 and (k in q or q in k):
                    score = len(k)
                    if score > best_score:
                        best_score = score
                        best = item.get("answer")
                else:
                    # token overlap for short FAQ probes
                    k_tokens = {t for t in k.replace("¿", "").replace("?", "").split() if len(t) > 3}
                    q_tokens = {t for t in q.replace("¿", "").replace("?", "").split() if len(t) > 3}
                    if k_tokens and len(k_tokens & q_tokens) >= 2:
                        score = len(k_tokens & q_tokens)
                        if score > best_score:
                            best_score = score
                            best = item.get("answer")

        if not best:
            await params.result_callback(
                {
                    "ok": False,
                    "no_match": True,
                    "note": (
                        "No hay FAQ para eso. Respondé en texto: empatía + "
                        "proponé fecha hoy/mañana. Luego cliente_dispuesto si acepta."
                    ),
                },
                properties=_CONTINUE,
            )
            return

        answer = str(best)
        if self.session.last_kb_answer == answer:
            self.session.kb_repeats += 1
            await params.result_callback(
                {
                    "ok": False,
                    "repeat_blocked": True,
                    "note": (
                        "Ya dijiste esa FAQ. NO la repitas. "
                        "Hablá en texto y pedí una fecha concreta de pago."
                    ),
                },
                properties=_CONTINUE,
            )
            return

        self.session.last_kb_answer = answer
        self.session.kb_repeats = 0
        await self._speak(answer)
        await params.result_callback(
            {
                "ok": True,
                "note": "Tras la FAQ, en el próximo turno pedí fecha de pago (texto libre).",
            },
            properties=_WAIT,
        )
