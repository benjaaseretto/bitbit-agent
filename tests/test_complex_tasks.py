"""Tasks de flujos complejos (venta, formulario, grafo)."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.flow_graph.catalog import find_flow_graph_path, load_flow_wrapper
from app.orchestrator.controller import FlowController
from app.orchestrator.loader import build_session
from app.tasks.graph import negotiation_task_node
from app.tasks.registry import get_task_class
from app.utils.dates import today_in_tz


def _params():
    return SimpleNamespace(result_callback=AsyncMock())


@pytest.mark.asyncio
async def test_sales_flow_uses_negotiation_v2_not_appointment():
    session, flow = build_session(
        {
            "name": "Ana López",
            "company_name": "TecnoMédico Equipos",
            "flow_key": "tecno_medico_flow",
        }
    )
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    ctrl = FlowController(session, flow, speak=speak)
    node = negotiation_task_node(flow, session.current_node_id)
    assert flow["flow_graph"]["nodes"][node]["task_type"] == "NegotiationTaskV2"
    names = {fn.__name__ for fn in ctrl.tools_for_phase("negotiation")}
    assert "confirmar_pedido" in names
    assert "agendar_cita" not in names


@pytest.mark.asyncio
async def test_identity_advances_to_opening_on_andes_care():
    session, flow = build_session(
        {"name": "Juan Pérez", "company_name": "Andes Care", "flow_key": "andes_care_flow"}
    )
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    ctrl = FlowController(session, flow, speak=speak)
    params = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="sí soy yo"
    )
    assert session.phase == "negotiation"
    assert spoken
    assert session.final_status == "Entregado"


@pytest.mark.asyncio
async def test_form_registers_email_and_completes():
    session, flow = build_session({"flow_key": "andes_care_flow", "name": "Juan"})
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    ctrl = FlowController(session, flow, speak=speak)
    session.phase = "negotiation"
    session.current_node_id = "task.collect_email_condonacion"
    task = get_task_class("FormTask")(
        ctrl._make_ctx(), node_id="task.collect_email_condonacion"
    )
    params = _params()
    await task.registrar_email(params, nombre="email_cliente", email="juan@correo.com")
    assert session.variables["email_cliente"] == "juan@correo.com"
    await task.confirmar_campo(params, nombre="email_cliente")
    assert params.result_callback.await_args.args[0]["ok"] is True


@pytest.mark.asyncio
async def test_clinica_cita_still_closes():
    session, flow = build_session(
        {"name": "Juan Pérez", "company_name": "Clínica Vida", "flow_key": "clinica_vida_flow"}
    )
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    ctrl = FlowController(session, flow, speak=speak)
    params = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="sí soy yo"
    )
    assert session.phase == "negotiation"
    fecha = (today_in_tz(session.timezone) + timedelta(days=1)).isoformat()
    params2 = _params()
    await ctrl.agendar_cita(params2, fecha_iso=fecha)
    assert session.final_status == "Cita reagendada"
    assert session.phase == "done"


@pytest.mark.asyncio
async def test_aurora_identity_speaks_opening_not_placeholder():
    session, flow = build_session(
        {"name": "Juan Pérez", "flow_key": "aurora_salud_flow"}
    )
    assert session.nombre_empresa == "Sanatorio Aurora"
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    ctrl = FlowController(session, flow, speak=speak)
    params = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="si correcto"
    )
    assert session.phase == "negotiation"
    assert spoken
    blob = " ".join(spoken)
    assert "{saludo" not in blob
    assert "{" not in blob
    assert "Juan" in blob or "Ana" in blob


def test_complex_specs_are_in_specs_dir():
    path = find_flow_graph_path("aurora_salud_flow")
    assert path and path.endswith("aurora_salud_flow_graph.json")
    wrapper = load_flow_wrapper(path)
    assert wrapper["flow_catalog"]["meta"]["vertical"] == "sanatorio"


def _bioanalyze_meta(**overrides):
    data = {
        "name": "Carla Méndez",
        "company_name": "BioAnalyze",
        "flow_key": "bio_analyze_flow",
        "producto": "analizador hematológico XS-500",
        "cantidad": "2",
        "sucursal": "depósito Norte",
        "financiamiento": "contado o 6 cuotas",
        "total_balance": "18500",
        "due_balance": "18500",
        "amount": "18500",
        "due_date": "2026-05-22",
        "delinquency": "120",
        "max_discount_pct": "40",
        "min_pago_pct": "60",
        "max_dias": "15",
        "nombre_agente": "Ana",
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    "mora, expected",
    [
        ("50", "task.negotiation_sin_descuento"),
        ("120", "task.negotiation"),
        ("250", "task.negotiation"),
    ],
)
def test_bioanalyze_delinquency_picks_negotiation_node(mora, expected):
    session, flow = build_session(_bioanalyze_meta(delinquency=mora))
    assert negotiation_task_node(flow, session.current_node_id, session) == expected
    if mora == "250":
        from app.tasks.graph import identity_success_goto

        assert identity_success_goto(flow, session) == "intent.opening_tramo_9"


@pytest.mark.asyncio
async def test_bioanalyze_identity_opens_discount_negotiation():
    session, flow = build_session(_bioanalyze_meta(delinquency="120"))
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    ctrl = FlowController(session, flow, speak=speak)
    params = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="sí soy yo"
    )
    assert session.phase == "negotiation"
    assert session.current_node_id == "task.negotiation"
    blob = " ".join(spoken)
    assert "{" not in blob
    assert "Carla" in blob
    assert "BioAnalyze" in blob
    prompt = ctrl.negotiation_system_prompt()
    assert "{max_discount_pct}" not in prompt
    assert "40" in prompt
    assert "{monto_minimo_palabras}" not in prompt
    assert "once mil" in prompt.lower() or "11100" in prompt


def test_bioanalyze_opening_renders_spoken_balance():
    session, flow = build_session(_bioanalyze_meta())
    from app.orchestrator.loader import say_text

    text = say_text(flow, "intent.opening", session)
    assert "{total_balance_palabras}" not in text
    assert "dieciocho mil" in text.lower() or "18500" in text


@pytest.mark.asyncio
async def test_bioanalyze_discount_tool_speaks_authorized_phrase():
    session, flow = build_session(_bioanalyze_meta(delinquency="120"))
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    ctrl = FlowController(session, flow, speak=speak)
    await ctrl.registrar_resultado_identidad(
        _params(), resultado="titular_confirmado", evidencia="sí soy yo"
    )
    names = {fn.__name__ for fn in ctrl.tools_for_phase("negotiation")}
    assert "ofrecer_descuento" in names
    spoken.clear()
    task = ctrl._active
    await task.ofrecer_descuento(_params(), evidencia="no me alcanza")
    assert session.variables["descuento_ofrecido"] is True
    assert session.variables["substatus"] == "Pago parcial"
    blob = " ".join(spoken).lower()
    assert "40" in blob
    assert "once mil" in blob
    fecha = (today_in_tz(session.timezone) + timedelta(days=1)).isoformat()
    await task.confirmar_pedido(_params(), fecha_iso=fecha)
    assert session.variables["substatus"] == "Pago parcial"
    assert session.variables.get("payment_amount") == "11100"
