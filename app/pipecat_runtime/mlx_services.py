"""Native MLX STT/TTS, with inference off the asyncio audio loop.

One executor serializes Metal work within this process. TTS yields incremental
PCM; an interruption stops requesting further chunks. No audio is sent remotely.
"""
from __future__ import annotations

import asyncio
import io
import os
import re
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from contextlib import suppress

import numpy as np
from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame, BotStoppedSpeakingFrame, ErrorFrame,
    TranscriptionFrame, TTSAudioRawFrame,
)
from pipecat.services.settings import STTSettings, TTSSettings
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.services.tts_service import TTSService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601

from app.pipecat_runtime.audio_map import map_log
from app.pipecat_runtime.config import RuntimeConfig
from app.pipecat_runtime.turn_start import is_turn_filler

_WORD_RE = re.compile(r"[a-záéíóúüñ]+", re.IGNORECASE)
_STOP = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "de",
    "del",
    "al",
    "y",
    "o",
    "que",
    "qué",
    "se",
    "te",
    "me",
    "le",
    "lo",
    "su",
    "sus",
    "es",
    "en",
    "por",
    "para",
    "con",
    "a",
    "algo",
    "asi",
    "así",
    "este",
    "esta",
    "eso",
    "esa",
    "da",
    "pasa",
}
_DOMAIN = {
    "pago",
    "pagar",
    "compra",
    "descuento",
    "cuenta",
    "adeudo",
    "deuda",
    "alcanza",
    "dinero",
    "total",
    "minimo",
    "mínimo",
    "manana",
    "mañana",
    "hoy",
    "quien",
    "quién",
    "habla",
    "empresa",
    "garantia",
    "garantía",
    "cuanto",
    "cuánto",
    "cuota",
    "pedido",
    "fecha",
    "llam",
    "ocupado",
    "ocupada",
    "despues",
    "después",
    "repetir",
    "repetite",
    "repiteme",
    "perdon",
    "perdón",
    "entiendo",
    "confirmo",
    "confirmar",
    "cancelar",
    "equipo",
    "analizador",
    "financiamiento",
    "precio",
    "correcto",
    "claro",
    "soy",
    "yo",
    "hola",
    "espera",
    "paso",
    "pasar",
    "pasalo",
    "pásalo",
    "juan",
    "carla",
    "ana",
    "doctora",
    "turno",
    "cita",
    "bioanalyze",
    # Identidad / terceros / número equivocado
    "equivocado",
    "equivocada",
    "equivoco",
    "número",
    "numero",
    "encuentra",
    "disponible",
    "momento",
    "recado",
    "buzon",
    "buzón",
    "titular",
    "persona",
    "ella",
    "aqui",
    "aquí",
    "ahora",
    "fallecio",
    "falleció",
    "incorrecto",
    # Origen/motivo de llamada — tokens completos (∩ de sets, no prefijos)
    "donde",
    "dónde",
    "llamando",
    "llamada",
    "llamas",
    "llamás",
    "llama",
    "repetido",
    "porfa",
    "favor",
    "compañía",
    "compania",
    "desde",
    "pasó",
    "paso",
    "escucho",
    "escuchas",
    "escuchás",
    "oigo",
    "cortó",
    "corto",
    "disculpe",
    "perdón",
    "perdon",
    # Conversación / rechazo / acuerdo (log 10:09: off-domain)
    "ok",
    "dale",
    "bien",
    "listo",
    "perfecto",
    "gracias",
    "imposible",
    "puedo",
    "pueda",
    "puede",
    "podemos",
    "hacer",
    "comentar",
    "trabajo",
    "responsable",
    "cubrir",
    "pagarlo",
}


