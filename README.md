# clinica-vida-agent (bitbit-agent)

Agente de voz para **consultas médicas** (identidad + agenda) sobre **Pipecat**.
Los flujos y tasks son **scripts independientes** (estilo colly): sumás un JSON +
un módulo en `app/tasks/` sin tocar el pipeline.

## Stack

| Capa | Servicio |
|------|----------|
| Runtime | [Pipecat](https://docs.pipecat.ai) |
| LLM | **DeepSeek-V4.1-Flash** (`deepseek-flash`) — default en bot y perfil Mac |
| STT | Whisper HTTP, o **Parakeet MLX** en Mac (`mac_bot`) |
| TTS | Kokoro, o **Qwen3-TTS MLX** streaming en Mac |
| VAD | Silero |
| Flujo | `app/flow_graph/specs/clinica_vida_flow_graph.json` |
| KB | `app/kb/clinica_vida.json` |
| Tasks | `app/tasks/identity.py`, `app/tasks/appointment.py` |

## Arranque (cloud STT/TTS + DeepSeek)

```bash
cd "Agente de voz 2"
cp .env.example .env
# Completar DEEPSEEK_API_KEY (nunca commitear .env)

python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

docker compose -f docker-compose.oss.yml up -d whisper

.venv/bin/python -m app.pipecat_runtime.bot --transport webrtc
```

## Arranque Mac (Parakeet + Qwen-TTS + DeepSeek)

```bash
cp .env.mac.example .env.mac
# DEEPSEEK_API_KEY en .env o .env.mac
# Opcional: TTS_SPEED=1.1  TTS_VOLUME=0.9
pip install -e ".[dev,mac]"
python scripts/prepare_models.py
python scripts/run_local.py
# Studio (supervisor): http://localhost:7860/
# Bot WebRTC interno: :7870 — Apagar / Encender desde el front
```

El supervisor en `:7860` deja la UI viva. **Apagar bot** mata el proceso MLX;
**Encender bot** lo vuelve a levantar sin reiniciar la terminal.

Voz Mac: `TTS_SPEED` (0.5–2.0) y `TTS_VOLUME` (0.1–2.0) en `.env` / `.env.mac`.

Para suavizar pausas entre fragmentos, `TTS_PREBUFFER_SECONDS` acumula audio antes
de reproducir (1.2 s por defecto; 0 desactiva la reserva). Añade espera inicial;
no elimina pausas que ya estén dentro del audio generado ni compensa una síntesis
sostenidamente más lenta que tiempo real. El registro `TTS continuity` informa
`estimated_starvation_ms`: estima cuánto tiempo faltó audio durante la síntesis,
sin incluir problemas de red o del navegador. Reiniciar el servidor tras cambiarlo.

El fragmento por defecto es de 0.64 s (`TTS_STREAMING_INTERVAL`). Cada llamada
guarda métricas sin texto ni audio en `reports/runtime-performance.jsonl`.
La [revisión de rendimiento](docs/audio-review-2026-09-20.md) documenta mediciones,
límites y comandos para repetir las pruebas locales.

LLM local MLX queda solo como A/B (`LLM_PROVIDER=mlx`); no es el default.

Metadata de prueba: `presets/demo_call.json`.
Flujo: `BITBIT_FLOW_KEY=clinica_vida_flow` (default).

## Flujo

1. Identidad del paciente (`IdentityVerificationTask`)
2. Apertura: turno ya cargado (día, hora, médico, sucursal) y pedido de confirmación
3. Confirmación (`AppointmentSchedulingTask` modo `confirm_attendance`: `confirmar_asistencia`, `reagendar_cita`, `cancelar_cita`, `responder_kb`)
4. Cierres (asistencia confirmada, reagendado, cancelado, recado, equivocado)

## Extender (como colly)

```bash
python scripts/new_flow.py otra_clinica --visible-name "Otra Clínica" --with-task
```

Ver [docs/FLOWS.md](docs/FLOWS.md) para el contrato de tasks y el índice de
stubs migrados desde colly / `legacy-agent-voice`.

## Tests

```bash
pytest -q
```
