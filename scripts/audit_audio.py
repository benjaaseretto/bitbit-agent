"""Repeatable MLX continuity audit; synthetic text, no microphone or LLM API."""
import asyncio
import json
import sys
import time
import wave
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipecat.frames.frames import TTSAudioRawFrame
from app.pipecat_runtime.config import RuntimeConfig
from app.pipecat_runtime.mlx_services import MLXAudioEngine, QwenMLXTTSService
from app.pipecat_runtime.performance import monitor_runtime
from app.pipecat_runtime.runtime_lock import single_mac_runtime

TEXTS = [
    "Sí, claro. ¿Qué horario le queda bien?",
    "Hola, soy Ana de Clínica Vida. Le llamo para confirmar su turno de mañana por la tarde. "
    "Recuerde llegar quince minutos antes y traer su documento. Si necesita cambiar el horario, "
    "puedo ayudarle a encontrar otra fecha. ¿Le queda bien?",
]


async def main():
    config = RuntimeConfig.from_env(require_llm=False)
    engine = MLXAudioEngine(config)
    rows = []
    try:
        await engine.load()
        await engine.warmup()
        async with monitor_runtime(engine, ROOT / "reports" / "audit-performance.jsonl"):
            for interval in [0.32, 0.64, 0.96]:
                engine.config = replace(config, tts_interval=interval)
                for index, text in enumerate(TEXTS):
                    for repeat in range(2):
                        service = QwenMLXTTSService(engine)
                        service._sample_rate = 24000
                        output_bytes = 0
                        async for frame in service.run_tts(text, f"audit-{interval}-{index}-{repeat}"):
                            if not isinstance(frame, TTSAudioRawFrame):
                                raise RuntimeError(f"Unexpected frame: {frame}")
                            output_bytes += len(frame.audio)
                        row = dict(engine.tts_stats[-1], interval=interval, case=index, repeat=repeat)
                        row["rtf"] = round(row["generation_seconds"] / row["audio_seconds"], 3)
                        assert output_bytes > 0 and row["completed"]
                        rows.append(row)
                        print(json.dumps(row), flush=True)
        import mlx.core as mx
        memory = await engine.call(lambda: {
            "active_mib": round(mx.get_active_memory() / 1024**2),
            "peak_mib": round(mx.get_peak_memory() / 1024**2),
        })
        path = ROOT / "reports" / "audio-audit.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"created": time.time(), "memory": memory, "runs": rows}, indent=2))
        # Synthetic user reply for a subsequent real STT/WebRTC smoke test.
        generator = engine.speech("Sí, soy yo. ¿De parte de quién habla?")
        chunks = []
        try:
            while (item := await engine.call(engine.next_pcm, generator)) is not None:
                chunks.append(item[0])
                rate = item[1]
        finally:
            await engine.call(generator.close)
        with wave.open(str(ROOT / "reports" / "synthetic-user.wav"), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(rate)
            wav.writeframes(b"".join(chunks))
        print(json.dumps({"report": str(path), "memory": memory}), flush=True)
    finally:
        await engine.close()


if __name__ == "__main__":
    with single_mac_runtime(ROOT):
        asyncio.run(main())
