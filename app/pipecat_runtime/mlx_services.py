"""Native MLX STT/TTS, with inference off the asyncio audio loop.

One executor serializes Metal work within this process. TTS yields incremental
PCM; an interruption stops requesting further chunks. No audio is sent remotely.
"""
from __future__ import annotations

import asyncio
import io
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import numpy as np
from loguru import logger
from pipecat.frames.frames import ErrorFrame, TranscriptionFrame, TTSAudioRawFrame
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

from app.pipecat_runtime.config import RuntimeConfig


class MLXAudioEngine:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bitbit-mlx")
        self.stt = None
        self.tts = None
        self.whisper_path = None
        self._closed = False

    async def call(self, fn, *args, **kwargs):
        return await asyncio.get_running_loop().run_in_executor(
            self.executor, partial(fn, *args, **kwargs)
        )

    async def load(self):
        await self.call(self._load)

    async def warmup(self):
        """Compile the actual audio paths before accepting microphone input."""
        generator = self.speech("Hola, buen día.")
        chunks = []
        try:
            while (item := await self.call(self.next_pcm, generator)) is not None:
                chunks.append(item[0])
                rate = item[1]
        finally:
            await self.call(generator.close)
        if chunks:
            from scipy.signal import resample_poly
            import math
            samples = np.frombuffer(b"".join(chunks), dtype="<i2").astype(np.float32) / 32768
            divisor = math.gcd(rate, 16000)
            samples = resample_poly(samples, 16000 // divisor, rate // divisor)
            audio = io.BytesIO()
            with wave.open(audio, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
            await self.call(self.transcribe, audio.getvalue())
        logger.info("MLX audio warmed up")

    def _snapshot(self, repo_id: str) -> str:
        """Usa cache local; si está incompleto, completa por red."""
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import IncompleteSnapshotError, LocalEntryNotFoundError

        try:
            return snapshot_download(repo_id, local_files_only=True)
        except (IncompleteSnapshotError, LocalEntryNotFoundError, OSError) as exc:
            logger.warning("Cache incompleto para {}; descargando: {}", repo_id, exc)
            return snapshot_download(repo_id, local_files_only=False)

    def _load(self):
        import mlx.core as mx
        from mlx_audio.tts.utils import load_model

        # Bound reclaimable Metal allocations on the shared 16 GB machine.
        mx.set_cache_limit(256 * 1024 * 1024)
        if self.config.stt_engine == "parakeet":
            from parakeet_mlx import from_pretrained

            path = self._snapshot(self.config.parakeet_model)
            self.stt = from_pretrained(path)
        else:
            from mlx_whisper.transcribe import ModelHolder

            self.whisper_path = self._snapshot(self.config.whisper_model)
            ModelHolder.get_model(self.whisper_path, mx.float16)
        self.tts = load_model(self._snapshot(self.config.tts_model))
        logger.info("MLX audio loaded stt={} tts={}", self.config.stt_engine, self.config.tts_model)

    def transcribe(self, audio: bytes) -> str:
        import mlx.core as mx

        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getframerate() != 16000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("STT expects 16 kHz mono PCM16")
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(
                np.float32
            ) / 32768

        # Eco/silencio: Parakeet y Whisper inventan "noticias" / inglés.
        if len(samples) < 1600:  # <100 ms
            return ""
        rms = float(np.sqrt(np.mean(np.square(samples))))
        if rms < 0.012:
            logger.debug("STT skip silence rms={:.4f}", rms)
            return ""

        if self.config.stt_engine == "parakeet":
            from parakeet_mlx.audio import get_logmel

            mel = get_logmel(mx.array(samples), self.stt.preprocessor_config)
            text = self.stt.generate(mel)[0].text.strip()
        else:
            import mlx_whisper

            text = mlx_whisper.transcribe(
                samples,
                path_or_hf_repo=self.whisper_path,
                language="es",
                condition_on_previous_text=False,
                temperature=0,
                no_speech_threshold=0.6,
            )["text"].strip()

        return self._sanitize_transcript(text)

    @staticmethod
    def _sanitize_transcript(text: str) -> str:
        t = " ".join((text or "").strip().split())
        if len(t) < 2:
            return ""
        lower = t.lower()
        # Alucinaciones típicas de STT con eco/ruido en demos locales
        junk_markers = (
            "breaking news",
            "subscribe",
            "thank you for watching",
            "milicias",
            "noticias desde",
            "obvious service",
            "mar rojo",
            "interpresiones",
            "www.",
            "http",
        )
        if any(m in lower for m in junk_markers):
            logger.warning("STT dropped hallucination: {}", t)
            return ""
        # Muy inglés sin señales de confirmación/identidad ES
        es_hits = ("sí", "si", "hola", "soy", "habla", "espera", "paso", "no", "juan", "doctora")
        en_tokens = set(lower.replace(",", " ").replace(".", " ").split())
        en_common = {"the", "yeah", "yes", "service", "obvious", "from", "news", "and", "so"}
        if en_tokens & en_common and not any(h in lower for h in es_hits):
            logger.warning("STT dropped english-like: {}", t)
            return ""
        return t
    def speech(self, text: str):
        kwargs = dict(
            text=text,
            lang_code="Spanish",
            stream=True,
            streaming_interval=self.config.tts_interval,
            verbose=False,
            max_tokens=600,
            speed=self.config.tts_speed,
        )
        if self.config.voice_mode == "clone":
            kwargs.update(
                ref_audio=self.config.reference_path(),
                ref_text=self.config.reference_text,
            )
        else:
            kwargs.update(voice=self.config.voice)
        return self.tts.generate(**kwargs)

    def next_pcm(self, generator):
        """Convierte el siguiente chunk a PCM16, aplicando speed/volume locales."""
        result = next(generator, None)
        if result is None:
            return None
        samples = np.asarray(result.audio, dtype=np.float32).reshape(-1)
        speed = float(self.config.tts_speed)
        volume = float(self.config.tts_volume)
        # Qwen aún no aplica speed de forma fiable: resampleamos el chunk.
        if abs(speed - 1.0) > 1e-3 and samples.size > 1:
            new_len = max(1, int(round(samples.size / speed)))
            x_old = np.linspace(0.0, 1.0, num=samples.size, endpoint=True)
            x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=True)
            samples = np.interp(x_new, x_old, samples).astype(np.float32)
        if abs(volume - 1.0) > 1e-3:
            samples = samples * volume
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        return pcm, result.sample_rate
    async def close(self):
        if not self._closed:
            self._closed = True
            await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=True)


