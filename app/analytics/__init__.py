"""Capa de insights: datasource, métricas, specs de visualización y contrato."""
from app.analytics.contract import ContractError, build_insight_message, validate_insight_message
from app.analytics.datasource import (
    DataSource,
    DataSourceError,
    FixtureDataSource,
    get_data_source,
    insights_enabled,
)
from app.analytics.metrics import UnknownPeriod, recovery_summary
from app.analytics.visualizations import VisualizationError, validate_visualization

__all__ = [
    "ContractError",
    "DataSource",
    "DataSourceError",
    "FixtureDataSource",
    "UnknownPeriod",
    "VisualizationError",
    "build_insight_message",
    "get_data_source",
    "insights_enabled",
    "recovery_summary",
    "validate_insight_message",
    "validate_visualization",
]