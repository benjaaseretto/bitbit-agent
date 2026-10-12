"""Tests de la capa analytics: métricas, specs y contrato (casos 1, 4, 6, 7, 8)."""
from __future__ import annotations

from datetime import date

import pytest
from app.analytics.contract import ContractError, build_insight_message, validate_insight_message
from app.analytics.datasource import DataSourceError, get_data_source
from app.analytics.fixtures import build_demo_dataset
from app.analytics.metrics import (
    distribution_by_status,
    format_money,
    recovery_summary,
    top_debtors,
)
from app.analytics.visualizations import (
    VisualizationError,
    bar_chart,
    line_chart,
    table,
    validate_visualization,
)

TODAY = date(2026, 10, 12)


@pytest.fixture
def dataset():
    return build_demo_dataset(TODAY)


# ---------- fixtures / datasource ----------

def test_demo_dataset_covers_all_periods():
    data = build_demo_dataset(TODAY)
    assert len(data["daily"]) >= 120
    assert data["daily"][0]["date"] < data["daily"][-1]["date"]
    assert data["debtors"], "debe haber deudores demo"
    assert data["meta"]["source"] == "fixture-demo"


def test_unknown_data_source_rejected():
    # Caso "sin permisos/fuente no autorizada": solo fuentes registradas.
    with pytest.raises(DataSourceError):
        get_data_source("crm_real_inexistente")


# ---------- métricas ----------

def test_recovery_summary_sums_match_data(dataset):
    summary = recovery_summary(dataset, "este_mes", TODAY)
    expected = round(
        sum(
            float(row["recovered_amount"])
            for row in dataset["daily"]
            if row["date"].startswith("2026-10")
        ),
        2,
    )
    assert summary["recovered_total"] == expected
    assert summary["start"] == "2026-10-01"
    assert summary["end"] == TODAY.isoformat()
    assert summary["recovery_pct"] is not None
    assert 0 <= summary["recovery_pct"] <= 100


def test_recovery_summary_empty_period(dataset):
    empty = {"daily": [], "debtors": [], "portfolio": {}}
    summary = recovery_summary(empty, "este_mes", TODAY)
    assert summary["recovered_total"] == 0.0
    assert summary["days"] == []
    assert summary["best_day"] is None
    assert summary["has_previous_data"] is False


def test_comparison_uses_previous_period(dataset):
    summary = recovery_summary(dataset, "este_mes", TODAY)
    assert summary["has_previous_data"] is True
    assert summary["previous"]["start"] == "2026-09-01"
    assert summary["delta_pct"] is not None


def test_distribution_by_status_sums_pending(dataset):
    rows = distribution_by_status(dataset["debtors"])
    total = sum(r["pending_balance"] for r in rows)
    expected = round(sum(float(d["pending_balance"]) for d in dataset["debtors"]), 2)
    assert abs(total - expected) < 0.01
    assert rows == sorted(rows, key=lambda r: -r["pending_balance"])


def test_top_debtors_order_and_cap(dataset):
    top = top_debtors(dataset["debtors"], limit=5)
    assert len(top) == 5
    balances = [r["pending_balance"] for r in top]
    assert balances == sorted(balances, reverse=True)
    assert len(top_debtors(dataset["debtors"], limit=99)) == 20  # cap


def test_format_money():
    assert format_money(152340.55) == "$152,341"


# ---------- validación de specs (whitelist) ----------

def test_line_spec_valid(dataset):
    rows = [
        {"date": row["date"], "recovered_amount": row["recovered_amount"]}
        for row in dataset["daily"][-7:]
    ]
    spec = line_chart(
        id="recovery-trend",
        title="Recupero diario",
        x_label="Fecha",
        unit="MXN",
        rows=rows,
        series=[("recovered_amount", "Importe recuperado")],
    )
    assert validate_visualization(spec) == spec


def test_unknown_chart_type_rejected():
    with pytest.raises(VisualizationError):
        validate_visualization({"id": "x", "chart_type": "3d-xml", "title": "t"})


def test_extra_keys_rejected_no_model_injection():
    # Caso 8: un campo extra (p.ej. "onclick") no puede colarse en la spec.
    spec = bar_chart(id="c", title="t", unit="MXN", labels=["a"], values=[1])
    injected = {**spec, "onclick": "alert(1)", "template": "{{evil}}"}
    with pytest.raises(VisualizationError):
        validate_visualization(injected)


def test_overlong_and_non_numeric_rejected():
    with pytest.raises(VisualizationError):
        line_chart(
            id="ok-id",
            title="x" * 200,
            x_label="F",
            unit="MXN",
            rows=[{"date": "2026-10-01", "v": 1}],
            series=[("v", "V")],
        )
    with pytest.raises(VisualizationError):
        bar_chart(id="ok-id", title="t", unit="MXN", labels=["a"], values=["no-num"])


def test_table_requires_matching_widths():
    with pytest.raises(VisualizationError):
        table(id="t", title="T", headers=["A", "B"], rows=[["solo"]])


# ---------- contrato bot → frontend ----------

def test_build_message_roundtrip():
    spec = bar_chart(id="c-1", title="Comparación", unit="MXN", labels=["a", "b"], values=[1, 2])
    msg = build_insight_message("Texto del agente.", spec)
    assert validate_insight_message(msg) == msg


def test_contract_rejects_unknown_type_and_keys():
    spec = bar_chart(id="c", title="t", unit="MXN", labels=["a"], values=[1])
    with pytest.raises(ContractError):
        validate_insight_message({"type": "html", "message": "x", "visualization": spec})
    with pytest.raises(ContractError):
        validate_insight_message(
            {"type": "visualization", "message": "x", "visualization": spec, "script": "alert(1)"}
        )
    with pytest.raises(ContractError):
        build_insight_message("", spec)


def test_contract_text_is_plain_data_not_code():
    # El mensaje puede contener HTML como TEXTO: el frontend lo pinta con
    # textContent (ver web/js/viz.js); el contrato no lo ejecuta ni lo permite
    # como clave estructural.
    spec = bar_chart(id="c", title="t", unit="MXN", labels=["a"], values=[1])
    msg = build_insight_message("<b>Recupero</b> & datos", spec)
    assert msg["message"] == "<b>Recupero</b> & datos"