# Frases de identidad: el filtro off-domain no debe tirarlas (STT imperfecto OK).
_IDENTITY_KEEP = (
    "equivoc",
    "no soy",
    "no es",
    "no se encuentra",
    "no está",
    "no esta",
    "número equivocado",
    "numero equivocado",
    "me equivoqué",
    "me equivoque",
    "he equivocado",
    "ha equivocado",
    "deja recado",
    "un momento",
    "se lo paso",
    "no está disponible",
    "no esta disponible",
    # Pedidos de aclaración / motivo de llamada (log 21:21:15)
    "me repeti",
    "me repetí",
    "me repite",
    "para qué me",
    "para que me",
    "por qué me llama",
    "por que me llama",
    "de parte de quién",
    "de parte de quien",
    "quién habla",
    "quien habla",
    "me estás llamando",
    "me estas llamando",
    "de dónde",
    "de donde",
    "dónde me",
    "donde me",
    "dónde le",
    "donde le",
    "me está llamando",
    "me esta llamando",
    "me he repetido",
    "me repetido",
    "qué pasó",
    "que paso",
    "qué pasa",
    "que pasa",
    "no te escucho",
    "no escucho",
    "me escuch",
    "me oyen",
    "se cortó",
    "se corto",
    "me cortaste",
    "otra vez",
    "me es imposible",
    "no puedo",
    "no me alcanza",
)



