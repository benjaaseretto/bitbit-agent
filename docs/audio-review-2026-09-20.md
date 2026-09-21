# Revisión de fluidez — Mac, 20 de septiembre de 2026

Se revisaron STT, TTS, coordinación del ejecutor MLX, reproducción, arranque,
interfaz y recursos. Se conservó el flujo de negocio. La configuración activa
usa Whisper MLX y Qwen3-TTS locales, pero el LLM sigue siendo DeepSeek por API.
Por tanto, el perfil activo no es completamente local.

## Hallazgos y cambios

1. **La protección del eco terminaba antes que la reproducción.** La generación
   puede terminar varios segundos antes que el parlante. Ahora STT observa
   `BotStartedSpeakingFrame` / `BotStoppedSpeakingFrame`. Se reemplazó el descarte
   fijo de dos segundos tras generar por una cola acústica de 200 ms tras
   reproducir. El audio identificado como eco no se encola al ejecutor MLX.
   Se mantiene la política existente de no interrumpir durante la voz del bot.
2. **Fragmentos demasiado pequeños aumentaban trabajo.** Se compararon 320, 640
   y 960 ms. Se seleccionaron 640 ms, conservando una reserva inicial de 1,2 s
   de audio. Esta reserva agrega latencia inicial; no elimina silencios propios
   de la voz ni garantiza continuidad bajo cualquier carga.
3. **Arranques duplicados podían cargar modelos antes de fallar por el puerto.**
   Un bloqueo por proyecto evita una segunda instancia Mac antes de asignar GPU.
   Se cerró el servidor Qwen LLM ocioso del proyecto: el perfil actual no lo usa.
   `LLM_PROVIDER=mlx` continúa disponible y el lanzador puede iniciarlo de nuevo.
4. **La animación competía por GPU.** Se limitó a 30 FPS y se omite el dibujo
   con la pestaña oculta. No se cambió la reproducción ni se midió todavía
   el ahorro de GPU en una sesión humana de navegador.
5. **Faltaban mediciones que separaran causas.** Cada llamada guarda tiempos
   de cola y trabajo MLX, retrasos del bucle de eventos y continuidad estimada
   de TTS. El historial de diagnósticos está acotado y no incluye diálogos ni audio.
6. **El arranque antiguo dependía de Daily incluso para WebRTC.** Se hizo diferida
   esa importación. También se pasó la carga de `.env` al arranque: importar el
   módulo alteraba el entorno y contaminaba las pruebas de otros flujos.

Se conservaron la protección del contexto TTS ante pausas del generador y el
límite ampliado de síntesis introducidos en la revisión anterior.

## Mediciones

Doce síntesis: dos textos sintéticos de distinta longitud, dos repeticiones por
tamaño de fragmento, modelos precalentados. La voz genera duraciones variables;
esta muestra pequeña orienta el ajuste, no establece garantías estadísticas.

| Fragmento | Primer audio, media | Tiempo de generación / duración del audio | Agotamiento estimado |
|---|---:|---:|---:|
| 320 ms | 938 ms | 0,709 | 0 ms |
| 640 ms, elegido | 871 ms | 0,691 | 0 ms |
| 960 ms | 1348 ms | 0,692 | 0 ms |

El primer audio incluye la reserva de reproducción; no incluye pensar con el
LLM, escuchar al usuario ni detectar el final de su turno.

- Memoria MLX activa: 2904 MiB; pico: 3857 MiB. No es la memoria total del proceso
  ni de la Mac.
- Cola del ejecutor durante síntesis aislada: máximo 0,083 ms. No se observó
  contención significativa en esta prueba.
- Retraso del bucle de eventos: máximo 7,16 ms, p95 2,13 ms durante las 12 síntesis.
- Whisper, frase sintética de 2,45 s: 1398 ms en frío, 224 y 223 ms precalentado.
  La transcripción conservó la intención de la frase. No es una evaluación de
  precisión general ni de micrófono real.
- WebRTC local, saludo completo: 615 paquetes recibidos, cero perdidos; 611
  cuadros de audio entregados. TTS completado, agotamiento estimado 0 ms.
  Primer audio en esta llamada: 1490 ms; retraso máximo del bucle: 2,45 ms.
- 85 pruebas Python pasan; comprobación de sintaxis JavaScript y compilación
  Python realizadas. Pruebas nuevas cubren demoras entre fragmentos, audio corto,
  preservación de PCM, reproducción versus síntesis, respuesta rápida del usuario,
  contención de ejecutor, bloqueo de instancias y persistencia de diagnósticos.

## Límites y trabajo pendiente

La Mac tenía aproximadamente 16 GB de swap usado antes de la revisión. Es un
indicador acumulado: no prueba que hubiera paginación activa durante los cortes.
No se atribuyen las mejoras a una reducción de swap ni se cerraron aplicaciones
ajenas al proyecto.

La comprobación WebRTC usó entrada silenciosa y sólo el saludo guionado.
La prueba completa con respuesta del LLM fue rechazada por la revisión automática
de seguridad porque podría enviar contexto privado del flujo a DeepSeek.
No se realizó ese envío. Falta autorización para esa medición con el proveedor
actual; tampoco se midieron eco de parlantes y variación de carga con una persona.

No se puede prometer fluidez en todo momento con estos resultados: cargas ajenas,
pausas generadas por el modelo, red y latencia del LLM siguen siendo variables.
La instrumentación permite acotar la causa si vuelve a ocurrir.

## Reproducción

- `python scripts/audit_audio.py`: cerrar el agente primero. Usa GPU y modelos
  locales, sin micrófono ni LLM. Guarda `reports/audio-audit.json`.
- `python scripts/check_audio_call.py --opening-only`: requiere el servidor Mac;
  verifica WebRTC y saludo con entrada silenciosa, sin activar el LLM.
- `python scripts/check_audio_call.py` sin esa opción envía una frase sintética
  al agente y puede activar el proveedor LLM con el contexto del flujo configurado.
  Requiere revisar y autorizar ese contexto/destino antes de esta prueba.
- Diagnósticos por llamada: `reports/runtime-performance.jsonl`. Resultados de
  esta revisión: `reports/audit-performance.jsonl`, `reports/call-audit.json` y
  `reports/stt-audit.json`.

El servidor quedó iniciado en `http://localhost:7860/`. Recargar el Studio para
que el navegador use también la animación actualizada.
