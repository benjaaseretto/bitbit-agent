"""Matching de FAQ (KB) reutilizable por tasks de agenda y venta."""
from __future__ import annotations

from typing import Any, Optional

from pipecat.frames.frames import FunctionCallResultProperties

from app.utils.templates import render_template
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)

_FILLERS = {
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


def match_kb_answer(knowledge_base: list[dict[str, Any]], pregunta: str) -> Optional[str]:
    q = (pregunta or "").strip().lower()
    if not q:
        return None
    best = None
    best_score = 0
    for item in knowledge_base:
        keys = [
            k.strip()
            for k in str(item.get("question", "")).lower().split("|")
            if k.strip()
        ]
        for k in keys:
            if len(k) >= 6 and (k in q or q in k):
                score = len(k)
                if score > best_score:
                    best_score = score
                    best = item.get("answer")
                continue
            k_tokens = {
                t for t in k.replace("¿", "").replace("?", "").split() if len(t) > 3
            }
            q_tokens = {
                t for t in q.replace("¿", "").replace("?", "").split() if len(t) > 3
            }
            if k_tokens and len(k_tokens & q_tokens) >= 2:
                score = len(k_tokens & q_tokens)
                if score > best_score:
                    best_score = score
                    best = item.get("answer")
    return str(best) if best else None


class KbMixin:
    """Añade responder_kb a una task."""

    @register_tool(type="normal")
    async def responder_kb(self, params, pregunta: str) -> None:
        """Responde una FAQ de la KB. Pasá la pregunta literal del usuario."""
        q_raw = (pregunta or "").strip()
        q = q_raw.lower()
        if q in _FILLERS or len(q) < 8:
            await params.result_callback(
                {
                    "ok": False,
                    "skip_kb": True,
                    "note": "No es una FAQ. Respondé en texto libre y seguí el objetivo de la fase.",
                },
                properties=_CONTINUE,
            )
            return

        best = match_kb_answer(self.session.knowledge_base, q_raw)
        if not best:
            await params.result_callback(
                {
                    "ok": False,
                    "no_match": True,
                    "note": "Sin FAQ. Respondé en texto con lo que sabés de la sesión y volvé al objetivo.",
                },
                properties=_CONTINUE,
            )
            return

        answer = render_template(str(best), self.session.as_template_vars())
        if self.session.last_kb_answer == answer:
            self.session.kb_repeats += 1
            await params.result_callback(
                {
                    "ok": False,
                    "repeat_blocked": True,
                    "note": "Ya diste esa FAQ. No la repitas. Seguí el objetivo de la fase.",
                },
                properties=_CONTINUE,
            )
            return

        self.session.last_kb_answer = answer
        self.session.kb_repeats = 0
        await self.speak(answer)
        await params.result_callback(
            {"ok": True, "note": "Tras la FAQ, volvé al objetivo de la fase."},
            properties=_WAIT,
        )