class MLXAudioEngine:
    def __init__(self, config: RuntimeConfig):
        self.config = config
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="bitbit-mlx")
        self.stt = None
        self.tts = None
        self.whisper_path = None
        self._closed = False
        self.last_spoken = ""
        self.tts_busy = False
        self.tts_ended_at = 0.0
        self.playback_active = False
        self.playback_ended_at = 0.0
        # Monotonic deadline while estimated WebRTC playout still has audio,
        # even if Pipecat already emitted BotStoppedSpeakingFrame.
        self.playback_until = 0.0
        self.work_stats = {}
        self.tts_stats = deque(maxlen=64)

    def stt_block_reason(self) -> str:
        now = time.monotonic()
        # Con barge-in habilitado hay que transcribir mientras el bot habla;
        # el eco se filtra en _sanitize_transcript(last_spoken=…).
        barge_in = int(os.getenv("INTERRUPTION_MIN_WORDS", "0") or "0") > 0
        if self.tts_busy and not barge_in:
            return "tts_busy"
        if self.playback_active and not barge_in:
            return "playback_active"
        if self.playback_until > now and not barge_in:
            return f"playout+{self.playback_until - now:.2f}s"
        if self.playback_ended_at > 0 and now - self.playback_ended_at < 0.2:
            return f"cooldown+{now - self.playback_ended_at:.2f}s"
        return "open"
        return "open"

    def stt_is_blocked(self):
        # Follow estimated speaker playout, not GPU completion. Qwen can finish
        # faster than realtime; TTSStoppedFrame then unmutes STT while audio is
        # still queued and echo barge-in wipes the remainder.
        return self.stt_block_reason() != "open"

    async def call(self, fn, *args, **kwargs):
        queued_at = time.perf_counter()

        def measured():
            started = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed = time.perf_counter() - started
                wait = started - queued_at
                name = getattr(fn, "__name__", type(fn).__name__)
                stats = self.work_stats.setdefault(name, {"calls": 0, "max_queue_ms": 0.0, "max_work_ms": 0.0})
                stats["calls"] += 1
                stats["max_queue_ms"] = max(stats["max_queue_ms"], wait * 1000)
                stats["max_work_ms"] = max(stats["max_work_ms"], elapsed * 1000)
                if wait > 0.1:
                    logger.warning("MLX queue operation={} wait_ms={:.0f}", name, wait * 1000)

        return await asyncio.get_running_loop().run_in_executor(
            self.executor, measured
        )

    async def load(self, *, with_tts: bool = True):
        await self.call(self._load, with_tts)

    async def warmup(self, *, with_tts: bool = True):
        """Compile the actual audio paths before accepting microphone input."""
        # Clone (Base + ref_audio) tarda minutos en la primera síntesis; si
        # calentamos acá el supervisor mata el bot a los 180s sin abrir :7870.
        warm_tts = (
            with_tts
            and self.tts is not None
            and self.config.voice_mode != "clone"
        )
        if warm_tts:
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
        else:
            if with_tts and self.config.voice_mode == "clone":
                logger.info(
                    "MLX clone TTS: skip full warmup (primera frase de la llamada compila)"
                )
            audio = io.BytesIO()
            with wave.open(audio, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b"\x00\x00" * 16000)
            await self.call(self.transcribe, audio.getvalue())
        logger.info(
            "MLX audio warmed up with_tts={} voice_mode={}",
            warm_tts,
            self.config.voice_mode,
        )

    def _snapshot(self, repo_id: str) -> str:
        """Usa cache local; si está incompleto, completa por red."""
        from huggingface_hub import snapshot_download
        from huggingface_hub.errors import IncompleteSnapshotError, LocalEntryNotFoundError

        try:
            return snapshot_download(repo_id, local_files_only=True)
        except (IncompleteSnapshotError, LocalEntryNotFoundError, OSError) as exc:
            logger.warning("Cache incompleto para {}; descargando: {}", repo_id, exc)
            return snapshot_download(repo_id, local_files_only=False)

    def _load(self, with_tts: bool = True):
        import mlx.core as mx

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
        if with_tts:
            from mlx_audio.tts.utils import load_model

            self.tts = load_model(self._snapshot(self.config.tts_model))
            logger.info(
                "MLX audio loaded stt={} tts={}",
                self.config.stt_engine,
                self.config.tts_model,
            )
        else:
            self.tts = None
            logger.info(
                "MLX STT loaded engine={} (TTS weights deferred; engine={})",
                self.config.stt_engine,
                os.getenv("TTS_ENGINE", "unset"),
            )

    def transcribe(self, audio: bytes) -> str:
        if self.stt_is_blocked():
            map_log(
                "stt.transcribe_blocked",
                reason=self.stt_block_reason(),
                audio_bytes=len(audio or b""),
            )
            return ""

        import mlx.core as mx

        with wave.open(io.BytesIO(audio), "rb") as wav:
            if wav.getframerate() != 16000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("STT expects 16 kHz mono PCM16")
            samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2").astype(
                np.float32
            ) / 32768

        # Eco/silencio: Parakeet y Whisper inventan "noticias" / inglés.
        if len(samples) < 1600:  # <100 ms
            map_log("stt.too_short", samples=len(samples))
            return ""
        rms = float(np.sqrt(np.mean(np.square(samples))))
        if rms < 0.012:
            map_log("stt.silence", rms=f"{rms:.4f}", samples=len(samples))
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

        return self._sanitize_transcript(text, last_spoken=self.last_spoken)

    @staticmethod
    def _is_repetitive_hallucination(text: str) -> bool:
        """Whisper en silencio/eco: 'No, no, no…' o una sola palabra repetida."""
        words = _WORD_RE.findall((text or "").lower())
        if len(words) < 8:
            return False
        counts: dict[str, int] = {}
        for word in words:
            counts[word] = counts.get(word, 0) + 1
        top = max(counts.values())
        return top >= 8 or (top / len(words)) >= 0.5

    def remember_spoken(self, text: str) -> None:
        chunk = " ".join((text or "").split())
        if not chunk:
            return
        merged = f"{self.last_spoken} {chunk}".strip()
        self.last_spoken = merged[-800:]

    @staticmethod
    def _words(text: str) -> set[str]:
        return set(_WORD_RE.findall((text or "").lower()))

    @classmethod
    def _sanitize_transcript(cls, text: str, last_spoken: str = "") -> str:
        t = " ".join((text or "").strip().split())
        if len(t) < 2:
            return ""
        if is_turn_filler(t):
            return ""
        if cls._is_repetitive_hallucination(t):
            map_log("stt.drop", reason="hallucination", text=repr(t[:80]))
            logger.warning("STT dropped repetitive hallucination: {}", t[:120])
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
            "te trago",
            "se te da",
            "la cabeza",
            "el corazón",
        )
        if any(m in lower for m in junk_markers):
            map_log("stt.drop", reason="junk", text=repr(t[:80]))
            logger.warning("STT dropped hallucination: {}", t)
            return ""
        tokens = cls._words(t)
        # Confirmaciones cortas. No uses "si" suelto: "¿qué pasa si…?" no es un sí.
        if tokens & {"sí", "correcto", "claro", "soy", "yo"} and len(tokens) <= 8:
            return t
        # Muletillas de línea / acuerdo / rechazo de 1-2 palabras.
        # El texto tipado del HUD no pasa por acá; el micrófono sí (log 10:09).
        _SHORT_OK = {
            "si",
            "no",
            "sí",
            "hola",
            "aló",
            "alo",
            "diga",
            "ok",
            "dale",
            "bien",
            "listo",
            "perfecto",
            "gracias",
            "bueno",
        }
        if len(tokens) <= 2 and tokens & _SHORT_OK:
            return t
        # Identidad / chequeo de línea: "número equivocado", "me escuchás", etc.
        if any(marker in lower for marker in _IDENTITY_KEEP):
            return t
        content = tokens - _STOP
        if not content:
            map_log("stt.drop", reason="empty-content", text=repr(t[:80]))
            logger.warning("STT dropped empty-content: {}", t)
            return ""
        spoken_words = cls._words(last_spoken) - _STOP
        # Eco real = el usuario "dijo" solo palabras que el bot acabó de decir.
        # Con last_spoken de 800 chars el umbral 0.45 tiraba frases nuevas
        # (log 10:09:35 "Hola, ¿me escuchás?" overlap=0.50).
        if spoken_words and content.issubset(spoken_words) and len(content) <= 5:
            map_log(
                "stt.drop",
                reason="echo",
                overlap="subset",
                text=repr(t[:80]),
            )
            logger.warning("STT dropped echo of TTS: {}", t)
            return ""
        # ≥2 palabras de contenido en español: dejar pasar (junk/english ya filtraron).
        # 1 token suelto sin dominio → tirar (alucinación corta).
        if len(content) == 1 and not (content & _DOMAIN) and not (content & spoken_words):
            map_log("stt.drop", reason="off-domain", text=repr(t[:80]))
            logger.warning("STT dropped off-domain: {}", t)
            return ""
        # Muy inglés sin señales de confirmación/identidad ES
        es_hits = (
            "sí",
            "si",
            "hola",
            "soy",
            "habla",
            "espera",
            "paso",
            "no",
            "juan",
            "doctora",
            "equivoc",
            "carla",
        )
        en_tokens = set(lower.replace(",", " ").replace(".", " ").split())
        en_common = {"the", "yeah", "yes", "service", "obvious", "from", "news", "and", "so"}
        if en_tokens & en_common and not any(h in lower for h in es_hits):
            map_log("stt.drop", reason="english-like", text=repr(t[:80]))
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
            max_tokens=4096,
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

    async def process_frame(self, frame, direction):
        if isinstance(frame, BotStartedSpeakingFrame):
            self.engine.playback_active = True
            map_log(
                "stt.bot_started",
                block=self.engine.stt_block_reason(),
                tts_busy=self.engine.tts_busy,
            )
            logger.info("AUDIO bot_started_speaking")
        elif isinstance(frame, BotStoppedSpeakingFrame):
            remain = max(0.0, self.engine.playback_until - time.monotonic())
            map_log(
                "stt.bot_stopped",
                remain_s=f"{remain:.3f}",
                tts_busy=self.engine.tts_busy,
                playback_active=self.engine.playback_active,
            )
            self.engine.playback_active = False
            self.engine.tts_busy = False
            self.engine.playback_ended_at = time.monotonic()
            logger.info("AUDIO bot_stopped_speaking remain_s={:.3f}", remain)
        await super().process_frame(frame, direction)

    async def cancel(self, frame):
        map_log("stt.cancel", block=self.engine.stt_block_reason())
        await super().cancel(frame)
        self.engine.playback_active = False
        self.engine.tts_busy = False
        self.engine.playback_ended_at = 0.0

    async def run_stt(self, audio: bytes):
        # Don't enqueue echo behind synthesis on the shared GPU worker.
        reason = self.engine.stt_block_reason()
        if reason != "open":
            map_log("stt.skip", reason=reason, audio_bytes=len(audio or b""))
            return
        started = time.perf_counter()
        try:
            text = await self.engine.call(self.engine.transcribe, audio)
            map_log(
                "stt.out",
                ms=f"{(time.perf_counter() - started) * 1000:.0f}",
                chars=len(text or ""),
                text=repr(text)[:80],
                block_now=self.engine.stt_block_reason(),
            )
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
            map_log("stt.error", err=type(exc).__name__)
            logger.exception("MLX transcription failed")
            yield ErrorFrame(error=f"MLX STT: {type(exc).__name__}")


