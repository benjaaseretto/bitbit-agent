# Voces disponibles (legales)

No hay clonación de cantantes famosos: eso requiere derechos de imagen/voz.
Acá están las voces **preset** que el stack ya soporta, más cómo usar **tu propia** grabación.

## Qwen3-TTS CustomVoice (perfil Mac / `run_local.py`)

Variable: `QWEN_TTS_VOICE` en `.env` o `.env.mac`.

| ID | Notas |
|----|--------|
| `Serena` | Default actual; buena para ES |
| `Vivian` | Femenina |
| `Ryan` | Masculina |
| `Aiden` | Masculina |
| `Uncle_Fu` | Masculina / madura |
| `Ono_Anna` | Femenina |
| `Sohee` | Femenina |
| `Eric` | Dialecto Sichuan (chino; no ideal para ES) |
| `Dylan` | Dialecto Beijing (chino; no ideal para ES) |

Ejemplo:

```bash
QWEN_TTS_VOICE=Vivian
TTS_SPEED=1.05
TTS_VOLUME=1.0
```

Listar en runtime:

```bash
python scripts/list_voices.py
```

## Kokoro (bot clásico / `python -m app.pipecat_runtime.bot`)

Variable: `KOKORO_VOICE`. Voces en español (prefijo `e`):

| ID | Notas |
|----|--------|
| `ef_dora` | Default; femenina ES |
| `em_alex` | Masculina ES |
| `em_santa` | Masculina ES |

## Clonar una voz propia (no celebridades)

1. Grabá ~10–20 s de audio limpio (vos u otra persona con permiso escrito).
2. Transcribí el texto exacto.
3. En `.env.mac`:

```bash
TTS_VOICE_MODE=clone
QWEN_TTS_REFERENCE_AUDIO=presets/voices/mi_voz.wav
QWEN_TTS_REFERENCE_TEXT="Hola, este es un audio de referencia para clonar mi voz."
```

4. `python scripts/prepare_models.py --clone` (una vez) y reiniciá `run_local.py`.

## Variar entre llamadas

Podés rotar presets sin código:

```bash
QWEN_TTS_VOICE=Ryan python scripts/run_local.py
QWEN_TTS_VOICE=Serena python scripts/run_local.py
```

O definir varias entradas en un archivo de presets y elegir con `BITBIT_VOICE_PRESET` (ver `presets/voices.json`).
