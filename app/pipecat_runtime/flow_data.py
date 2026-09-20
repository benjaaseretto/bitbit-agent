"""Compat: carga de flujo + utilidades (canónico en app.orchestrator / app.utils)."""
from __future__ import annotations

from app.orchestrator.loader import (
    APP_DIR,
    DEFAULT_FLOW_KEY,
    KB_PATH,
    SPEC_PATH,
    build_session,
    load_flow_by_key,
    load_flow_spec,
    load_kb,
    load_kb_for_flow,
    node,
    say_text,
)
from app.utils.dates import (
    amount_to_words,
    parse_iso_date,
    resolve_relative_fecha,
    spoken_date,
    today_in_tz,
    validate_commitment_date,
)
from app.utils.templates import render_template

__all__ = [
    "APP_DIR",
    "DEFAULT_FLOW_KEY",
    "KB_PATH",
    "SPEC_PATH",
    "amount_to_words",
    "build_session",
    "load_flow_by_key",
    "load_flow_spec",
    "load_kb",
    "load_kb_for_flow",
    "node",
    "parse_iso_date",
    "render_template",
    "resolve_relative_fecha",
    "say_text",
    "spoken_date",
    "today_in_tz",
    "validate_commitment_date",
]
