# Flujos y tasks independientes

Este repo sigue el modelo de **colly** (un JSON por flujo + scripts de task),
pero el runtime es **Pipecat** (no LiveKit AgentTasks).

## Layout

```
app/flow_graph/specs/*.json              # flujos activos
app/flow_graph/demo_specs/complex/       # 45 flujos complejos (sanatorio / equipos)
app/kb/*.json                            # FAQ por flujo
app/kb/complex/*.json                    # KB de los flujos complejos
app/tasks/*.py                           # scripts de tools + prompt por dominio
app/orchestrator/                        # carga spec + swap de fase/tools
app/pipecat_runtime/bot.py               # pipeline de voz (no conoce el dominio)
```

Índice de los 45: `app/flow_graph/demo_specs/complex/INDEX.md`.
Regenerar: `python scripts/adapt_complex_flows.py --limit 45`.

## Flujo activo

Por defecto: `clinica_vida_flow` (`BITBIT_FLOW_KEY`).

```bash
BITBIT_FLOW_KEY=clinica_vida_flow python -m app.pipecat_runtime.bot --transport webrtc
```

Listar specs:

```python
from app.flow_graph.catalog import list_flow_spec_files, get_flow_catalog_metadata
for p in list_flow_spec_files():
    print(get_flow_catalog_metadata(p)["flow_key"], p)
```

## Crear un flujo nuevo

```bash
python scripts/new_flow.py mi_vertical --visible-name "Mi Vertical" --with-task
```

Genera:

1. `app/flow_graph/specs/mi_vertical_flow_graph.json`
2. `app/kb/mi_vertical.json`
3. (opcional) `app/tasks/mi_vertical.py` con `@register_task`

Cableá `task_type` del nodo del JSON al nombre de la clase registrada.

## Tasks built-in

| `task_type` | Módulo | Fase |
|-------------|--------|------|
| `IdentityVerificationTask` | `app/tasks/identity.py` | identity |
| `AppointmentSchedulingTask` | `app/tasks/appointment.py` | negotiation (agenda) |

El resto de tasks de colly están indexadas como stubs en `app/tasks/stubs.py`
(origen en `legacy-agent-voice`). Portá una a la vez: nuevo archivo +
`@register_task` + `ensure_builtin_tasks_loaded`.

## Contrato de una task

```python
@register_task
class MiTask(BaseTask):
    task_type = "MiTask"
    phase = "negotiation"
    tool_choice = "auto"

    def system_prompt(self) -> str: ...
    def tools(self) -> Sequence[Callable]:  # métodos async Pipecat
        return [self.mi_tool]
```

El `FlowController` elige la task según la fase y el `task_type` del nodo
en el spec; el bot solo hace `tools_for_phase` / `system_prompt`.
