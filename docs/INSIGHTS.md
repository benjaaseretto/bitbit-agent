# Insights: agente de voz con consultas de datos y visualizaciones

Extensión experimental del agente de voz (rama
`feature/voice-agent-interactive-visualizations`). El agente conversa por voz,
consulta datos autorizados mediante tools y muestra gráficos interactivos en
el Studio mientras sigue hablando.

**Estado**: demo funcional end-to-end con dataset sintético. No hay conexión a
un CRM real (ver [Fuente de datos real](#fuente-de-datos-real)).

---

## 1. Diagnóstico de la arquitectura existente

El repo ya tenía todas las piezas conversacionales; la extensión las reutiliza:

| Componente conceptual del brief | Equivalente en el repo |
|---|---|
| Voice Interface | Pipeline Pipecat (`bot.py` / `mac_bot.py`: transport → STT → LLM → TTS) |
| Conversation Manager | `FlowController` (`app/orchestrator/controller.py`) + fases identity→negotiation→done |
| Intent/Entity Extraction | Function calling del LLM sobre tools por fase (`LLMContext(tools=...)`) |
| Tool Router | Tasks con `@register_task` + registry (`app/tasks/*`, `registry.py`) |
| Customer Context | `CallSession` (`app/session/call_session.py`) |
| Observability | HUD + observers (`app/pipecat_runtime/hud.py`, `performance.py`) |
| Frontend | Studio (`web/`): WebRTC + data channel (`web/js/webrtc.js` → `onMessage`) |

Lo único faltante era: (a) una capa de datos/métricas, (b) un canal bot→frontend
para payloads estructurados (el HUD solo enviaba status/transcript/metrics) y
(c) un renderer de visualizaciones en el frontend.

## 2. La skill de la captura: `anatomy`

La captura (post de LinkedIn de Miguel Ángel Durán) muestra **`anatomy`**, una
skill de Claude Code que genera **ilustraciones isométricas interactivas**
(quizás didácticas de sistemas, "quiz of concept") como **sitios estáticos de
SVG editado a mano** — "hand-modularized parts", "thin connector labels",
"editable SVG", "no gradients", "1-5 canvas".

Verificado solo contra la captura (el link `lnkd.in/egbdqNet` no se abrió:
navegación a link acortado no autorizada en esta sesión).

**Decisión de integración.** `anatomy` es una skill de **autorchia en tiempo de
desarrollo** (un workflow de prompts que produce HTML/SSVG estático), no una
librería de runtime: no se puede invocar dentro de un bot de voz en producción
ni ejecutar su salida como código del frontend. La integración correcta es
**adoptar sus principios de craft en un renderer controlado**:

- SVG construido por código (`createElementNS`), editable, sin gradientes.
- Un detalle por nodo (un nodo por punto de dato, con `<title>` nativo).
- Etiquetas finas y precisas (ticks numéricos, leyenda mínima).
- Cero contenido "scroll-only" o decorativo: cada gráfico responde a una
  pregunta del usuario.

Para ilustraciones isométricas estáticas (ej. diagrama del pipeline), `anatomy`
se puede usar en desarrollo para generar el asset y commitearlo; el runtime
nunca ejecuta SVG/JS generado por el LLM.

## 3. Arquitectura implementada

```
Voz (Pipecat) ─┐
               ├─> LLM (DeepSeek) ── function call ──> DataInsightsTask (app/tasks/insights.py)
Texto (HUD)  ──┘                                            │
                                        ┌───────────────────┤
                                        ▼                   ▼
                            app/analytics/metrics.py   app/analytics/datasource.py
                            (cálculo puro, sin LLM)    (solo lectura, whitelist)
                                        │                   │
                                        ▼                   ▼
                            app/analytics/visualizations.py (builders + validación)
                                        │
                                        ▼
                            app/analytics/contract.py (mensaje tipado validado)
                                        │
                                        ▼
                            emit → OutputTransportMessageFrame → data channel WebRTC
                                        │
                                        ▼
                            web/js/viz.js (renderer SVG controlado, whitelist)
```

Puntos clave:

1. **El LLM nunca toca los datos ni la spec.** Solo elige tool + período. La
   métrica se calcula en Python, la spec la construyen builders con whitelist
   y el mensaje se valida dos veces (backend y frontend).
2. **La voz sigue siendo la interfaz principal.** Las tools hablan el resumen
   con los valores calculados (`run_llm=False`: sin segunda generación) y
   envían la visualización por el canal. Si el canal falla, la voz no se corta
   (`BaseTask.emit_visual` devuelve `False` y sigue el turno).
3. **Opt-in por env.** `BITBIT_INSIGHTS=1` inyecta las tools y el hint de
   prompt en fase negotiation (`FlowController._insights_task`). Default OFF:
   el agente original queda intacto (verificado por la suite).
4. **Preguntas de seguimiento comparten contexto**: "mostrame la última semana"
   vuelve a llamar `consultar_recupero(periodo="ultima_semana")` → la spec usa
   el mismo `id` (`recovery-trend`) → el panel actualiza in-place sin perder
   el historial de la conversación.

## 4. Contrato bot → frontend

```json
{
  "type": "visualization",
  "message": "Recupero este mes: $152,341 (2026-10-01 → 2026-10-12).",
  "visualization": {
    "id": "recovery-trend",
    "chart_type": "line",
    "title": "Recupero diario · este mes",
    "unit": "MXN",
    "x": {"field": "date", "label": "Fecha"},
    "series": [{"field": "recovered_amount", "label": "Importe recuperado"}],
    "data": [{"date": "2026-10-01", "recovered_amount": 51200.0}]
  }
}
```

- `chart_type` ∈ {`line`, `bar`, `ring`, `table`, `kpi`} (whitelist en backend
  y frontend).
- Claves extra, strings > límites y valores no numéricos → rechazados
  (`VisualizationError` / `ContractError`).
- `id` estable (`^[a-z0-9][a-z0-9_-]{0,48}$`) → update in-place del panel.
- Mensajes de estado: `{"type": "insight_status", "state": "querying"}` para
  loading (extendible).

## 5. Seguridad

| Riesgo | Mitigación |
|---|---|
| LLM inyecta código en el frontend | La spec la generan builders en código; validación de claves/valores; frontend usa `textContent`/`createElement`, nunca `innerHTML` ni `eval` |
| SQL injection | No hay SQL; el adapter real debe usar consultas parametrizadas y **solo lectura** |
| Acceso a datos de otro cliente | En demo no aplica (dataset sintético sin PII). En producción, la autorización vive DENTRO del `DataSource` (el identificador del frontend nunca es confiable) |
| Datos sensibles en logs | El resumen hablado viaja por TTS; los payloads del canal no se loguean |
| Operaciones sensibles | Las tools de insights son de solo lectura; el agendamiento real (caso B del brief) requeriría confirmación explícita antes de reservar — ver Limitaciones |

## 6. Fuente de datos real

`app/analytics/datasource.py` define el protocolo `DataSource` (solo lectura,
`snapshot() -> {daily, debtors, portfolio}`). Hoy está registrado solo
`fixture` (dataset sintético determinista de `fixtures.py`).

Para conectar un CRM/DB real:

1. Implementar `DataSource` con las mismas claves (el adapter puede traducir
   de las tablas del CRM a ese shape).
2. Registrarlo en `_PROVIDERS` y seleccionarlo con `INSIGHTS_DATA_SOURCE`.
3. La autorización por cliente/auth token se resuelve adentro del adapter.
4. **Reutilizar las fórmulas del negocio** para métricas (el `% de recupero`
   del demo está documentado en `metrics.py`; no es la fórmula oficial de
   ningún negocio).

## 7. Variables de entorno

| Variable | Default | Qué hace |
|---|---|---|
| `BITBIT_INSIGHTS` | `0` (off) | Habilita las tools de datos + hint de prompt + panel |
| `INSIGHTS_DATA_SOURCE` | `fixture` | Elige el `DataSource` registrado |

No se agregaron secretos ni dependencias nuevas (todo es stdlib + Pipecat ya
presente).

## 8. Cómo ejecutar

```bash
# Backend (Mac, con voz + panel):
BITBIT_INSIGHTS=1 python scripts/run_local.py

# Backend (OSS):
BITBIT_INSIGHTS=1 BITBIT_FLOW_KEY=clinica_vida_flow python -m app.pipecat_runtime.bot --transport webrtc

# Frontend: abrir el Studio (http://localhost:7860), iniciar llamada y
# preguntar por voz: "¿cómo viene mi recupero este mes?"
```

Sin `BITBIT_INSIGHTS=1`, el agente y el panel quedan exactamente como antes.

## 9. Pruebas

Ejecutadas: `pytest -q` → **118 passed** (24 nuevos en `tests/test_analytics.py`
y `tests/test_insights_task.py`), 1 failed preexistente ambiental
(`test_studio.py::test_bot_manager_start_reuses_running_child`, requiere GPU
Metal). Cobertura de los casos del brief:

1. Consulta sin gráficos → `test_tool_works_without_emit_channel` + suite original.
2. Consulta con gráfico (fixture) → `test_consultar_recupero_emits_and_speaks_real_numbers`.
3. Seguimiento que actualiza período → `test_followup_updates_same_visualization_id`.
4. Resultados vacíos → `test_empty_dataset_says_so_without_inventing`.
5. Error de acceso a datos → `test_datasource_error_reports_and_continues`.
6. Sin permisos/fuente no autorizada → `test_unknown_data_source_rejected`.
7. Validación del esquema → `tests/test_analytics.py` (whitelist, claves extra, límites).
8. Prevención de código arbitrario → `test_extra_keys_rejected_no_model_injection`
   + smoke DOM de `web/js/viz.js` (sin `innerHTML`/`eval`, `textContent`).
9-12. Turnos/reserva tras confirmación/continuidad de voz/compatibilidad →
   suite original (`test_bitbit_agent.py`, `test_complex_tasks.py`).

No ejecutadas (sin infraestructura acá): llamada real de voz con el panel
abierto, y el navegador integrado no alcanzó `localhost` en este entorno — el
renderer se verificó con un smoke DOM headless (`node --input-type=module`) que
ejercitó render de line/bar/ring/table, rechazo de chart desconocido y update
in-place por id.

## 10. Limitaciones y próximos pasos

- **Datos**: solo fixture sintético. Caso B (agendamiento con disponibilidad
  real y reserva) requiere el adapter/API del sistema de turnos — la
  arquitectura ya lo soporta vía `DataSource`/tools con confirmación explícita.
- **Permisos por cliente**: modelo de auth pendiente; pertenece al adapter real.
- **Renderer**: line/bar/ring/table/kpi + tooltips nativos; zoom y selección de
  rango por arrastre quedan pendientes (los filtros de período ya existen como
  botones que reutilizan el canal de texto).
- **Anatomy skill**: usable en dev-time para ilustraciones isométricas estáticas;
  integración runtime = principios de craft (ya adoptados), no ejecución de su output.
- **Latencia**: las tools de insights corren en el turno del LLM (tool call →
  cálculo local ~ms → TTS del resumen). No se midió en llamada real.