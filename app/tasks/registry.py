"""Registry de task_type → clase."""
from __future__ import annotations

from typing import Dict, List, Type

from app.tasks.base import BaseTask
from app.tasks.stubs import COLLY_TASK_STUBS, stub_message

TASK_REGISTRY: Dict[str, Type[BaseTask]] = {}


def register_task(cls: Type[BaseTask]) -> Type[BaseTask]:
    name = getattr(cls, "task_type", None) or cls.__name__
    TASK_REGISTRY[name] = cls
    return cls


def get_task_class(task_type: str) -> Type[BaseTask]:
    if task_type in TASK_REGISTRY:
        return TASK_REGISTRY[task_type]
    if task_type in COLLY_TASK_STUBS:
        raise NotImplementedError(stub_message(task_type))
    raise KeyError(
        f"Unknown task_type '{task_type}'. "
        f"Registradas: {sorted(TASK_REGISTRY)}. "
        f"Stubs colly: {sorted(COLLY_TASK_STUBS)}."
    )


def list_task_types() -> List[str]:
    return sorted(TASK_REGISTRY.keys())


def ensure_builtin_tasks_loaded() -> None:
    """Importa scripts built-in para que se auto-registren."""
    from app.tasks import appointment as _appointment  # noqa: F401
    from app.tasks import extra_auth as _extra_auth  # noqa: F401
    from app.tasks import form as _form  # noqa: F401
    from app.tasks import identity as _identity  # noqa: F401
    from app.tasks import next_contact as _next_contact  # noqa: F401
    from app.tasks import questionnaire as _questionnaire  # noqa: F401
    from app.tasks import sales as _sales  # noqa: F401
