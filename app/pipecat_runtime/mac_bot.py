"""Pipecat Mac: Whisper-MLX STT + Kokoro TTS (default) o Qwen-TTS MLX + DeepSeek."""
from __future__ import annotations

import asyncio
import os
import time

import httpx
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import (
    InputAudioRawFrame,
    LLMUpdateSettingsFrame,
    OutputTransportMessageFrame,
    TTSSpeakFrame,
)
from pipecat.observers.user_bot_latency_observer import UserBotLatencyObserver
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.runner.types import RunnerArguments
from pipecat.runner.utils import create_transport
from pipecat.services.deepseek.llm import DeepSeekLLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import TransportParams
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from app.orchestrator import FlowController, build_session
from app.pipecat_runtime.audio_map import AudioMapObserver, map_log
from app.pipecat_runtime.config import ROOT, RuntimeConfig
from app.pipecat_runtime.performance import monitor_runtime
from app.pipecat_runtime.runtime_lock import single_mac_runtime
from app.pipecat_runtime.deepseek_llm import BitbitDeepSeekLLMService
from app.pipecat_runtime.hud import attach_hud, wire_text_input
from app.pipecat_runtime.mlx_services import MLXAudioEngine, MLXSTTService, QwenMLXTTSService
from app.pipecat_runtime.playout_hold import PlayoutHoldTTSStopped
from app.pipecat_runtime.studio import install_studio_frontend, merge_call_metadata
from app.pipecat_runtime.turn_start import MacMinWordsUserTurnStartStrategy
from app.utils.call_metadata import load_call_metadata
from app.utils.templates import render_template, split_tts_utterances

_THINKING_OFF = DeepSeekLLMService.ThinkingConfig(type="disabled")

_engine = None
_active_call = False


def _tts_engine_name() -> str:
    # Qwen is the natural default on Mac; Kokoro remains opt-in.
    return (os.getenv("TTS_ENGINE") or "qwen-mlx").strip().lower()


def _apply_mac_voice_env() -> None:
    """Studio voice lab wins over parent shell / shared `.env` (TTS_ENGINE=kokoro)."""
    try:
        from app.pipecat_runtime.voice_lab import env_overrides_from_active

        for key, value in env_overrides_from_active().items():
            os.environ[key] = value
    except Exception as exc:
        logger.warning("No se pudo aplicar active voice: {}", exc)
        os.environ.setdefault("TTS_ENGINE", "qwen-mlx")


# Kokoro Mac: sintetizar en paquetes cortos y yield ya, para no esperar
# el guion completo (log 10:15:49: 430 chars → TTFB 4.9s / user_to_audio 6.8s).
_KOKORO_STREAM_CHARS = int(os.getenv("KOKORO_STREAM_CHARS", "140"))


