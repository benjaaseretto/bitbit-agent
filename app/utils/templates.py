"""Plantillas de texto para prompts y say nodes."""
from __future__ import annotations

from typing import Any


def render_template(text: str, variables: dict[str, Any]) -> str:
    out = text
    for key, value in variables.items():
        out = out.replace("{" + str(key) + "}", str(value))
    return out
