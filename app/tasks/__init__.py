"""Tasks Pipecat: protocolo, registry y scripts independientes por dominio."""

from app.tasks.registry import (
    TASK_REGISTRY,
    ensure_builtin_tasks_loaded,
    get_task_class,
    list_task_types,
    register_task,
)
from app.tasks.stubs import COLLY_TASK_STUBS

ensure_builtin_tasks_loaded()

__all__ = [
    "COLLY_TASK_STUBS",
    "TASK_REGISTRY",
    "get_task_class",
    "list_task_types",
    "register_task",
]
