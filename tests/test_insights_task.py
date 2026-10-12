"""Tests de DataInsightsTask end-to-end con fixture (casos 1, 2, 3, 4, 5, 8, 9-12).

9-12 (turnos, reserva tras confirmación, continuidad de voz, compatibilidad)
están cubiertos por la suite original: test_bitbit_agent.py y
test_complex_tasks.py ejercitan el flujo de citas sin insights.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from app.analytics.datasource import DataSourceError
from app.pipecat_runtime.flow_data import build_session
from app.pipecat_runtime.tools import FlowController


def _params():
    cb = AsyncMock()
    return SimpleNamespace(result_callback=cb), cb


def _controller(meta=None, emit=None):
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    session, flow = build_session(
        meta
        or {
            "name": "Juan Pérez",
            "company_name": "Clínica Vida",
            # Pin explícito: .env del repo puede traer BITBIT_FLOW_KEY distinto
            # y load_dotenv en otros tests contamina os.environ.
            "flow_key": "clinica_vida_flow",
        }
    )
    ctrl = FlowController(session, flow, speak=speak, emit=emit)
    return ctrl, session, spoken


# ---------- 1: flag apagado → agente original intacto ----------

def test_insights_disabled_by_default(monkeypatch):
    monkeypatch.delenv("BITBIT_INSIGHTS", raising=False)
    ctrl, _session, _spoken = _controller()
    names = [fn.__name__ for fn in ctrl.tools_for_phase("negotiation")]
    assert "consultar_recupero" not in names
    assert "CONSULTAS DE DATOS" not in ctrl.negotiation_system_prompt()


def test_insights_injected_with_env(monkeypatch):
    monkeypatch.setenv("BITBIT_INSIGHTS", "1")
    ctrl, _session, _spoken = _controller()
    names = {fn.__name__ for fn in ctrl.tools_for_phase("negotiation")}
    assert {"consultar_recupero", "comparar_periodos", "distribucion_deuda", "top_deudores"} <= names
    # Las tools de la fase original siguen presentes.
    assert "confirmar_asistencia" in names
    assert "CONSULTAS DE DATOS" in ctrl.negotiation_system_prompt()
    # En identity no se inyectan.
    identity_names = {fn.__name__ for fn in ctrl.tools_for_phase("identity")}
    assert "consultar_recupero" not in identity_names


@pytest.mark.asyncio
async def test_tool_works_without_emit_channel(monkeypatch):
    # Sin canal de visualización (emit=None): la tool igual habla el resumen.
    monkeypatch.setenv("BITBIT_INSIGHTS", "1")
    ctrl, _session, spoken = _controller(emit=None)
    task = ctrl._insights_task()
    assert task is not None
    assert await task.emit_visual({"type": "visualization"}) is False
    params, cb = _params()
    await task.consultar_recupero(params, periodo="este_mes")
    cb.assert_awaited()
    assert spoken and "$" in spoken[0]


# ---------- 2: consulta con gráfico, números reales del fixture ----------

@pytest.mark.asyncio
async def test_consultar_recupero_emits_and_speaks_real_numbers(monkeypatch):
    monkeypatch.setenv("BITBIT_INSIGHTS", "1")
    sent: list[dict] = []

    async def emit(payload: dict) -> None:
        sent.append(payload)

    ctrl, _session, spoken = _controller(emit=emit)
    task = ctrl._insights_task()
    params, cb = _params()

    await task.consultar_recupero(params, periodo="este_mes")

    cb.assert_awaited()
    assert sent, "debe enviar la visualización por el canal"
    message = sent[0]
    assert message["type"] == "visualization"
    spec = message["visualization"]
    assert spec["id"] == "recovery-trend"
    assert spec["chart_type"] == "line"
    assert spec["data"], "la serie debe traer datos del fixture"
    # Speech con números reales, no inventados: coincide con la métrica.
    metrics = cb.call_args[0][0]
    expected = metrics["recovered_total"]
    assert f"${expected:,.0f}" in " ".join(spoken)


# ---------- 3: seguimiento actualiza el mismo panel ----------

@pytest.mark.asyncio
async def test_followup_updates_same_visualization_id(monkeypatch):
    monkeypatch.setenv("BITBIT_INSIGHTS", "1")
    sent: list[dict] = []

    async def emit(payload: dict) -> None:
        sent.append(payload)

    ctrl, _session, _spoken = _controller(emit=emit)
    task = ctrl._insights_task()
    params, _cb = _params()

    await task.consultar_recupero(params, periodo="este_mes")
    params2, _cb2 = _params()
    await task.consultar_recupero(params2, periodo="ultima_semana")

    assert len(sent) == 2
    ids = [m["visualization"]["id"] for m in sent]
    assert ids == ["recovery-trend", "recovery-trend"]  # update in-place
    assert sent[0]["message"] != sent[1]["message"]
    assert sent[1]["visualization"]["data"][0]["date"] >= sent[0]["visualization"]["data"][0]["date"]


# ---------- 4: resultados vacíos ----------

@pytest.mark.asyncio
async def test_empty_dataset_says_so_without_inventing(monkeypatch):
    monkeypatch.setenv("BITBIT_INSIGHTS", "1")
    ctrl, _session, spoken = _controller(emit=None)
    task = ctrl._insights_task()
    params, cb = _params()

    empty = {"daily": [], "debtors": [], "portfolio": {}}

    async def fake_snapshot():
        return empty

    with patch.object(type(task), "_dataset", lambda self: empty):
        await task.consultar_recupero(params, periodo="este_mes")

    cb.assert_awaited()
    result = cb.call_args[0][0]
    assert result.get("empty") is True
    assert any("No hay datos" in s for s in spoken)


# ---------- 5: error de acceso a datos ----------

@pytest.mark.asyncio
async def test_datasource_error_reports_and_continues(monkeypatch):
    monkeypatch.setenv("BITBIT_INSIGHTS", "1")
    ctrl, _session, spoken = _controller()
    task = ctrl._insights_task()
    params, cb = _params()

    def broken(self):
        raise DataSourceError("crm caído")

    with patch.object(type(task), "_dataset", broken):
        await task.consultar_recupero(params, periodo="este_mes")

    cb.assert_awaited()
    assert cb.call_args[0][0]["ok"] is False
    assert any("No pude consultar" in s for s in spoken)


# ---------- 8 (backend): el LLM nunca escribe la spec ----------

@pytest.mark.asyncio
async def test_invalid_spec_never_reaches_channel(monkeypatch):
    """El LLM jamás escribe la spec; y una spec rota no llega al canal."""
    monkeypatch.setenv("BITBIT_INSIGHTS", "1")
    sent: list[dict] = []

    async def emit(payload: dict) -> None:
        sent.append(payload)

    ctrl, _session, _spoken = _controller(emit=emit)
    task = ctrl._insights_task()

    ok = await task._send_visualization(
        "mensaje",
        {
            "id": "recovery-trend",
            "chart_type": "line",
            "title": "Recupero",
            "data": [{"fecha": "2026-10-01", "importe": 1000.0}],
        },
    )
    broken = await task._send_visualization(
        "mensaje", {"id": "x", "chart_type": "wasm", "title": "inyección"}
    )
    assert ok is True and sent and sent[0]["type"] == "visualization"
    assert broken is False  # rechazada por el contrato, nunca emitida

    # El payload que SÍ viajó revalida contra el contrato (defensa en profundidad).
    from app.analytics.contract import validate_insight_message

    validate_insight_message(sent[0])