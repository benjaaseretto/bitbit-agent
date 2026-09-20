"""Tests del catálogo de flujos y registry de tasks."""
from __future__ import annotations

import pytest

from app.flow_graph.catalog import find_flow_graph_path, list_flow_spec_files
from app.tasks import COLLY_TASK_STUBS, TASK_REGISTRY, get_task_class, list_task_types


def test_catalog_lists_clinica_spec():
    files = list_flow_spec_files()
    assert any("clinica_vida" in p for p in files)
    path = find_flow_graph_path("clinica_vida_flow")
    assert path and path.endswith("clinica_vida_flow_graph.json")


def test_builtin_tasks_registered():
    types = list_task_types()
    assert "IdentityVerificationTask" in types
    assert "AppointmentSchedulingTask" in types
    assert "NegotiationTaskV2" in types
    assert "FormTask" in types
    assert "NextContactTask" in types
    assert "QuestionnaireTask" in types
    assert get_task_class("IdentityVerificationTask").task_type == "IdentityVerificationTask"
    assert get_task_class("NegotiationTaskV2").task_type == "NegotiationTaskV2"


def test_colly_stub_raises():
    assert "NegotiationTask" in COLLY_TASK_STUBS
    with pytest.raises(NotImplementedError, match="aún no portada"):
        get_task_class("NegotiationTask")


def test_unknown_task_raises():
    with pytest.raises(KeyError, match="Unknown task_type"):
        get_task_class("NoExisteTaskXYZ")


def test_registry_not_empty():
    assert len(TASK_REGISTRY) >= 2