def _build_tts(engine: MLXAudioEngine, config: RuntimeConfig):
    name = _tts_engine_name()
    if name in ("qwen", "qwen-mlx", "mlx"):
        tts = QwenMLXTTSService(engine)
        logger.info(
            "TTS ready engine=qwen-mlx mode={} voice={} ref={} speed={} volume={}",
            config.voice_mode,
            config.voice if config.voice_mode == "preset" else "(clone)",
            (config.reference_audio or "")[:72],
            config.tts_speed,
            config.tts_volume,
        )
        return tts
    from collections.abc import AsyncGenerator

    import numpy as np
    from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
    from pipecat.services.kokoro.tts import KokoroTTSService
    from pipecat.utils.tracing.service_decorators import traced_tts
    from pipecat.utils.types import assert_given, require_given

    class MacKokoroTTSService(KokoroTTSService):
        """Stream Kokoro PCM by short packs so the first sentence starts early."""

        @traced_tts
        async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
            from app.pipecat_runtime.audio_map import map_log

            started = time.perf_counter()
            preview = " ".join((text or "").split())
            if len(preview) > 72:
                preview = preview[:69] + "…"
            packs = split_tts_utterances(text, max_chars=_KOKORO_STREAM_CHARS) or []
            map_log(
                "kokoro.begin",
                ctx=context_id,
                chars=len(text or ""),
                packs=len(packs),
                preview=repr(preview),
            )
            try:
                await self.start_tts_usage_metrics(text)
                voice = require_given(self._settings.voice, "Kokoro TTS voice")
                lang = require_given(self._settings.language, "Kokoro TTS language")
                speed = assert_given(self._settings.speed)
                first_audio = True
                total_out_s = 0.0
                for index, pack in enumerate(packs, start=1):
                    stream = self._kokoro.create_stream(
                        pack, voice=voice, lang=lang, speed=speed, trim=False
                    )
                    parts: list[np.ndarray] = []
                    rate = None
                    async for samples, sample_rate in stream:
                        chunk = np.asarray(samples, dtype=np.float32).reshape(-1)
                        parts.append(chunk)
                        rate = sample_rate
                    if not parts or rate is None:
                        map_log(
                            "kokoro.empty_pack",
                            ctx=context_id,
                            pack=index,
                            chars=len(pack),
                        )
                        continue
                    audio = np.concatenate(parts)
                    # Cola corta solo al final del turno; entre packs no (huecos).
                    if index == len(packs):
                        audio = np.concatenate(
                            [audio, np.zeros(int(0.12 * rate), dtype=np.float32)]
                        )
                    if first_audio:
                        await self.stop_ttfb_metrics()
                        first_audio = False
                    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
                    pcm = await self._resampler.resample(pcm, rate, self.sample_rate)
                    out_s = len(pcm) / max(self.sample_rate * 2, 1)
                    total_out_s += out_s
                    map_log(
                        "kokoro.yield",
                        ctx=context_id,
                        pack=f"{index}/{len(packs)}",
                        chars=len(pack),
                        out_s=f"{out_s:.3f}",
                        total_s=f"{total_out_s:.3f}",
                        pcm_bytes=len(pcm),
                        gen_s=f"{time.perf_counter() - started:.3f}",
                    )
                    yield TTSAudioRawFrame(pcm, self.sample_rate, 1, context_id=context_id)
                if first_audio:
                    map_log(
                        "kokoro.empty",
                        ctx=context_id,
                        gen_s=f"{time.perf_counter() - started:.3f}",
                    )
            except Exception as exc:
                map_log(
                    "kokoro.error",
                    ctx=context_id,
                    err=type(exc).__name__,
                    msg=repr(str(exc)[:120]),
                )
                yield ErrorFrame(error=f"Unknown error occurred: {exc}")
            finally:
                await self.stop_ttfb_metrics()

    voice = os.getenv("KOKORO_VOICE", "ef_dora")
    # Long BioAnalyze scripts take >3s to synthesize; default stop timeout
    # closes the context with "completed with no audio" (log 21:38:06).
    tts = MacKokoroTTSService(
        stop_frame_timeout_s=float(os.getenv("TTS_STOP_TIMEOUT_SECS", "30")),
        settings=KokoroTTSService.Settings(
            voice=voice, language=Language.ES, speed=float(config.tts_speed)
        ),
    )
    logger.info(
        "TTS ready engine=kokoro voice={} language=ES speed={} stream_chars={}",
        voice,
        config.tts_speed,
        _KOKORO_STREAM_CHARS,
    )
    return tts


class ClosedSessionGate(FrameProcessor):
    """Descarta micrófono cuando la sesión ya cerró (fase done)."""

    def __init__(self, session):
        super().__init__()
        self.session = session
        self._muted_logged = False

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and self.session.phase == "done":
            if not self._muted_logged:
                self._muted_logged = True
                map_log("gate.mute_mic", phase="done")
            return
        await self.push_frame(frame, direction)


