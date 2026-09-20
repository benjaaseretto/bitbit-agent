# ADR 0001 — Pipecat en lugar de LiveKit

## Contexto

colly-agent acopla el worker de voz a LiveKit Agents y proveedores cerrados (Deepgram, ElevenLabs, OpenAI). Este agente necesita un runtime portable, stack open-source equivalente y un solo flujo de consultas médicas.

## Decisión

Usar **Pipecat** como orquestador de pipeline de voz, **DeepSeek-V4.1-Flash** (`deepseek-flash`) como LLM, **Whisper** como STT y **Kokoro** como TTS.

## Consecuencias

- Se pierde SIP/LiveKit Cloud, multi-tenant y el catálogo de ~133 flujos de colly.
- Se gana control de costo, self-host de STT/TTS y un repo entregable sin deps LiveKit.
- El flujo se expresa como **spec JSON independiente** + **tasks/scripts** (`app/tasks/*`)
  orquestados por `FlowController` (Pipecat tools), no como AgentTasks LiveKit.
- Las tasks de colly no portadas quedan indexadas en `app/tasks/stubs.py` para migrar
  de a una (`scripts/new_flow.py`).
