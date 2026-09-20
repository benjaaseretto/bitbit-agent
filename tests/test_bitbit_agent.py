from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.pipecat_runtime.flow_data import (
    KB_PATH,
    SPEC_PATH,
    build_session,
    resolve_relative_fecha,
    today_in_tz,
    validate_commitment_date,
)
from app.pipecat_runtime.tools import FlowController


ROOT = Path(__file__).resolve().parents[1]


def test_clinica_spec_shape():
    assert SPEC_PATH.exists()
    data = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    assert data["flow_catalog"]["platform_flow_key"] == "clinica_vida_flow"
    assert data["flow_catalog"]["visible_name"] == "clinica_vida"
    graph = data["flow_graph"]
    assert graph["start"] == "task.identity_verification"
    assert graph["nodes"]["task.negotiation"]["task_type"] == "AppointmentSchedulingTask"
    assert "consulta" in graph["nodes"]["intent.opening"]["prompt"].lower()


def test_clinica_kb_exists():
    assert KB_PATH.exists()
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    assert isinstance(kb, list) and len(kb) >= 5


def test_build_session_from_preset():
    preset = ROOT / "presets" / "demo_call.json"
    meta = json.loads(preset.read_text(encoding="utf-8"))
    session, flow = build_session(meta)
    assert session.nombre_deudor == "Juan Pérez"
    assert session.nombre_empresa == "Clínica Vida"
    assert session.especialidad == "medicina general"
    assert flow["flow_graph"]["start"] == "task.identity_verification"
    assert len(session.knowledge_base) >= 5


def test_validate_date_window():
    tz = "America/Mexico_City"
    ok_date = (today_in_tz(tz) + timedelta(days=2)).isoformat()
    ok, iso, _ = validate_commitment_date(ok_date, timezone=tz, max_dias=7)
    assert ok and iso == ok_date
    bad = (today_in_tz(tz) + timedelta(days=40)).isoformat()
    ok2, iso2, _ = validate_commitment_date(bad, timezone=tz, max_dias=7)
    assert not ok2 and iso2 is None


def test_require_config_exits_without_key(monkeypatch):
    from app.pipecat_runtime import bot as bot_mod

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        bot_mod.require_config()
    assert exc.value.code == 1


def _controller(meta: dict | None = None):
    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    session, flow = build_session(
        meta or {"name": "Juan Pérez", "company_name": "Clínica Vida"}
    )
    ctrl = FlowController(session, flow, speak=speak)
    return ctrl, session, spoken


def _params():
    cb = AsyncMock()
    return SimpleNamespace(result_callback=cb), cb


@pytest.mark.asyncio
async def test_script_titular_ok():
    ctrl, session, spoken = _controller()
    params, cb = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="sí, soy yo"
    )
    assert session.final_status == "Entregado"
    assert session.phase == "negotiation"
    assert spoken
    cb.assert_awaited()


@pytest.mark.asyncio
async def test_script_persona_equivocada():
    ctrl, session, spoken = _controller()
    params, cb = _params()
    await ctrl.registrar_resultado_identidad(params, resultado="persona_equivocada")
    assert session.final_status == "Equivocado"
    assert session.phase == "done"
    assert spoken
    cb.assert_awaited()


@pytest.mark.asyncio
async def test_script_cita_fecha_valida():
    ctrl, session, _ = _controller({"name": "Juan", "max_dias": 7})
    params, cb = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="soy yo"
    )
    params2, cb2 = _params()
    fecha = (today_in_tz(session.timezone) + timedelta(days=2)).isoformat()
    await ctrl.agendar_cita(params2, fecha_iso=fecha)
    assert session.final_status == "Cita agendada"
    assert session.commitment_date == fecha
    assert session.phase == "done"
    cb2.assert_awaited()


@pytest.mark.asyncio
async def test_script_fecha_invalida():
    ctrl, session, spoken = _controller({"name": "Juan", "max_dias": 7})
    params, _ = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="soy yo"
    )
    spoken.clear()
    params2, cb2 = _params()
    bad = (today_in_tz(session.timezone) + timedelta(days=40)).isoformat()
    await ctrl.agendar_cita(params2, fecha_iso=bad)
    assert session.final_status == "Entregado"
    assert session.commitment_date is None
    assert session.negotiation_attempts == 1
    assert spoken
    cb2.assert_awaited()


@pytest.mark.asyncio
async def test_script_kb():
    ctrl, session, spoken = _controller()
    params, cb = _params()
    await ctrl.responder_kb(params, pregunta="¿Cuánto cuesta la consulta?")
    assert spoken
    assert any("costo" in s.lower() or "importe" in s.lower() or "seguro" in s.lower() for s in spoken)
    cb.assert_awaited()


