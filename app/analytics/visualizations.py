"""Builders de specs de visualización + validación estricta (whitelist).

Contrato de seguridad:
- El LLM NUNCA escribe la spec: las tools la construyen con estos builders a
  partir de métricas calculadas en código. El LLM solo elige período/params.
- `validate_visualization` rechaza tipos de gráfico desconocidos, claves
  extra, strings largos y valores no numéricos. El frontend además usa
  `textContent` (nunca innerHTML) para todo lo que viaja en la spec.
"""
from __future__ import annotations

import re
from typing import Any

_ALLOWED_CHARTS = {"line", "bar", "ring", "table", "kpi"}

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,48}$")


class VisualizationError(ValueError):
    pass


def _clean_text(value: Any, *, limit: int, field: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise VisualizationError(f"campo {field} vacío")
    if len(text) > limit:
        raise VisualizationError(f"campo {field} excede {limit} caracteres")
    return text


def _clean_number(value: Any, field: str) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        raise VisualizationError(f"campo {field} no es numérico") from None


def line_chart(
    *,
    id: str,
    title: str,
    x_label: str,
    unit: str,
    rows: list[dict[str, Any]],
    series: list[tuple[str, str]],  # (field, label)
) -> dict[str, Any]:
    """Gráfico de líneas: rows con date ISO + campos numéricos."""
    if not _SLUG_RE.match(str(id or "")):
        raise VisualizationError(f"id inválido: {id!r}")
    clean_rows = []
    for row in rows:
        clean = {"date": _clean_text(row.get("date"), limit=10, field="date")}
        for field, _label in series:
            clean[field] = _clean_number(row.get(field), field)
        clean_rows.append(clean)
    return {
        "id": str(id),
        "chart_type": "line",
        "title": _clean_text(title, limit=80, field="title"),
        "unit": _clean_text(unit, limit=10, field="unit"),
        "x": {"field": "date", "label": _clean_text(x_label, limit=40, field="x.label")},
        "series": [
            {"field": field, "label": _clean_text(label, limit=40, field="series.label")}
            for field, label in series
        ],
        "data": clean_rows,
    }


def bar_chart(
    *, id: str, title: str, unit: str, labels: list[str], values: list[float]
) -> dict[str, Any]:
    if not _SLUG_RE.match(str(id or "")):
        raise VisualizationError(f"id inválido: {id!r}")
    if not labels or len(labels) != len(values):
        raise VisualizationError("bar: labels y values deben emparejarse")
    return {
        "id": str(id),
        "chart_type": "bar",
        "title": _clean_text(title, limit=80, field="title"),
        "unit": _clean_text(unit, limit=10, field="unit"),
        "labels": [_clean_text(l, limit=40, field="label") for l in labels],
        "values": [_clean_number(v, "value") for v in values],
    }


def ring_chart(
    *, id: str, title: str, unit: str, labels: list[str], values: list[float]
) -> dict[str, Any]:
    spec = bar_chart(id=id, title=title, unit=unit, labels=labels, values=values)
    spec["chart_type"] = "ring"
    return spec


def table(
    *, id: str, title: str, headers: list[str], rows: list[list[Any]]
) -> dict[str, Any]:
    if not _SLUG_RE.match(str(id or "")):
        raise VisualizationError(f"id inválido: {id!r}")
    if not headers or not rows:
        raise VisualizationError("table: se requieren headers y rows")
    clean_rows = []
    for row in rows:
        if len(row) != len(headers):
            raise VisualizationError("table: fila con ancho distinto a headers")
        clean_rows.append(
            [
                _clean_number(cell, "cell")
                if isinstance(cell, (int, float))
                else _clean_text(cell, limit=60, field="cell")
                for cell in row
            ]
        )
    return {
        "id": str(id),
        "chart_type": "table",
        "title": _clean_text(title, limit=80, field="title"),
        "headers": [_clean_text(h, limit=40, field="header") for h in headers],
        "rows": clean_rows,
    }


def validate_visualization(spec: Any) -> dict[str, Any]:
    """Valida la spec contra la whitelist. Devuelve la spec saneada."""
    if not isinstance(spec, dict):
        raise VisualizationError("visualization debe ser un objeto")
    chart = spec.get("chart_type")
    if chart not in _ALLOWED_CHARTS:
        raise VisualizationError(f"chart_type no permitido: {chart!r}")
    if not _SLUG_RE.match(str(spec.get("id") or "")):
        raise VisualizationError(f"id inválido: {spec.get('id')!r}")
    _clean_text(spec.get("title"), limit=80, field="title")
    allowed_keys = {
        "line": {"id", "chart_type", "title", "unit", "x", "series", "data"},
        "bar": {"id", "chart_type", "title", "unit", "labels", "values"},
        "ring": {"id", "chart_type", "title", "unit", "labels", "values"},
        "table": {"id", "chart_type", "title", "headers", "rows"},
        "kpi": {"id", "chart_type", "title", "unit", "labels", "values"},
    }[chart]
    extra = set(spec) - allowed_keys
    if extra:
        raise VisualizationError(f"claves no permitidas para {chart}: {sorted(extra)}")
    if chart in ("bar", "ring"):
        values = spec.get("values")
        if not isinstance(values, list) or not values:
            raise VisualizationError(f"{chart}: values vacío")
        if len(values) > 24:
            raise VisualizationError(f"{chart}: máximo 24 valores")
    if chart == "line" and not (spec.get("data") or []):
        raise VisualizationError("line: data vacía")
    if chart == "table" and len(spec.get("rows") or []) > 20:
        raise VisualizationError("table: máximo 20 filas")
    return spec