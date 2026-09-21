"""Plantillas de texto para prompts y say nodes."""
from __future__ import annotations

import re
from typing import Any

# Placeholders sin valor: el TTS no debe leer "{saludo_por_horario}" en voz alta.
_UNRESOLVED = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def render_template(text: str, variables: dict[str, Any]) -> str:
    out = str(text or "")
    for key in sorted(variables, key=lambda item: -len(str(item))):
        value = variables[key]
        out = out.replace("{" + str(key) + "}", "" if value is None else str(value))
    out = _UNRESOLVED.sub("", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r" +([.,;:?!])", r"\1", out)
    return out.strip()


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_tts_utterances(text: str, *, max_chars: int = 720) -> list[str]:
    """Parte solo scripts extremos.

    En Mac no bajes de ~720: cada TTSSpeakFrame nuevo paga TTFB/prebuffer
    (~1.3s) y suena a corte entre frases.
    """
    raw = " ".join(str(text or "").split())
    if not raw:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(raw) if p.strip()] or [raw]
    chunks: list[str] = []
    buf = ""
    for piece in parts:
        if buf and len(buf) + 1 + len(piece) > max_chars:
            chunks.append(buf)
            buf = piece
        else:
            buf = f"{buf} {piece}".strip()
    if buf:
        chunks.append(buf)
    return chunks


def render_value(value: Any, variables: dict[str, Any]) -> Any:
    """Renderiza placeholders en strings anidados (params del nodo)."""
    if isinstance(value, str):
        return render_template(value, variables)
    if isinstance(value, list):
        return [render_value(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: render_value(item, variables) for key, item in value.items()}
    return value