class MLXSTTService(SegmentedSTTService):
    def __init__(self, engine: MLXAudioEngine):
        self.engine = engine
        super().__init__(sample_rate=16000, settings=STTSettings(
            model=engine.config.stt_engine, language=Language.ES))

    def can_generate_metrics(self):
        return True

    async def run_stt(self, audio: bytes):
        started = time.perf_counter()
        try:
            text = await self.engine.call(self.engine.transcribe, audio)
            logger.info(
                "LATENCY stt_ms={:.0f} text={!r}",
                (time.perf_counter() - started) * 1000,
                text,
            )
            if text:
                yield TranscriptionFrame(
                    text, self._user_id, time_now_iso8601(), language=Language.ES
                )
        except Exception as exc:
            logger.exception("MLX transcription failed")
            yield ErrorFrame(error=f"MLX STT: {type(exc).__name__}")


class QwenMLXTTSService(TTSService):
    def __init__(self, engine: MLXAudioEngine):
        self.engine = engine
        super().__init__(sample_rate=24000, push_start_frame=True, push_stop_frames=True,
                         settings=TTSSettings(model=engine.config.tts_model,
                                              voice=engine.config.voice, language=Language.ES))

    def can_generate_metrics(self):
        return True

    async def run_tts(self, text: str, context_id: str):
        generator = self.engine.speech(text)
        started = time.perf_counter()
        first = True
        await self.start_ttfb_metrics()
        await self.start_tts_usage_metrics(text)
        try:
            while True:
                item = await self.engine.call(self.engine.next_pcm, generator)
                if item is None:
                    break
                pcm, rate = item
                if not pcm:
                    continue
                if rate != self.sample_rate:
                    raise ValueError(f"Unexpected Qwen sample rate: {rate}")
                if first:
                    first = False
                    await self.stop_ttfb_metrics()
                    logger.info("LATENCY tts_first_audio_ms={:.0f}", (time.perf_counter() - started) * 1000)
                yield TTSAudioRawFrame(pcm, rate, 1, context_id=context_id)
        except Exception as exc:
            logger.exception("Qwen TTS failed")
            yield ErrorFrame(error=f"MLX TTS: {type(exc).__name__}")
        finally:
            # Runs after any in-flight next() in the same executor, including
            # cancellation; never call generator.close() while it is executing.
            await self.engine.call(generator.close)
