from __future__ import annotations

import json

from app.orchestrator.loader import build_session
from app.utils.call_metadata import apply_test_env_overrides, load_call_metadata


def test_test_env_overrides_name(monkeypatch):
    monkeypatch.setenv("TEST_NAME", "Lucía Gómez")
    monkeypatch.setenv("TEST_TOTAL_BALANCE", "1500")
    data = apply_test_env_overrides({"name": "Juan Pérez"})
    from app.utils.call_metadata import apply_derived_fields

    data = apply_derived_fields(data)
    assert data["name"] == "Lucía Gómez"
    assert data["total_balance_palabras"]


def test_load_call_metadata_json_then_env(monkeypatch, tmp_path):
    preset = tmp_path / "call.json"
    preset.write_text(json.dumps({"name": "Preset", "company_name": "Clínica Vida"}), encoding="utf-8")
    monkeypatch.setenv("BITBIT_METADATA_FILE", str(preset))
    monkeypatch.setenv("TEST_METADATA_SOURCE", "json")
    monkeypatch.setenv("TEST_NAME", "Ana Test")
    monkeypatch.setenv("TEST_DIM_5", "PROXIMO CONTACTO")
    data = load_call_metadata()
    assert data["name"] == "Ana Test"
    assert data["dim_5"] == "PROXIMO CONTACTO"
    assert data["nombre_deudor_completo"] == "Ana Test"


def test_build_session_hydrates_test_variables(monkeypatch):
    monkeypatch.setenv("TEST_NAME", "Juan Pérez")
    monkeypatch.setenv("TEST_DIM_5", "agenda")
    monkeypatch.setenv("TEST_DUE_BALANCE", "2500")
    meta = load_call_metadata()
    session, _flow = build_session(meta)
    assert session.variables["dim_5"] == "agenda"
    assert session.variables["due_balance_palabras"]
    assert session.as_template_vars()["nombre_deudor_completo"] == "Juan Pérez"


def test_env_source_does_not_require_json(monkeypatch):
    monkeypatch.setenv("TEST_METADATA_SOURCE", "env")
    monkeypatch.setenv("TEST_NAME", "Solo Env")
    monkeypatch.delenv("BITBIT_METADATA_FILE", raising=False)
    data = load_call_metadata()
    assert data["name"] == "Solo Env"
    assert data["company_name"]


def test_generic_test_env_maps_snake_case(monkeypatch):
    monkeypatch.setenv("TEST_PRODUCTO", "analizador hematológico XS-500")
    monkeypatch.setenv("TEST_MAX_DISCOUNT_PCT", "40")
    monkeypatch.setenv("TEST_MIN_PAGO_PCT", "60")
    from app.utils.call_metadata import apply_derived_fields

    data = apply_derived_fields(
        apply_test_env_overrides({"name": "Carla Méndez", "total_balance": "18500"})
    )
    assert data["producto"] == "analizador hematológico XS-500"
    assert data["max_discount_pct"] == "40"
    assert data["monto_minimo"] == "11100"
    assert data["monto_minimo_palabras"]
    assert data["total_balance_palabras"]
    assert data["especialidad"] == "analizador hematológico XS-500"


def test_bio_analyze_preset_hydrates_discount_path(monkeypatch):
    monkeypatch.setenv("BITBIT_METADATA_FILE", "presets/bio_analyze_call.json")
    monkeypatch.setenv("TEST_METADATA_SOURCE", "json")
    monkeypatch.delenv("TEST_NAME", raising=False)
    monkeypatch.setenv("TEST_DELINQUENCY", "120")
    data = load_call_metadata()
    session, flow = build_session(data)
    assert flow["flow_catalog"]["platform_flow_key"] == "bio_analyze_flow"
    assert session.variables["delinquency"] == "120"
    assert session.variables["producto"]
    assert session.variables["monto_minimo"] == "11100"
    assert session.as_template_vars()["total_balance_palabras"]
    assert session.nombre_empresa == "BioAnalyze"


def test_redis_source_without_client_falls_back(monkeypatch, tmp_path):
    preset = tmp_path / "call.json"
    preset.write_text(json.dumps({"name": "Fallback"}), encoding="utf-8")
    monkeypatch.setenv("BITBIT_METADATA_FILE", str(preset))
    monkeypatch.setenv("TEST_METADATA_SOURCE", "redis")
    monkeypatch.delenv("TEST_REDIS_URL", raising=False)
    monkeypatch.delenv("CLIENT_REDIS_URL", raising=False)
    monkeypatch.delenv("TEST_REDIS_HOST", raising=False)
    monkeypatch.delenv("CLIENT_REDIS_HOST", raising=False)
    monkeypatch.delenv("TEST_NAME", raising=False)
    monkeypatch.delenv("TEST_FLOW_KEY", raising=False)
    data = load_call_metadata()
    assert data["name"] == "Fallback"
