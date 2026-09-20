# Investigación: stack bitbit-agent → open source

Runtime de producto: **Pipecat** (no LiveKit).

| Capa | Servicio OSS / self-host | En bitbit-agent |
|---|---|---|
| Orquestación | Pipecat (BSD) | `app/pipecat_runtime/bot.py` |
| LLM | DeepSeek-V4.1-Flash (`deepseek-flash`) | `DeepSeekLLMService` |
| STT | Whisper (faster-whisper-server) | `OpenAISTTService` → `:8000` |
| TTS | Kokoro español (`ef_dora` / `em_alex`, lang `ES`) | `KokoroTTSService` |
| VAD | Silero | `SileroVADAnalyzer` |
| Flujo | JSON propio | `bitbit_flow_graph.json` |

## Arranque

`python -m app.pipecat_runtime.bot --transport webrtc`

## Fuera de v1

SIP, Redis de campañas, multi-tenant, Langfuse prod, WhatsApp.