def _guard_transport_writes(output) -> None:
    """Log MAP transport.drop when SmallWebRTC silently refuses audio.

    BaseOutputTransport swallows a False from write_audio_frame: the chunk is
    dropped, nothing is pushed downstream and TTSStopped arrives instantly
    (log 09:57:22: 23.4 s of Kokoro PCM consumed in 4 ms).
    """
    original = output.write_audio_frame
    state = {"dropped": 0, "bytes": 0, "last_log": 0.0}

    async def guarded(frame):
        ok = await original(frame)
        if ok:
            if state["dropped"]:
                map_log(
                    "transport.drop_end",
                    dropped=state["dropped"],
                    dropped_s=f"{state['bytes'] / max(frame.sample_rate * 2, 1):.3f}",
                )
                state["dropped"] = 0
                state["bytes"] = 0
            return ok
        state["dropped"] += 1
        state["bytes"] += len(frame.audio or b"")
        now = time.monotonic()
        if state["dropped"] == 1 or now - state["last_log"] >= 1.0:
            state["last_log"] = now
            client = getattr(output, "_client", None)
            conn = getattr(client, "_webrtc_connection", None)
            last_ping = getattr(conn, "_last_received_time", None)
            map_log(
                "transport.drop",
                dropped=state["dropped"],
                dropped_s=f"{state['bytes'] / max(frame.sample_rate * 2, 1):.3f}",
                connected=getattr(client, "is_connected", None),
                closing=getattr(client, "is_closing", None),
                track=getattr(client, "_audio_output_track", None) is not None,
                since_ping_s=(
                    f"{time.time() - last_ping:.2f}" if last_ping else None
                ),
            )
        return ok

    output.write_audio_frame = guarded


def _tolerate_stale_ping(connection) -> None:
    """Do not drop audio just because the data-channel ping is late.

    SmallWebRTCConnection.is_connected() returns False when the last `ping`
    is older than 3 s; BaseOutputTransport then discards every audio chunk
    without an error. A cached webrtc.js (4 s pings) or a throttled
    background tab reproduces it. While aiortc still reports the peer
    connection as connected, keep sending; real disconnects are still caught
    by the input track timeout and the ICE state change.
    """
    original = getattr(connection, "is_connected", None)
    if not callable(original):
        return
    state = {"last_log": 0.0}

    def patched() -> bool:
        if original():
            return True
        pc = getattr(connection, "_pc", None)
        if pc is None or getattr(pc, "connectionState", None) != "connected":
            return False
        now = time.monotonic()
        if now - state["last_log"] >= 2.0:
            state["last_log"] = now
            last_ping = getattr(connection, "_last_received_time", None)
            map_log(
                "transport.stale_ping",
                since_ping_s=f"{time.time() - last_ping:.2f}" if last_ping else None,
                pc_state=pc.connectionState,
            )
        return True

    connection.is_connected = patched


def load_metadata():
    return load_call_metadata()


def build_llm(config: RuntimeConfig, prompt: str):
    if config.llm_provider == "deepseek":
        return BitbitDeepSeekLLMService(
            api_key=config.deepseek_api_key,
            settings=DeepSeekLLMService.Settings(
                model=config.deepseek_model,
                system_instruction=prompt,
                thinking=_THINKING_OFF,
                temperature=0.3,
                max_tokens=220,
            ),
        )
    # A/B opcional: OpenAI wire protocol → mlx_lm.server local
    return OpenAILLMService(
        api_key="local",
        base_url=config.llm_url,
        run_in_parallel=False,
        settings=OpenAILLMService.Settings(
            model=config.llm_model,
            system_instruction=prompt,
            temperature=0.3,
            max_tokens=220,
        ),
    )


async def check_llm(config: RuntimeConfig) -> None:
    if config.llm_provider == "deepseek":
        if not config.deepseek_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY ausente")
        logger.info("LLM ready provider=deepseek model={}", config.deepseek_model)
        return
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(f"{config.llm_url.rstrip('/')}/models")
        response.raise_for_status()
        models = {m["id"] for m in response.json()["data"]}
        if config.llm_model not in models:
            raise RuntimeError(f"El servidor local no expone {config.llm_model}")


