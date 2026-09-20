"""Carga de specs/KB independientes y construcción de sesión."""
from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from app.flow_graph.catalog import find_flow_graph_path, load_flow_wrapper, resolve_kb_path
from app.session.call_session import CallSession
from app.utils.dates import today_in_tz
from app.utils.templates import render_template

APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_FLOW_KEY = os.getenv("BITBIT_FLOW_KEY", "clinica_vida_flow")

# Paths canónicos (tests / compat)
SPEC_PATH = APP_DIR / "flow_graph" / "specs" / "clinica_vida_flow_graph.json"
KB_PATH = APP_DIR / "kb" / "clinica_vida.json"


def _int_or_default(raw: Any, default: int) -> int:
    """No confundir 0 con 'ausente' (bug histórico: saldo/plazo 0 → default)."""
    if raw is None or raw == "":
        return default
    return int(raw)


def load_flow_by_key(flow_key: Optional[str] = None) -> dict[str, Any]:
    key = (flow_key or DEFAULT_FLOW_KEY).strip()
    path = find_flow_graph_path(key)
    if not path:
        # Fallback al spec médico canónico
        if SPEC_PATH.exists():
            return load_flow_wrapper(str(SPEC_PATH))
        raise FileNotFoundError(f"No flow spec for key={key!r}")
    return load_flow_wrapper(path)


def load_kb_for_flow(flow: dict[str, Any]) -> list[dict[str, Any]]:
    kb_path = resolve_kb_path(flow, app_dir=str(APP_DIR))
    if not kb_path or not Path(kb_path).exists():
        if KB_PATH.exists():
            kb_path = str(KB_PATH)
        else:
            return []
    with open(kb_path, encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else []


def load_flow_spec() -> dict[str, Any]:
    return load_flow_by_key(DEFAULT_FLOW_KEY)


def load_kb() -> list[dict[str, Any]]:
    return load_kb_for_flow(load_flow_spec())


def node(flow: dict[str, Any], node_id: str) -> dict[str, Any]:
    return flow["flow_graph"]["nodes"][node_id]


def say_text(flow: dict[str, Any], node_id: str, session: CallSession) -> str:
    nodes = flow.get("flow_graph", {}).get("nodes") or {}
    n = nodes.get(node_id)
    if not isinstance(n, dict):
        return ""
    prompt = n.get("prompt")
    if not prompt and isinstance(n.get("prompt_by"), dict):
        prompt_by = n["prompt_by"]
        prompt = prompt_by.get("default") or next(iter(prompt_by.values()), "")
    return render_template(str(prompt or ""), session.as_template_vars())


def build_session(
    metadata: Optional[dict[str, Any]] = None,
    *,
    flow_key: Optional[str] = None,
) -> tuple[CallSession, dict[str, Any]]:
    meta = dict(metadata or {})
    key = str(meta.get("flow_key") or flow_key or DEFAULT_FLOW_KEY)
    flow = load_flow_by_key(key)
    kb = load_kb_for_flow(flow)
    tz = str(meta.get("timezone") or "America/Mexico_City")
    max_dias = _int_or_default(meta.get("max_dias"), 7)
    limite = (today_in_tz(tz) + timedelta(days=max_dias)).isoformat()

    catalog = flow.get("flow_catalog") or {}
    resolved_key = str(
        catalog.get("platform_flow_key") or catalog.get("flow_key") or key
    )

    session = CallSession(
        call_id=str(meta.get("id") or uuid.uuid4().hex[:12]),
        nombre_agente=str(meta.get("nombre_agente") or "Ana"),
        nombre_deudor=str(
            meta.get("name")
            or meta.get("nombre_paciente")
            or meta.get("nombre_deudor")
            or "Paciente"
        ),
        nombre_empresa=str(meta.get("company_name") or "Clínica Vida"),
        especialidad=str(meta.get("especialidad") or "medicina general"),
        nombre_medico=str(meta.get("nombre_medico") or "el médico de turno"),
        sucursal=str(meta.get("sucursal") or "sucursal Centro"),
        max_dias=max_dias,
        timezone=tz,
        fecha_limite=limite,
        current_node_id=str(flow["flow_graph"]["start"]),
        phase="identity",
        flow_key=resolved_key,
    )
    vars_ = session.as_template_vars()
    session.knowledge_base = [
        {
            "question": item.get("question", ""),
            "answer": render_template(str(item.get("answer", "")), vars_),
        }
        for item in kb
    ]
    return session, flow
