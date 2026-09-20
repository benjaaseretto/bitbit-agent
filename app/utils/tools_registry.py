"""Registro liviano de tools (estilo colly) para descubrimiento e índices."""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

TOOLS: Dict[str, Dict[str, Any]] = {}


def register_tool(type: Optional[str] = None) -> Callable:
    """Marca una función como tool descubrible. No cambia la firma Pipecat."""

    def decorator(func: Callable) -> Callable:
        TOOLS[func.__name__] = {
            "function": func,
            "type": type,
            "name": func.__name__,
            "description": func.__doc__,
        }
        return func

    return decorator
