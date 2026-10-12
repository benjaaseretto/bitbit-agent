"""Contrato tipado bot → frontend para el data channel de Studio.

Mensaje:
    {"type": "visualization", "message": str, "visualization": <spec validada>}

Se envía por el mismo canal que el HUD (OutputTransportMessageFrame → data
channel WebRTC → onMessage del frontend). El frontend valida de nuevo y
renderiza con createElement/textContent; nunca eval ni innerHTML.
"""
from __future__ import annotations

from typing import Any

from app.analytics.visualizations import VisualizationError, validate_visualization


class ContractError(ValueError):
    pass


def build_insight_message(message: str, visualization: dict[str, Any]) -> dict[str, Any]:
    """Arma y valida el mensaje completo antes de enviarlo al frontend."""
    text = " ".join(str(message or "").split())
    if not text or len(text) > 300:
        raise ContractError("message vacío o > 300 caracteres")
    try:
        spec = validate_visualization(visualization)
    except VisualizationError as exc:
        raise ContractError(f"visualización inválida: {exc}") from None
    return {"type": "visualization", "message": text, "visualization": spec}


def validate_insight_message(payload: Any) -> dict[str, Any]:
    """Valida un mensaje entrante/saliente del canal (defensa en profundidad)."""
    if not isinstance(payload, dict) or payload.get("type") != "visualization":
        raise ContractError("type debe ser 'visualization'")
    extra = set(payload) - {"type", "message", "visualization"}
    if extra:
        raise ContractError(f"claves no permitidas: {sorted(extra)}")
    return build_insight_message(
        str(payload.get("message") or ""), payload.get("visualization") or {}
    )