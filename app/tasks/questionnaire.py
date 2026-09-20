"""QuestionnaireTask: clasificación a claves del schema (no texto libre)."""
from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from pipecat.frames.frames import FunctionCallResultProperties

from app.tasks.base import BaseTask, TaskContext
from app.tasks.kb import KbMixin
from app.tasks.registry import register_task
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)


@register_task
class QuestionnaireTask(KbMixin, BaseTask):
    task_type = "QuestionnaireTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.questionnaire") -> None:
        super().__init__(ctx, node_id=node_id)

    def _schema(self) -> list[dict[str, Any]]:
        return list(self.node_params().get("schema") or [])

    def _options(self) -> list[str]:
        values: list[str] = []
        for field in self._schema():
            for opt in field.get("options") or []:
                val = opt.get("value") if isinstance(opt, dict) else opt
                if val is not None:
                    values.append(str(val))
        return values

    def system_prompt(self) -> str:
        params = self.node_params()
        custom = params.get("instructions") or ""
        title = params.get("title") or "cuestionario"
        options = ", ".join(self._options()) or "las claves del schema"
        labels = "; ".join(
            f"{f.get('name')}: {f.get('label')}" for f in self._schema() if f.get("label")
        )
        return (
            f"Sos {self.session.nombre_agente} de {self.session.nombre_empresa}. "
            f"FASE: CUESTIONARIO ({title}).\n"
            f"Preguntá: {labels or title}.\n"
            f"Claves válidas: {options}. NUNCA registres texto libre.\n"
            "- registrar_respuesta(clave) con UNA clave de esa lista (o 'duda').\n"
            "- repetir_pregunta si pide que repitas.\n"
            "- cancelar_cuestionario SOLO si pide terminar.\n"
            "- responder_kb si pregunta un término de la FAQ.\n"
            f"{custom}"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [
            self.registrar_respuesta,
            self.repetir_pregunta,
            self.cancelar_cuestionario,
            self.responder_kb,
        ]

    @register_tool(type="normal")
    async def registrar_respuesta(self, params, clave: str) -> None:
        """Clasifica la respuesta en una clave del schema (incl. duda)."""
        raw = (clave or "").strip()
        allowed = set(self._options()) | {"duda"}
        if allowed and raw not in allowed:
            # match case-insensitive
            mapped = next((v for v in allowed if v.lower() == raw.lower()), None)
            if mapped:
                raw = mapped
            else:
                await params.result_callback(
                    {
                        "ok": False,
                        "error": f"Clave inválida. Usá una de: {sorted(allowed)}",
                    },
                    properties=_CONTINUE,
                )
                return
        field = self._schema()[0] if self._schema() else {"name": "respuesta"}
        name = str(field.get("name") or "respuesta")
        self.session.variables[name] = raw
        if raw == "duda":
            await self.advance("duda")
            await params.result_callback({"ok": True, "clave": raw, "held": True}, properties=_WAIT)
            return
        landed = await self.advance("Completado")
        if not landed:
            await self.advance("Continuar")
        await params.result_callback({"ok": True, "clave": raw, "field": name}, properties=_WAIT)

    @register_tool(type="normal")
    async def repetir_pregunta(self, params) -> None:
        """Repite la pregunta del campo, sin avanzar."""
        field = self._schema()[0] if self._schema() else {}
        label = field.get("label") or self.node_params().get("title") or "la pregunta"
        await self.speak(f"Por supuesto. Necesito saber {label}.")
        await params.result_callback({"ok": True, "repeated": True}, properties=_WAIT)

    @register_tool(type="normal")
    async def cancelar_cuestionario(self, params, razon: Optional[str] = None) -> None:
        """El usuario corta el cuestionario."""
        await self.advance("Cancelado")
        await params.result_callback(
            {"ok": True, "outcome": "Cancelado", "reason": razon}, properties=_WAIT
        )
