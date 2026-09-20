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
    session, flow = build_session({"name": "Juan Pérez", "company_name": "Clínica Vida"})
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
    assert session.final_status == "Cita agendada"
    assert session.phase == "done"


def test_complex_specs_are_in_specs_dir():
    path = find_flow_graph_path("aurora_salud_flow")
    assert path and path.endswith("aurora_salud_flow_graph.json")
    wrapper = load_flow_wrapper(path)
    assert wrapper["flow_catalog"]["meta"]["vertical"] == "sanatorio"
