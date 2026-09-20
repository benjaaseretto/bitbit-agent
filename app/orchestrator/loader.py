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
from app.utils.call_metadata import apply_derived_fields
from app.utils.dates import (
    resolve_relative_fecha,
    spoken_clock,
    spoken_date,
    spoken_greeting,
    today_in_tz,
)
from app.tasks.graph import prompt_from_by
from app.utils.templates import render_template

APP_DIR = Path(__file__).resolve().parents[1]


def default_flow_key() -> str:
    """Lee BITBIT_FLOW_KEY en runtime (después de load_dotenv)."""
    return (os.getenv("BITBIT_FLOW_KEY") or "clinica_vida_flow").strip()


DEFAULT_FLOW_KEY = "clinica_vida_flow"  # fallback documental; preferí default_flow_key()

# Paths canónicos (tests / compat)
SPEC_PATH = APP_DIR / "flow_graph" / "specs" / "clinica_vida_flow_graph.json"
KB_PATH = APP_DIR / "kb" / "clinica_vida.json"


def _int_or_default(raw: Any, default: int) -> int:
    """No confundir 0 con 'ausente' (bug histórico: saldo/plazo 0 → default)."""
    if raw is None or raw == "":
        return default
    return int(raw)


def load_flow_by_key(flow_key: Optional[str] = None) -> dict[str, Any]:
    key = (flow_key or default_flow_key()).strip()
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
    return load_flow_by_key(default_flow_key())


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
        prompt = prompt_from_by(n["prompt_by"], session)
    return render_template(str(prompt or ""), session.as_template_vars())


def build_session(
    metadata: Optional[dict[str, Any]] = None,
    *,
    flow_key: Optional[str] = None,
) -> tuple[CallSession, dict[str, Any]]:
    meta = dict(metadata or {})
    key = str(meta.get("flow_key") or flow_key or default_flow_key())
    flow = load_flow_by_key(key)
    kb = load_kb_for_flow(flow)
    tz = str(meta.get("timezone") or "America/Mexico_City")
    max_dias = _int_or_default(meta.get("max_dias"), 7)
    limite = (today_in_tz(tz) + timedelta(days=max_dias)).isoformat()

    catalog = flow.get("flow_catalog") or {}
    cfg = flow.get("flow_config") or {}
    resolved_key = str(
        catalog.get("platform_flow_key") or catalog.get("flow_key") or key
    )
    flow_company = str(cfg.get("company_pronunciation") or "").strip()
    preset_company = str(meta.get("company_name") or "").strip()
    # El preset demo es Clínica Vida; no pegarlo encima de Aurora / Andes / etc.
    if flow_company and (
        not preset_company
        or (preset_company == "Clínica Vida" and resolved_key != "clinica_vida_flow")
    ):
        nombre_empresa = flow_company
    else:
        nombre_empresa = preset_company or flow_company or "Clínica Vida"
    raw_turno = str(meta.get("fecha_turno") or meta.get("fecha_cita") or "mañana")
    fecha_turno = resolve_relative_fecha(raw_turno, timezone=tz)
    hora_turno = str(meta.get("hora_turno") or meta.get("hora_cita") or "10:00")
    hora_spoken = str(meta.get("hora_turno_spoken") or spoken_clock(hora_turno))
    franja = str(meta.get("franja_turno") or "").strip()

    session = CallSession(
        call_id=str(meta.get("id") or uuid.uuid4().hex[:12]),
        nombre_agente=str(meta.get("nombre_agente") or "Ana"),
        nombre_deudor=str(
            meta.get("name")
            or meta.get("nombre_paciente")
            or meta.get("nombre_deudor")
            or "Paciente"
        ),
        nombre_empresa=nombre_empresa,
        especialidad=str(meta.get("especialidad") or "medicina general"),
        nombre_medico=str(meta.get("nombre_medico") or "el médico de turno"),
        sucursal=str(meta.get("sucursal") or "sucursal Centro"),
        max_dias=max_dias,
        timezone=tz,
        fecha_limite=limite,
        fecha_turno=fecha_turno,
        fecha_turno_spoken=spoken_date(fecha_turno),
        hora_turno=hora_turno,
        hora_turno_spoken=hora_spoken,
        franja_turno=franja,
        current_node_id=str(flow["flow_graph"]["start"]),
        phase="identity",
        flow_key=resolved_key,
    )
    session.variables["saludo_por_horario"] = spoken_greeting(tz)
    _hydrate_call_variables(session, meta)
    vars_ = session.as_template_vars()
    session.knowledge_base = [
        {
            "question": item.get("question", ""),
            "answer": render_template(str(item.get("answer", "")), vars_),
        }
        for item in kb
    ]
    return session, flow


_HYDRATE_SKIP = frozenset({"knowledge_base", "knowledge_base_questions"})


def _hydrate_call_variables(session: CallSession, meta: dict[str, Any]) -> None:
    """Copia la metadata de prueba (TEST_* / Redis / JSON) a session.variables."""
    enriched = apply_derived_fields(meta)
    for key, value in enriched.items():
        if key in _HYDRATE_SKIP or value is None:
            continue
        name = str(key)
        if name not in session.variables:
            session.variables[name] = value
    session.variables.setdefault("nombre_deudor", session.nombre_deudor)
    session.variables.setdefault("nombre_deudor_completo", session.nombre_deudor)
    session.variables.setdefault("nombre_paciente", session.nombre_deudor)
    session.variables.setdefault("nombre_empresa", session.nombre_empresa)
    session.variables.setdefault("max_dias", session.max_dias)
