# ADR 0001 — Pipecat en lugar de LiveKit

## Contexto

colly-agent acopla el worker de voz a LiveKit Agents y proveedores cerrados (Deepgram, ElevenLabs, OpenAI). bitbit-agent necesita un runtime portable, stack open-source equivalente y un solo flujo de cobranza.

## Decisión

Usar **Pipecat** como orquestador de pipeline de voz, **DeepSeek-V4.1-Flash** (`deepseek-flash`) como LLM, **Whisper** como STT y **Kokoro** como TTS.

## Consecuencias

- Se pierde SIP/LiveKit Cloud, multi-tenant y el catálogo de ~133 flujos de colly.
- Se gana control de costo, self-host de STT/TTS y un repo entregable sin deps LiveKit.
- El flujo se expresa como spec JSON + `FlowController` (tools), no como AgentTasks LiveKit.
