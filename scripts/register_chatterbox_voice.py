#!/usr/bin/env python3
"""Generate a Spanish reference clip (Kokoro) and register it on Chatterbox as language=es."""
from __future__ import annotations

import os
import sys
import wave
from pathlib import Path

import numpy as np
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets" / "voices"
PROMPT_WAV = ASSETS / "ana_es_prompt.wav"
PROMPT_TEXT = (
    "Hola, buen día. Mi nombre es Ana, le hablo de Bitbit respecto al "
    "financiamiento de su teléfono móvil. Quedo atento a su respuesta."
)


def _synthesize_with_kokoro(out_path: Path) -> None:
    from kokoro_onnx import Kokoro
    from pipecat.services.kokoro.tts import KOKORO_CACHE_DIR, _ensure_model_files

    model = KOKORO_CACHE_DIR / "kokoro-v1.0.onnx"
    voices = KOKORO_CACHE_DIR / "voices-v1.0.bin"
    _ensure_model_files(model, voices)
    kokoro = Kokoro(str(model), str(voices))
    samples, sr = kokoro.create(PROMPT_TEXT, voice="ef_dora", speed=1.0, lang="es")
    pcm = (np.asarray(samples) * 32767.0).astype(np.int16)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sr))
        wf.writeframes(pcm.tobytes())
    print(f"Wrote Spanish prompt → {out_path}")


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    base = os.getenv("CHATTERBOX_BASE_URL", "http://localhost:4123/v1").rstrip("/")
    # voices endpoint is on host root, not under /v1
    host = base.removesuffix("/v1")
    voice_name = os.getenv("CHATTERBOX_VOICE", "ana_es")

    if not PROMPT_WAV.exists():
        print("Generating Spanish prompt with Kokoro (one-shot)…")
        _synthesize_with_kokoro(PROMPT_WAV)

    # health — this image exposes /health, not /languages or /voices
    try:
        r = requests.get(f"{host}/health", timeout=10)
        r.raise_for_status()
        print("Health:", r.json())
    except Exception as exc:
        print(f"Chatterbox not reachable at {host}: {exc}", file=sys.stderr)
        print("Start: docker compose -f docker-compose.oss.yml up -d chatterbox", file=sys.stderr)
        return 1

    # Optional voice library (older/newer API builds). travisvn image may not expose it.
    try:
        with PROMPT_WAV.open("rb") as fh:
            resp = requests.post(
                f"{host}/voices",
                data={"voice_name": voice_name, "language": "es"},
                files={"voice_file": (PROMPT_WAV.name, fh, "audio/wav")},
                timeout=60,
            )
        print("Register status:", resp.status_code, resp.text[:500])
        if resp.status_code == 404:
            print(
                "Note: this Chatterbox build has no /voices endpoint; "
                "using default voice-sample + language=es on /v1/audio/speech."
            )
    except Exception as exc:
        print(f"Voice register skipped: {exc}")

    # smoke TTS
    speech = requests.post(
        f"{base}/audio/speech",
        json={
            "input": "Hola, ¿me confirma si hablo con Juan Pérez?",
            "voice": voice_name,
            "language": "es",
        },
        timeout=120,
    )
    out = ROOT / "assets" / "voices" / "chatterbox_smoke.wav"
    out.write_bytes(speech.content)
    print(f"Smoke TTS → {out} ({speech.status_code}, {len(speech.content)} bytes)")
    return 0 if speech.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