@pytest.mark.asyncio
async def test_kb_blocks_filler_and_repeat():
    ctrl, session, spoken = _controller()
    params, cb = _params()
    await ctrl.responder_kb(params, pregunta="ok, entiendo")
    assert not spoken
    result = cb.await_args.args[0]
    assert result.get("skip_kb") is True

    params2, cb2 = _params()
    await ctrl.responder_kb(params2, pregunta="¿Dónde queda la clínica?")
    assert spoken
    spoken.clear()
    params3, cb3 = _params()
    await ctrl.responder_kb(params3, pregunta="¿Cuál es la dirección?")
    assert not spoken
    assert cb3.await_args.args[0].get("repeat_blocked") is True


def test_resolve_relative_fecha_manana():
    tz = "America/Mexico_City"
    expected = (today_in_tz(tz) + timedelta(days=1)).isoformat()
    assert resolve_relative_fecha("mañana", timezone=tz) == expected
    assert resolve_relative_fecha("puede ser mañana", timezone=tz) == expected
    ok, iso, _ = validate_commitment_date("mañana", timezone=tz, max_dias=7)
    assert ok and iso == expected


@pytest.mark.asyncio
async def test_cita_fecha_relativa():
    ctrl, session, _ = _controller({"name": "Juan", "max_dias": 7})
    params, _ = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="soy yo"
    )
    params2, cb2 = _params()
    await ctrl.agendar_cita(params2, fecha_iso="mañana")
    expected = (today_in_tz(session.timezone) + timedelta(days=1)).isoformat()
    assert session.final_status == "Cita agendada"
    assert session.commitment_date == expected
    assert session.phase == "done"
    cb2.assert_awaited()


@pytest.mark.asyncio
async def test_identidad_idempotente_tras_agenda():
    ctrl, session, spoken = _controller()
    params, _ = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="sí"
    )
    spoken.clear()
    params2, cb2 = _params()
    await ctrl.registrar_resultado_identidad(
        params2, resultado="titular_confirmado", evidencia="otra vez"
    )
    assert session.phase == "negotiation"
    assert not spoken
    result = cb2.await_args.args[0]
    assert result.get("already") is True


@pytest.mark.asyncio
async def test_agendar_bloqueado_en_identidad():
    ctrl, session, _ = _controller()
    params, cb = _params()
    await ctrl.agendar_cita(params, fecha_iso="2026-09-20")
    assert session.phase == "identity"
    result = cb.await_args.args[0]
    assert result.get("ok") is False


@pytest.mark.asyncio
async def test_on_phase_failure_no_rompe_identidad():
    async def bad_phase(_phase: str) -> None:
        raise AttributeError("DeepSeekLLMService object has no attribute set_settings")

    spoken: list[str] = []

    async def speak(text: str) -> None:
        spoken.append(text)

    session, flow = build_session({"name": "Juan"})
    ctrl = FlowController(session, flow, speak=speak, on_phase=bad_phase)
    params, cb = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="sí soy"
    )
    assert session.phase == "negotiation"
    assert session.final_status == "Entregado"
    assert spoken
    cb.assert_awaited()


@pytest.mark.asyncio
async def test_finalizar_no_sobrescribe_cita_cerrada():
    ctrl, session, spoken = _controller({"name": "Juan", "max_dias": 7})
    params, _ = _params()
    await ctrl.registrar_resultado_identidad(
        params, resultado="titular_confirmado", evidencia="sí"
    )
    fecha = (today_in_tz(session.timezone) + timedelta(days=1)).isoformat()
    params2, _ = _params()
    await ctrl.agendar_cita(params2, fecha_iso=fecha)
    assert session.final_status == "Cita agendada"
    assert session.phase == "done"
    spoken.clear()
    params3, cb3 = _params()
    await ctrl.finalizar(params3, resultado="sin_cita")
    assert session.final_status == "Cita agendada"
    assert session.commitment_date == fecha
    assert not spoken
    assert cb3.await_args.args[0].get("already") is True


def test_max_dias_cero_se_respeta():
    session, _ = build_session({"name": "Juan", "max_dias": 0})
    assert session.max_dias == 0
    assert session.fecha_limite == today_in_tz(session.timezone).isoformat()


def test_build_llm_deepseek_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    from app.pipecat_runtime.config import RuntimeConfig
    from app.pipecat_runtime.deepseek_llm import BitbitDeepSeekLLMService
    from app.pipecat_runtime.mac_bot import build_llm

    cfg = RuntimeConfig.from_env()
    assert cfg.llm_provider == "deepseek"
    llm = build_llm(cfg, "prompt de prueba")
    assert isinstance(llm, BitbitDeepSeekLLMService)