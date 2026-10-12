"""Métricas de recupero: cálculo puro en código, sin LLM.

Definiciones (demo, documentadas en docs/INSIGHTS.md — en producción
reutilizar las fórmulas del negocio):

- recovered_total = suma de recovered_amount del período.
- pending_end = pending_balance del último día del período.
- recovery_pct = recovered_total / (recovered_total + pending_end) × 100
  (lo recuperado sobre lo recuperado + lo que quedaba pendiente al cierre).
- delta vs período anterior inmediato de la misma duración.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

PERIODS: tuple[str, ...] = (
    "este_mes",
    "mes_anterior",
    "ultima_semana",
    "ultimos_3_meses",
)

_PERIOD_LABELS = {
    "este_mes": "este mes",
    "mes_anterior": "el mes anterior",
    "ultima_semana": "la última semana",
    "ultimos_3_meses": "los últimos tres meses",
}


class UnknownPeriod(ValueError):
    pass


def period_label(periodo: str) -> str:
    return _PERIOD_LABELS.get(periodo, periodo)


def period_bounds(periodo: str, today: date) -> tuple[date, date]:
    """Rango [start, end] inclusive del período y del período previo."""
    if periodo == "este_mes":
        start = today.replace(day=1)
        prev_end = start - timedelta(days=1)
        return start, today, prev_end.replace(day=1), prev_end
    if periodo == "mes_anterior":
        prev_end = today.replace(day=1) - timedelta(days=1)
        prev_start = prev_end.replace(day=1)
        return (
            prev_start,
            prev_end,
            (prev_start - timedelta(days=31)).replace(day=1),
            prev_start - timedelta(days=1),
        )
    if periodo == "ultima_semana":
        start = today - timedelta(days=6)
        return start, today, start - timedelta(days=7), start - timedelta(days=1)
    if periodo == "ultimos_3_meses":
        start = today - timedelta(days=89)
        return start, today, start - timedelta(days=90), start - timedelta(days=1)
    raise UnknownPeriod(f"período desconocido: {periodo!r}")


def _slice(daily: list[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    out = []
    for row in daily:
        day = date.fromisoformat(str(row["date"]))
        if start <= day <= end:
            out.append(row)
    return out


def _period_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "recovered_total": 0.0,
            "pending_end": None,
            "best_day": None,
            "days_with_activity": 0,
        }
    recovered_total = round(sum(float(r["recovered_amount"]) for r in rows), 2)
    pending_end = round(float(rows[-1]["pending_balance"]), 2)
    best = max(rows, key=lambda r: float(r["recovered_amount"]))
    return {
        "recovered_total": recovered_total,
        "pending_end": pending_end,
        "best_day": {
            "date": str(best["date"]),
            "amount": round(float(best["recovered_amount"]), 2),
        },
        "days_with_activity": sum(1 for r in rows if float(r["recovered_amount"]) > 0),
    }


def _recovery_pct(recovered: float, pending_end: float | None) -> float | None:
    if pending_end is None:
        return None
    denom = recovered + pending_end
    if denom <= 0:
        return None
    return round(100.0 * recovered / denom, 1)


def recovery_summary(
    dataset: dict[str, Any], periodo: str, today: date
) -> dict[str, Any]:
    """Métricas del período + comparación con el período anterior."""
    if periodo not in PERIODS:
        raise UnknownPeriod(f"período desconocido: {periodo!r}")
    start, end, prev_start, prev_end = period_bounds(periodo, today)
    daily = dataset.get("daily") or []
    rows = _slice(daily, start, end)
    prev_rows = _slice(daily, prev_start, prev_end)

    current = _period_metrics(rows)
    previous = _period_metrics(prev_rows)
    pct = _recovery_pct(
        current["recovered_total"],
        current["pending_end"] if current["pending_end"] is not None else 0.0,
    )
    prev_pct = _recovery_pct(
        previous["recovered_total"],
        previous["pending_end"] if previous["pending_end"] is not None else 0.0,
    )
    delta = None
    if pct is not None and prev_pct is not None:
        delta = round(pct - prev_pct, 1)
    return {
        "period": periodo,
        "period_label": period_label(periodo),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": rows,
        "recovered_total": current["recovered_total"],
        "pending_end": current["pending_end"],
        "best_day": current["best_day"],
        "days_with_activity": current["days_with_activity"],
        "recovery_pct": pct,
        "previous": {
            "start": prev_start.isoformat(),
            "end": prev_end.isoformat(),
            "recovered_total": previous["recovered_total"],
            "recovery_pct": prev_pct,
        },
        "delta_pct": delta,
        "has_previous_data": bool(prev_rows),
    }


def distribution_by_status(debtors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Distribución de saldo pendiente por estado del deudor."""
    totals: dict[str, float] = {}
    for debtor in debtors:
        status = str(debtor.get("status") or "sin_estado")
        totals[status] = round(
            totals.get(status, 0.0) + float(debtor.get("pending_balance") or 0.0), 2
        )
    return [
        {"status": status, "pending_balance": amount}
        for status, amount in sorted(totals.items(), key=lambda kv: -kv[1])
    ]


def top_debtors(debtors: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    """Ranking de deudores por saldo pendiente (mayor primero)."""
    limit = max(1, min(int(limit), 20))
    ranked = sorted(
        debtors,
        key=lambda d: float(d.get("pending_balance") or 0.0),
        reverse=True,
    )[:limit]
    return [
        {
            "id": str(d.get("id") or ""),
            "name": str(d.get("name") or ""),
            "pending_balance": round(float(d.get("pending_balance") or 0.0), 2),
            "status": str(d.get("status") or "sin_estado"),
        }
        for d in ranked
    ]


def format_money(amount: float) -> str:
    """Formato hablado/friendly: $152,340 (sin decimales)."""
    return f"${amount:,.0f}"