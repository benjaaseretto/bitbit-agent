"""Repeatable local checks. Synthetic audio is explicitly labelled, never a human reference."""
import argparse
import asyncio
import io
import json
import sys
import time
import wave
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pipecat_runtime.config import RuntimeConfig
from app.pipecat_runtime.mlx_services import MLXAudioEngine


def wav16(path):
    import soundfile as sf
    samples, rate = sf.read(path, dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    if rate != 16000:
        import math
        divisor = math.gcd(rate, 16000)
        samples = resample_poly(samples, 16000 // divisor, rate // divisor)
    out = io.BytesIO()
    with wave.open(out, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return out.getvalue()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stt", choices=["parakeet", "whisper-mlx"], default="parakeet")
    parser.add_argument("--audio", type=Path, default=ROOT / "assets/voices/ana_es_prompt.wav")
    parser.add_argument("--text", default="Hola, soy Ana de Clínica Vida. ¿En qué puedo ayudarle?")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--stt-only", action="store_true")
    args = parser.parse_args()
    config = replace(RuntimeConfig.from_env(), stt_engine=args.stt)
    report = {"stt": args.stt, "tts": config.tts_model, "voice_mode": config.voice_mode,
              "input_audio": str(args.audio), "note": "Default input is synthetic Kokoro; not a human quality benchmark.",
              "runs": []}
    engine = MLXAudioEngine(config)
    folder = ROOT / "reports"
    folder.mkdir(exist_ok=True)
    try:
        await engine.load()
        audio = wav16(args.audio)
        for run in range(args.runs):
            started = time.perf_counter()
            transcript = await engine.call(engine.transcribe, audio)
            row = {"run": run, "stt_ms": round((time.perf_counter() - started)*1000), "transcript": transcript}
            if not args.stt_only:
                generator = engine.speech(args.text)
                started = time.perf_counter()
                chunks = []
                first = None
                try:
                    while (item := await engine.call(engine.next_pcm, generator)) is not None:
                        pcm, rate = item
                        if pcm:
                            if first is None:
                                first = time.perf_counter() - started
                            chunks.append(pcm)
                finally:
                    await engine.call(generator.close)
                elapsed = time.perf_counter() - started
                if not chunks:
                    raise RuntimeError("TTS returned no audio")
                duration = sum(len(c) for c in chunks) / (rate * 2)
                row.update(tts_first_audio_ms=round(first*1000), tts_total_ms=round(elapsed*1000),
                           audio_seconds=round(duration, 2), rtf=round(elapsed/duration, 3))
                with wave.open(str(folder / f"qwen_sample_{run}.wav"), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(rate)
                    wav.writeframes(b"".join(chunks))
            report["runs"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        await engine.close()
        output = folder / f"benchmark_{args.stt}.json"
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
