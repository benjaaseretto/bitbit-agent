#!/usr/bin/env python3
"""Scaffold de un flujo independiente (spec + KB + task stub opcional).

Uso:
  python scripts/new_flow.py mi_flujo --visible-name "Mi flujo" --with-task

Después:
  1. Editá app/flow_graph/specs/<key>_flow_graph.json
  2. Editá app/kb/<key>.json
  3. Si usaste --with-task: implementá app/tasks/<key>.py y @register_task
  4. BITBIT_FLOW_KEY=<platform_flow_key> python -m app.pipecat_runtime.bot
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = ROOT / "app" / "flow_graph" / "specs"
KB = ROOT / "app" / "kb"
TASKS = ROOT / "app" / "tasks"


def _slug(raw: str) -> str:
    s = re.sub(r"[^a-z0-9_]+", "_", raw.strip().lower())
    return s.strip("_") or "nuevo_flujo"


def _spec_template(flow_key: str, visible: str, kb_file: str) -> dict:
    return {
        "flow_catalog": {
            "platform_flow_key": f"{flow_key}_flow",
            "visible_name": visible,
            "flow_type": "test",
            "enabled": True,
            "description": f"Flujo {visible}: identidad + fase de negocio.",
            "fields": [
                {
                    "label": "Nombre del contacto",
                    "field": "name",
                    "type": "text",
                    "required": True,
                },
                {
                    "label": "Nombre de la empresa",
                    "field": "company_name",
                    "type": "text",
                    "required": True,
                },
            ],
            "knowledge_base": {
                "file": kb_file,
                "company_id": f"{flow_key}-demo",
                "description": f"FAQ de {visible}.",
            },
            "company_id": f"{flow_key}-demo",
        },
        "flow_config": {"company_pronunciation": visible},
        "flow_graph": {
            "version": "1.0",
            "start": "task.identity_verification",
            "nodes": {
                "task.identity_verification": {
                    "type": "task",
                    "label": "Verificar identidad",
                    "task_type": "IdentityVerificationTask",
                    "params": {
                        "max_retries": 2,
                        "identity_identificacion_breve": (
                            "Hola, buen día. Mi nombre es {nombre_agente}, "
                            "le hablo de {nombre_empresa}."
                        ),
                    },
                    "on": {
                        "Entregado": {
                            "action": "set_status",
                            "status": "Entregado",
                            "goto": "intent.opening",
                            "express_route": True,
                            "express_route_next": "task.negotiation",
                        },
                        "Equivocado": {
                            "action": "set_status",
                            "status": "Equivocado",
                            "goto": "final.end_wrong",
                        },
                        "Recado conocido": {
                            "action": "set_status",
                            "status": "Recado conocido",
                            "goto": "final.end_recado",
                        },
                        "Buzon de Voz": {
                            "action": "set_status",
                            "status": "Buzon de Voz",
                            "goto": "final.end_mailbox",
                        },
                    },
                },
                "intent.opening": {
                    "type": "intention",
                    "label": "Apertura",
                    "prompt": (
                        "Gracias. Le llamo de {nombre_empresa} para continuar "
                        "con su gestión."
                    ),
                    "on": {"always": {"goto": "task.negotiation"}},
                },
                "task.negotiation": {
                    "type": "task",
                    "label": "Fase de negocio",
                    "task_type": "AppointmentSchedulingTask",
                    "params": {
                        "max_attempts": 3,
                        "custom_instructions": "",
                        "invalid_date_message": (
                            "Esa fecha no está disponible. ¿Puede ser hasta "
                            "el {fecha_limite}?"
                        ),
                        "invalid_date_retry_message": (
                            "Necesito una fecha dentro del plazo, hasta el "
                            "{fecha_limite}."
                        ),
                    },
                    "on": {
                        "Cita agendada": {
                            "action": "set_status",
                            "status": "Cita agendada",
                            "goto": "final.end_commitment",
                        }
                    },
                },
                "intent.confirm_commitment": {
                    "type": "intention",
                    "label": "Confirmar",
                    "prompt": "Perfecto, quedó agendado para el {commitment_date_spoken}.",
                },
                "intent.soft_close_no_commitment": {
                    "type": "intention",
                    "label": "Cierre suave",
                    "prompt": "Entiendo. Quedamos atentos cuando quiera retomar.",
                },
                "final.end_commitment": {
                    "type": "final",
                    "label": "Fin OK",
                    "prompt": "Que tenga buen día.",
                },
                "final.end_no_commitment": {
                    "type": "final",
                    "label": "Fin sin cita",
                    "prompt": "Gracias por su tiempo. Hasta luego.",
                },
                "final.end_paid": {
                    "type": "final",
                    "label": "Ya tenía",
                    "prompt": "Perfecto, entonces ya está en orden. Hasta luego.",
                },
                "final.end_intencion_de_pago": {
                    "type": "final",
                    "label": "Reagendar",
                    "prompt": "De acuerdo, lo contactamos en otro momento. Hasta luego.",
                },
                "final.end_wrong": {
                    "type": "final",
                    "label": "Equivocado",
                    "prompt": "Disculpe la molestia. Hasta luego.",
                },
                "final.end_recado": {
                    "type": "final",
                    "label": "Recado",
                    "prompt": "Le agradezco. Por favor coméntele que lo buscamos. Hasta luego.",
                },
                "final.end_mailbox": {
                    "type": "final",
                    "label": "Buzón",
                    "prompt": "Dejo el recado. Hasta luego.",
                },
            },
        },
    }


def _kb_template(visible: str) -> list:
    return [
        {
            "question": "horario | horarios | abren",
            "answer": f"El horario de atención de {visible} es de lunes a viernes.",
        },
        {
            "question": "dirección | donde | ubicación",
            "answer": f"La dirección de {visible} está en el centro. ¿Agendamos?",
        },
    ]


def _task_stub(module_name: str, class_name: str) -> str:
    return '''"""Task stub para {class_name} — completar tools + prompt."""
from __future__ import annotations

from typing import Any, Callable, Sequence

from app.tasks.base import BaseTask, TaskContext
from app.tasks.registry import register_task


@register_task
class {class_name}(BaseTask):
    task_type = "{class_name}"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.negotiation") -> None:
        super().__init__(ctx)
        self.node_id = node_id

    def system_prompt(self) -> str:
        return (
            f"Sos {{self.session.nombre_agente}} de {{self.session.nombre_empresa}}. "
            "Implementá la lógica de negocio de este script."
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        # TODO: devolver métodos async con firma Pipecat (params, ...)
        return []
'''.format(class_name=class_name)


def main() -> int:
    parser = argparse.ArgumentParser(description="Scaffold flujo independiente")
    parser.add_argument("name", help="slug del flujo (ej. clinica_norte)")
    parser.add_argument("--visible-name", default=None, help="Nombre visible")
    parser.add_argument(
        "--with-task",
        action="store_true",
        help="Crear stub de task en app/tasks/",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Escribir en demo_specs/ en lugar de specs/",
    )
    args = parser.parse_args()

    slug = _slug(args.name)
    visible = args.visible_name or slug.replace("_", " ").title()
    kb_file = f"{slug}.json"
    specs_dir = ROOT / "app" / "flow_graph" / ("demo_specs" if args.demo else "specs")
    specs_dir.mkdir(parents=True, exist_ok=True)
    KB.mkdir(parents=True, exist_ok=True)

    spec_path = specs_dir / f"{slug}_flow_graph.json"
    kb_path = KB / kb_file

    if spec_path.exists():
        print(f"Ya existe {spec_path}", file=sys.stderr)
        return 1

    spec_path.write_text(
        json.dumps(_spec_template(slug, visible, kb_file), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    if not kb_path.exists():
        kb_path.write_text(
            json.dumps(_kb_template(visible), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    task_path = None
    if args.with_task:
        class_name = "".join(p.title() for p in slug.split("_")) + "Task"
        task_path = TASKS / f"{slug}.py"
        if task_path.exists():
            print(f"Task ya existe {task_path} (spec/KB creados igual)", file=sys.stderr)
        else:
            task_path.write_text(_task_stub(slug, class_name), encoding="utf-8")
            # Asegurar import en registry loader
            reg = ROOT / "app" / "tasks" / "registry.py"
            marker = "def ensure_builtin_tasks_loaded"
            text = reg.read_text(encoding="utf-8")
            if f"tasks.{slug}" not in text and marker in text:
                insert = (
                    f'    from app.tasks import {slug} as _{slug}  # noqa: F401\n'
                )
                text = text.replace(
                    "def ensure_builtin_tasks_loaded() -> None:\n"
                    '    """Importa scripts built-in para que se auto-registren."""\n'
                    "    from app.tasks import appointment as _appointment  # noqa: F401\n"
                    "    from app.tasks import identity as _identity  # noqa: F401\n",
                    "def ensure_builtin_tasks_loaded() -> None:\n"
                    '    """Importa scripts built-in para que se auto-registren."""\n'
                    "    from app.tasks import appointment as _appointment  # noqa: F401\n"
                    "    from app.tasks import identity as _identity  # noqa: F401\n"
                    f"{insert}",
                )
                reg.write_text(text, encoding="utf-8")

    print(f"Spec: {spec_path.relative_to(ROOT)}")
    print(f"KB:   {kb_path.relative_to(ROOT)}")
    if task_path and task_path.exists():
        print(f"Task: {task_path.relative_to(ROOT)}")
    print(f"Run:  BITBIT_FLOW_KEY={slug}_flow python -m app.pipecat_runtime.bot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