class QwenMLXTTSService(TTSService):
    def __init__(self, engine: MLXAudioEngine):
        self.engine = engine
        # GPU local puede pausar >3s entre chunks; el default de Pipecat corta con
        # TTSStoppedFrame y el parlante oye un hueco ("se pierde el audio").
        stop_timeout = float(os.getenv("TTS_STOP_TIMEOUT_SECS", "12"))
        super().__init__(
            sample_rate=24000,
            push_start_frame=True,
            push_stop_frames=True,
            stop_frame_timeout_s=stop_timeout,
            settings=TTSSettings(
                model=engine.config.tts_model,
                voice=engine.config.voice,
                language=Language.ES,
            ),
        )
        logger.info(
            "TTS service ready stop_timeout_s={} prebuffer_s={}",
            stop_timeout,
            engine.config.tts_prebuffer,
        )

    def can_generate_metrics(self):
        return True

    async def _keep_synthesis_context_alive(self, context_id: str):
        # A local GPU can pause longer than Pipecat's idle timeout between
        # chunks. Keep the queue alive until synthesis actually finishes;
        # on_turn_context_completed still closes it in normal frame order.
        ticks = 0
        while True:
            self._refresh_audio_context(context_id)
            ticks += 1
            if ticks % 5 == 0:
                logger.debug(
                    "TTS keepalive context={} tick={} timeout_s={}",
                    context_id,
                    ticks,
                    self._stop_frame_timeout_s,
                )
            await asyncio.sleep(self._stop_frame_timeout_s / 3)

    async def run_tts(self, text: str, context_id: str):
        preview = " ".join((text or "").split())
        if len(preview) > 80:
            preview = preview[:77] + "…"
        logger.info(
            "TTS begin context={} mode={} voice={} chars={} text={!r}",
            context_id,
            self.engine.config.voice_mode,
            (
                self.engine.config.reference_audio
                if self.engine.config.voice_mode == "clone"
                else self.engine.config.voice
            ),
            len(text or ""),
            preview,
        )
        map_log("qwen.begin", ctx=context_id, chars=len(text or ""), preview=repr(preview))
        self.engine.remember_spoken(text)
        self.engine.tts_busy = True
        generator = self.engine.speech(text)
        started = time.perf_counter()
        first = True
        pending = []
        buffered_seconds = 0.0
        playback_until = 0.0
        starvation_seconds = 0.0
        starvation_events = 0
        total_audio_seconds = 0.0
        pcm_chunks = 0
        first_audio_ms = None
        completed = False
        await self.start_ttfb_metrics()
        await self.start_tts_usage_metrics(text)
        keepalive = asyncio.create_task(self._keep_synthesis_context_alive(context_id))
        try:
            while True:
                item = await self.engine.call(self.engine.next_pcm, generator)
                if item is None:
                    # Short answers must still play even below the threshold.
                    if pending:
                        first_audio_ms = (time.perf_counter() - started) * 1000
                        await self.stop_ttfb_metrics()
                        logger.info(
                            "LATENCY tts_first_audio_ms={:.0f} (flush short buffer={:.2f}s)",
                            first_audio_ms,
                            buffered_seconds,
                        )
                        playback_until = time.perf_counter() + buffered_seconds
                        self.engine.playback_until = (
                            time.monotonic() + buffered_seconds
                        )
                    for frame in pending:
                        yield frame
                    completed = True
                    break
                pcm, rate = item
                if not pcm:
                    continue
                if rate != self.sample_rate:
                    raise ValueError(f"Unexpected Qwen sample rate: {rate}")
                frame = TTSAudioRawFrame(pcm, rate, 1, context_id=context_id)
                seconds = len(pcm) / (rate * 2)
                total_audio_seconds += seconds
                pcm_chunks += 1
                if first:
                    pending.append(frame)
                    buffered_seconds += seconds
                    if buffered_seconds < self.engine.config.tts_prebuffer:
                        continue
                    first = False
                    first_audio_ms = (time.perf_counter() - started) * 1000
                    await self.stop_ttfb_metrics()
                    map_log(
                        "qwen.first",
                        ctx=context_id,
                        ms=f"{first_audio_ms:.0f}",
                        prebuffer_s=f"{buffered_seconds:.2f}",
                        chunks=pcm_chunks,
                    )
                    logger.info(
                        "LATENCY tts_first_audio_ms={:.0f} prebuffer_filled_s={:.2f}",
                        first_audio_ms,
                        buffered_seconds,
                    )
                    playback_until = time.perf_counter() + buffered_seconds
                    self.engine.playback_until = time.monotonic() + buffered_seconds
                    for queued in pending:
                        yield queued
                    pending.clear()
                else:
                    now = time.perf_counter()
                    gap = max(0.0, now - playback_until)
                    if gap > 0.08:
                        starvation_events += 1
                        map_log(
                            "qwen.underrun",
                            ctx=context_id,
                            gap_ms=f"{gap * 1000:.0f}",
                            chunk=pcm_chunks,
                            audio_s=f"{total_audio_seconds:.2f}",
                        )
                        logger.warning(
                            "AUDIO underrun context={} gap_ms={:.0f} chunk={} "
                            "audio_s={:.2f} gen_s={:.2f}",
                            context_id,
                            gap * 1000,
                            pcm_chunks,
                            total_audio_seconds,
                            now - started,
                        )
                    starvation_seconds += gap
                    # Yield ASAP when ahead so the transport/WebRTC can buffer.
                    # Mid-stream sleeps starved the playout queue on Mac (GPU
                    # ≈ realtime) and made small stalls audible. Drain wait in
                    # finally still delays TTSStopped until estimated playout ends.
                    playback_until = max(now, playback_until) + seconds
                    self.engine.playback_until = time.monotonic() + max(
                        0.0, playback_until - time.perf_counter()
                    )
                    yield frame
        except Exception as exc:
            logger.exception("Qwen TTS failed")
            yield ErrorFrame(error=f"MLX TTS: {type(exc).__name__}")
        finally:
            gen_s = time.perf_counter() - started
            drain_s = 0.0
            self.engine.tts_busy = False
            # Sleep until estimated playout ends so TTSStopped/BotStopped don't
            # land ~tail_s early (log 21:30:35: Bot stopped with playout_tail_s=0.82
            # → eco + STT + sensación de corte). Barge-in also uses playback_until.
            if completed and playback_until > 0:
                drain_s = max(0.0, playback_until - time.perf_counter())
                if drain_s > 0.05:
                    self.engine.playback_until = time.monotonic() + drain_s
                    logger.info(
                        "AUDIO drain_wait_s={:.2f} context={} audio_s={:.2f} gen_s={:.2f}",
                        drain_s,
                        context_id,
                        total_audio_seconds,
                        gen_s,
                    )
                    with suppress(asyncio.CancelledError):
                        await asyncio.sleep(drain_s + 0.05)
            stats = {
                "first_audio_ms": round(first_audio_ms, 1) if first_audio_ms is not None else None,
                "audio_seconds": round(total_audio_seconds, 3),
                "generation_seconds": round(gen_s, 3),
                "drain_wait_seconds": round(drain_s, 3),
                "estimated_starvation_ms": round(starvation_seconds * 1000, 1),
                "starvation_events": starvation_events,
                "pcm_chunks": pcm_chunks,
                "completed": completed,
            }
            if hasattr(self.engine, "tts_stats"):
                self.engine.tts_stats.append(stats)
            realtime_ratio = (
                (total_audio_seconds / gen_s) if gen_s > 0.05 else 0.0
            )
            logger.info(
                "TTS end context={} completed={} chars={} audio_s={:.2f} gen_s={:.2f} "
                "drain_s={:.2f} realtime_ratio={:.2f} underrun_ms={:.0f} "
                "underrun_events={} chunks={}",
                context_id,
                completed,
                len(text or ""),
                total_audio_seconds,
                gen_s,
                drain_s,
                realtime_ratio,
                starvation_seconds * 1000,
                starvation_events,
                pcm_chunks,
            )
            map_log(
                "qwen.end",
                ctx=context_id,
                completed=completed,
                audio_s=f"{total_audio_seconds:.2f}",
                gen_s=f"{gen_s:.2f}",
                drain_s=f"{drain_s:.2f}",
                chunks=pcm_chunks,
                underrun=starvation_events,
            )
            if realtime_ratio < 0.85 and total_audio_seconds > 1.0:
                logger.warning(
                    "AUDIO slow_synthesis context={} realtime_ratio={:.2f} "
                    "(GPU más lento que el parlante → huecos)",
                    context_id,
                    realtime_ratio,
                )
            keepalive.cancel()
            with suppress(asyncio.CancelledError):
                await keepalive
            self.engine.tts_ended_at = time.monotonic()
            await self.engine.call(generator.close)
