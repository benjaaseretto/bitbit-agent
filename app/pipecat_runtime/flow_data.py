"""Carga del flujo bitbit + utilidades de plantillas/fechas (Pipecat)."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from num2words import num2words

from app.pipecat_runtime.session import BitbitSession

APP_DIR = Path(__file__).resolve().parents[1]
SPEC_PATH = APP_DIR / "flow_graph" / "specs" / "bitbit_flow_graph.json"
KB_PATH = APP_DIR / "kb" / "bitbit.json"


def render_template(text: str, variables: dict[str, Any]) -> str:
    out = text
    for key, value in variables.items():
        out = out.replace("{" + str(key) + "}", str(value))
    return out


def today_in_tz(tz_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return datetime.now(ZoneInfo("UTC")).date()


def parse_iso_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except Exception:
        return None


def spoken_date(iso: str) -> str:
    d = parse_iso_date(iso)
    if d is None:
        return iso
    months = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    return f"{d.day} de {months[d.month - 1]}"


def resolve_relative_fecha(raw: str, *, timezone: str) -> str:
    """Map spoken Spanish relatives to ISO AAAA-MM-DD; pass through ISO/other."""
    s = " ".join(str(raw or "").strip().lower().split())
    if not s:
        return raw
    today = today_in_tz(timezone)
    relatives = {
        "hoy": 0,
        "today": 0,
        "mañana": 1,
        "manana": 1,
        "tomorrow": 1,
        "pasado mañana": 2,
        "pasado manana": 2,
        "mañana mismo": 1,
        "manana mismo": 1,
    }
    if s in relatives:
        return (today + timedelta(days=relatives[s])).isoformat()
    # Soft match: "puede ser mañana", "que mañana podría ser"
    if "pasado mañana" in s or "pasado manana" in s:
        return (today + timedelta(days=2)).isoformat()
    if "mañana" in s or "manana" in s:
        return (today + timedelta(days=1)).isoformat()
    if s == "hoy" or s.startswith("hoy "):
        return today.isoformat()
    iso = parse_iso_date(raw)
    return iso.isoformat() if iso else raw


def validate_commitment_date(
    raw: str, *, timezone: str, max_dias: int
) -> tuple[bool, Optional[str], str]:
    resolved = resolve_relative_fecha(raw, timezone=timezone)
    target = parse_iso_date(resolved)
    human = raw
    if target is None:
        return False, None, human
    start = today_in_tz(timezone)
    end = start + timedelta(days=max(0, int(max_dias)))
    human = target.strftime("%d/%m/%Y")
    if start <= target <= end:
        return True, target.isoformat(), human
    return False, None, human


def amount_to_words(amount: float, lang: str = "es") -> str:
    try:
        whole = int(round(float(amount)))
        return num2words(whole, lang=lang)
    except Exception:
        return str(amount)


def load_flow_spec() -> dict[str, Any]:
    with SPEC_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_kb() -> list[dict[str, Any]]:
    if not KB_PATH.exists():
        return []
    with KB_PATH.open(encoding="utf-8") as fh:
        data = json.load(fh)
    return data if isinstance(data, list) else []


def build_session(metadata: Optional[dict[str, Any]] = None) -> tuple[BitbitSession, dict[str, Any]]:
    meta = dict(metadata or {})
    flow = load_flow_spec()
    kb = load_kb()
    tz = str(meta.get("timezone") or "America/Mexico_City")
    due_date = str(meta.get("due_date") or "")
    if not due_date:
        due_date = today_in_tz(tz).isoformat()
    due_balance = float(meta.get("due_balance") or meta.get("amount") or 1500)
    max_dias = int(meta.get("max_dias") or 7)
    d = parse_iso_date(due_date)
    dias = max(0, (today_in_tz(tz) - d).days) if d else 0
    limite = (today_in_tz(tz) + timedelta(days=max_dias)).isoformat()

    session = BitbitSession(
        call_id=str(meta.get("id") or uuid.uuid4().hex[:12]),
        nombre_agente=str(meta.get("nombre_agente") or "Ana"),
        nombre_deudor=str(meta.get("name") or meta.get("nombre_deudor") or "Cliente"),
        nombre_empresa=str(meta.get("company_name") or "Bitbit"),
        amount=float(meta.get("amount") or due_balance),
        due_balance=due_balance,
        due_date=due_date,
        dias_mora=dias,
        max_dias=max_dias,
        timezone=tz,
        monto_deuda_palabras=amount_to_words(due_balance),
        fecha_limite=limite,
        current_node_id=str(flow["flow_graph"]["start"]),
        phase="identity",
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


def node(flow: dict[str, Any], node_id: str) -> dict[str, Any]:
    return flow["flow_graph"]["nodes"][node_id]


def say_text(flow: dict[str, Any], node_id: str, session: BitbitSession) -> str:
    n = node(flow, node_id)
    return render_template(str(n.get("prompt") or ""), session.as_template_vars())
