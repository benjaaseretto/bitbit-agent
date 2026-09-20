# Flujos y tasks independientes

Este repo sigue el modelo de **colly** (un JSON por flujo + scripts de task),
pero el runtime es **Pipecat** (no LiveKit AgentTasks).

## Layout

```
app/flow_graph/specs/*.json              # todos los flujos (clínica, consultas, venta equipos)
app/kb/*.json                            # FAQ por flujo
app/kb/complex/*.json                    # KB de los flujos complejos
app/tasks/*.py                           # scripts de tools + prompt por dominio
app/orchestrator/                        # carga spec + swap de fase/tools
app/pipecat_runtime/bot.py               # pipeline de voz (no conoce el dominio)
```

Índice: `app/flow_graph/specs/INDEX.md` (25 consultas/sanatorio + 20 venta de equipos).
Regenerar: `python scripts/adapt_complex_flows.py --limit 45`.

## Flujo activo

Por defecto: `clinica_vida_flow` (`BITBIT_FLOW_KEY`).

Studio (front propio, no el `/client` de Pipecat): `http://localhost:7860/`

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
| `AppointmentSchedulingTask` | `app/tasks/appointment.py` | agenda / consultas |
| `NegotiationTaskV2` | `app/tasks/sales.py` | venta / pedido |
| `MultiProductNegotiationTask` | `app/tasks/sales.py` | venta multiproducto |
| `OfferSelectionTask` | `app/tasks/sales.py` | elección de plan |
| `NextContactTask` | `app/tasks/next_contact.py` | recontacto |
| `PaymentIntentionDateTask` | `app/tasks/next_contact.py` | fecha tentativa |
| `FormTask` | `app/tasks/form.py` | captura de campos |
| `QuestionnaireTask` | `app/tasks/questionnaire.py` | cuestionario |
| `FieldVerificationTask` | `app/tasks/extra_auth.py` | campo extra |
| `KBATask` | `app/tasks/extra_auth.py` | KBA |

El orquestador recorre `on`/`goto` del spec (say → task → final). Lo que quede en `app/tasks/stubs.py` con `status: stub` aún no está portado.

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
