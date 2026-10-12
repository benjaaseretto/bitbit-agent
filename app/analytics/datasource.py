"""Data Access Layer para insights: interface controlada de solo lectura.

El LLM NUNCA accede directo a los datos: las tools de `app/tasks/insights.py`
pasan por esta capa, que valida entradas y devuelve dicts ya tipados.

Adapter demo: FixtureDataSource (dataset sintético, ver fixtures.py).
Adapter real (CRM/DB): implementar DataSource y registrarlo en
`get_data_source` vía INSIGHTS_DATA_SOURCE. La autorización por cliente
debe vivir ADENTRO del adapter (el frontend nunca envía identificadores
confiables; ver docs/INSIGHTS.md, sección seguridad).
"""
from __future__ import annotations

import os
from typing import Any, Protocol


class DataSourceError(RuntimeError):
    """La consulta a la fuente de datos falló."""


class DataSource(Protocol):
    """Fuente de datos de solo lectura para insights."""

    def snapshot(self) -> dict[str, Any]:
        """Devuelve {"daily": [...], "debtors": [...], "portfolio": {...}}."""


class FixtureDataSource:
    """Dataset sintético determinista (demo). No contiene datos reales."""

    def snapshot(self) -> dict[str, Any]:
        from app.analytics.fixtures import build_demo_dataset
        from app.utils.dates import today_in_tz

        return build_demo_dataset(today_in_tz("America/Mexico_City"))


_PROVIDERS: dict[str, type] = {
    # Adapter demo. Un adapter real se registra acá y se elige por env.
    "fixture": FixtureDataSource,
}


def insights_enabled() -> bool:
    """Feature flag: BITBIT_INSIGHTS=1 habilita tools y panel de datos."""
    return (os.getenv("BITBIT_INSIGHTS") or "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def get_data_source(name: str | None = None) -> DataSource:
    key = (name or os.getenv("INSIGHTS_DATA_SOURCE") or "fixture").strip().lower()
    provider = _PROVIDERS.get(key)
    if provider is None:
        raise DataSourceError(
            f"INSIGHTS_DATA_SOURCE={key!r} no registrado. "
            f"Disponibles: {sorted(_PROVIDERS)}."
        )
    return provider()