async def run_bot(transport, runner_args: RunnerArguments):
    global _active_call
    if _active_call:
        raise RuntimeError(
            "Este perfil admite una conversación a la vez en la Mac de 16 GB."
        )
    _apply_mac_voice_env()
    config = RuntimeConfig.from_env()
    _apply_mac_voice_env()
    await check_llm(config)
    session, flow = build_session(merge_call_metadata(load_metadata(), runner_args))
    _active_call = True
    engine = _engine or MLXAudioEngine(config)
    owned = _engine is None
    worker_holder: dict = {}
    use_qwen_tts = _tts_engine_name() in ("qwen", "qwen-mlx", "mlx")
    voice_label = (
        config.reference_audio
        if config.voice_mode == "clone"
        else (config.voice or "preset")
    )
    try:
        from app.pipecat_runtime.voice_lab import set_call_lock

        set_call_lock(active=True, voice_label=str(voice_label or ""))
    except Exception as exc:
        logger.warning("No se pudo escribir call lock: {}", exc)
    try:
        if owned:
            await engine.load(with_tts=use_qwen_tts)
            await engine.warmup(with_tts=use_qwen_tts)
        stt = MLXSTTService(engine)
        tts = _build_tts(engine, config)
        playout_hold = PlayoutHoldTTSStopped(engine)
        if use_qwen_tts and config.voice_mode == "clone":
            logger.info(
                "VOICE mode=clone ref_audio={} ref_text_chars={}",
                config.reference_audio,
                len(config.reference_text or ""),
            )
        elif use_qwen_tts and config.voice_mode == "preset":
            logger.info("VOICE mode=preset voice={}", config.voice)

        async def speak(text):
            # Un solo TTSSpeakFrame por turno. Partir en ~280 (log 21:39:50,
            # chunks 177+252) cerraba el contexto entre frases: el transporte
            # emitía BotStoppedSpeaking a los 4.3s y la frase siguiente quedaba
            # atrás del hold. El timeout de Kokoro ya es 30s, no hace falta
            # trocear un guion de ~400 caracteres.
            max_chars = int(os.getenv("TTS_MAX_CHARS", "720"))
            chunks = split_tts_utterances(text, max_chars=max_chars)
            engine.tts_busy = True
            engine.remember_spoken(text or "")
            map_log(
                "speak",
                chunks=len(chunks),
                chars=len(text or ""),
                lens=[len(c) for c in chunks],
                tts_busy=engine.tts_busy,
                last_spoken_len=len(engine.last_spoken or ""),
                preview=repr((text or "")[:80]),
            )
            logger.info(
                "SPEAK queue chunks={} chars={} lens={}",
                len(chunks),
                len(text or ""),
                [len(c) for c in chunks],
            )
            for index, chunk in enumerate(chunks, start=1):
                logger.info(
                    "SPEAK chunk {}/{} chars={} preview={!r}",
                    index,
                    len(chunks),
                    len(chunk),
                    chunk[:72] + ("…" if len(chunk) > 72 else ""),
                )
                await tts.queue_frame(TTSSpeakFrame(chunk))

        hud = attach_hud(session, transport)

        async def on_phase(phase):
            map_log("phase", phase=phase, status=session.final_status)
            await hud.emit_phase(phase)
            if phase == "done":
                context.set_tools([])
                context.set_tool_choice("none")
                worker = worker_holder.get("worker")
                if worker is not None:
                    # Drena TTS de despedida y corta el pipeline.
                    await worker.stop_when_done()
                return
            context.set_tools(controller.tools_for_phase("negotiation"))
            context.set_tool_choice(controller.tool_choice_for_phase("negotiation"))
            prompt = controller.negotiation_system_prompt()
            if config.llm_provider == "deepseek":
                delta = DeepSeekLLMService.Settings(
                    system_instruction=prompt, thinking=_THINKING_OFF
                )
            else:
                delta = OpenAILLMService.Settings(system_instruction=prompt)
            await llm.queue_frame(LLMUpdateSettingsFrame(delta=delta))

        async def emit_visual(payload: dict) -> None:
            """Canal bot → frontend para visualizaciones (mismo canal que el HUD)."""
            await transport.output().send_message(
                OutputTransportMessageFrame(message=payload)
            )

        controller = FlowController(session, flow, speak=speak, on_phase=on_phase, emit=emit_visual)
        llm = build_llm(config, controller.identity_system_prompt())
        context = LLMContext(
            tools=controller.tools_for_phase("identity"),
            tool_choice=controller.tool_choice_for_phase("identity"),
        )
        user, assistant = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                vad_analyzer=SileroVADAnalyzer(
                    params=VADParams(
                        start_secs=float(os.getenv("VAD_START_SECS", "0.25")),
                        stop_secs=float(os.getenv("VAD_STOP_SECS", "0.25")),
                    )
                ),
                user_turn_strategies=UserTurnStrategies(
                    start=[
                        MacMinWordsUserTurnStartStrategy(
                            min_words=int(os.getenv("INTERRUPTION_MIN_WORDS", "0")),
                            use_interim=False,
                            playback_active=engine.stt_is_blocked,
                        )
                    ]
                ),
            ),
        )
        wire_text_input(transport, user)
        latency = UserBotLatencyObserver()

        @latency.event_handler("on_latency_measured")
        async def measured(observer, seconds):
            map_log("latency", user_to_audio_ms=f"{seconds * 1000:.0f}")
            logger.info("LATENCY user_to_audio_ms={:.0f}", seconds * 1000)

        _guard_transport_writes(transport.output())

        pipeline = Pipeline(
            [
                transport.input(),
                ClosedSessionGate(session),
                stt,
                user,
                llm,
                tts,
                playout_hold,
                transport.output(),
                assistant,
            ]
        )
        worker = PipelineWorker(
            pipeline,
            params=PipelineParams(
                audio_in_sample_rate=16000,
                audio_out_sample_rate=24000,
                enable_metrics=True,
                enable_usage_metrics=True,
            ),
            observers=[latency, hud, AudioMapObserver()],
            idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
            processor_unusable_policy=ProcessorUnusablePolicy.CONTINUE,
        )
        worker_holder["worker"] = worker
        runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
        await runner.add_workers(worker)

        @transport.event_handler("on_client_connected")
        async def connected(transport, client):
            _tolerate_stale_ping(client)
            map_log("session.connected", phase=session.phase, flow=session.flow_key)
            await hud.emit_session()
            opening = flow["flow_graph"]["nodes"]["task.identity_verification"][
                "params"
            ]["identity_identificacion_breve"]
            await speak(
                render_template(opening, session.as_template_vars())
                + f" ¿Hablo con {session.nombre_deudor}?"
            )

        @transport.event_handler("on_client_disconnected")
        async def disconnected(transport, client):
            map_log("session.disconnected", status=session.final_status, phase=session.phase)
            logger.info("Session finished status={}", session.final_status)
            await runner.cancel()

        async with monitor_runtime(engine):
            await runner.run()
    finally:
        _active_call = False
        try:
            from app.pipecat_runtime.voice_lab import set_call_lock

            set_call_lock(active=False)
        except Exception:
            pass
        if owned:
            await engine.close()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(
        runner_args,
        {
            # auto_silence=True mantiene el timestamp del RawAudioTrack en
            # sincronía durante el idle; con False el track "recuperaba" el
            # atraso en ráfaga (log 09:57:06: 3.1 s en 0.12 s) y el navegador
            # descartaba el arranque de la frase. Kokoro ya entrega un solo
            # frame por turno, así que no hay huecos entre batches que tapar.
            "webrtc": lambda: TransportParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                audio_out_auto_silence=True,
            )
        },
    )
    await run_bot(transport, runner_args)


def _main():
    global _engine
    # Apply before and after dotenv: shared `.env` still says kokoro for Linux.
    _apply_mac_voice_env()
    config = RuntimeConfig.from_env()
    _apply_mac_voice_env()
    _engine = MLXAudioEngine(config)

    async def prepare():
        await check_llm(config)
        _apply_mac_voice_env()
        engine_name = _tts_engine_name()
        use_qwen = engine_name in ("qwen", "qwen-mlx", "mlx")
        logger.info(
            "Mac audio profile tts_engine={} load_qwen_weights={} env={}",
            engine_name,
            use_qwen,
            os.getenv("TTS_ENGINE"),
        )
        await _engine.load(with_tts=use_qwen)
        await _engine.warmup(with_tts=use_qwen)

    from pipecat.runner.run import main as run

    try:
        install_studio_frontend()
        asyncio.run(prepare())
        run()
    finally:
        asyncio.run(_engine.close())


def main():
    with single_mac_runtime(ROOT):
        _main()


if __name__ == "__main__":
    main()
