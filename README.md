# bitbit-agent

Agente de voz de cobranza (**un flujo**) sobre **Pipecat** — sin LiveKit.

## Stack

| Capa | Servicio |
|------|----------|
| Runtime | [Pipecat](https://docs.pipecat.ai) |
| LLM | DeepSeek-V4.1-Flash (`deepseek-flash`) |
| STT | Whisper HTTP (`docker-compose.oss.yml`) o MLX local |
| TTS | Kokoro español in-process (`ef_dora`); opt-in Chatterbox (`TTS_ENGINE=chatterbox`) |
| VAD | Silero |
| Flujo | `app/flow_graph/specs/bitbit_flow_graph.json` |
| KB | `app/kb/bitbit.json` |

Investigación OSS: [docs/STACK_OPEN_SOURCE.md](docs/STACK_OPEN_SOURCE.md)  
ADR: [docs/adr/0001-pipecat-not-livekit.md](docs/adr/0001-pipecat-not-livekit.md)

## Arranque

```bash
cd "Agente de voz 2"
cp .env.example .env
# Completar DEEPSEEK_API_KEY (nunca commitear .env)

python3.13 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"   # incluye pipecat-ai[webrtc]

# STT Whisper (HTTP). TTS = Kokoro in-process (no Docker).
docker compose -f docker-compose.oss.yml up -d whisper

# WebRTC local — abrí http://localhost:7860/client/
.venv/bin/python -m app.pipecat_runtime.bot --transport webrtc
```

Metadata de prueba: `presets/demo_call.json`.

## Flujo

1. Identidad (`registrar_resultado_identidad`, `esperar_titular`)
2. Apertura
3. Negociación (`cliente_dispuesto`, `finalizar`, `responder_kb`)
4. Cierres

## Tests

```bash
pytest -q
```
