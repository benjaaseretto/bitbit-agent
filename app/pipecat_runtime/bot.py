"""
clinica-vida-agent — bot de voz con Pipecat.

Stack: DeepSeek-V4.1-Flash + Whisper OSS + Kokoro (ES) + Silero VAD.
Flujo: app/flow_graph/specs/*.json (default clinica_vida_flow).
Tasks: app/tasks/* (scripts independientes).

Arranque:
  python -m app.pipecat_runtime.bot --transport webrtc
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv
from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import InputAudioRawFrame, LLMUpdateSettingsFrame, TTSSpeakFrame
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
from pipecat.services.openai.stt import OpenAISTTService
from pipecat.transcriptions.language import Language
from pipecat.transports.base_transport import BaseTransport, TransportParams
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams
from pipecat.workers.runner import WorkerRunner

from app.orchestrator import FlowController, build_session
from app.pipecat_runtime.deepseek_llm import BitbitDeepSeekLLMService
from app.pipecat_runtime.hud import attach_hud, wire_text_input
from app.pipecat_runtime.studio import install_studio_frontend, merge_call_metadata
from app.utils.call_metadata import load_call_metadata
from app.utils.templates import render_template, split_tts_utterances

_THINKING_OFF = DeepSeekLLMService.ThinkingConfig(type="disabled")

class ClosedSessionGate(FrameProcessor):
    """Descarta micrófono cuando la sesión ya cerró (fase done)."""

    def __init__(self, session):
        super().__init__()
        self.session = session

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame) and self.session.phase == "done":
            return
        await self.push_frame(frame, direction)


def require_config() -> None:
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        logger.error(
            "DEEPSEEK_API_KEY is required. Copy .env.example to .env and set your key."
        )
        sys.exit(1)


def _build_stt():
    engine = (os.getenv("STT_ENGINE") or "whisper-http").strip().lower()
    if engine in ("mlx", "local", "whisper-local"):
        from pipecat.services.whisper.stt import WhisperSTTService

        return WhisperSTTService(
            settings=WhisperSTTService.Settings(
                model=os.getenv("WHISPER_MODEL", "base"),
                language=Language.ES,
            ),
        )
    return OpenAISTTService(
        api_key=os.getenv("WHISPER_API_KEY", "not-needed"),
        base_url=os.getenv("WHISPER_BASE_URL", "http://localhost:8000/v1"),
        settings=OpenAISTTService.Settings(
            model=os.getenv("WHISPER_MODEL", "whisper-1"),
            language=Language.ES,
        ),
    )


def _build_tts():
    """Default: Kokoro in-process (ES). Opt-in: TTS_ENGINE=chatterbox (docker :4123)."""
    engine = (os.getenv("TTS_ENGINE") or "kokoro").strip().lower()
    if engine in ("chatterbox", "chatterbox-multilingual"):
        from app.pipecat_runtime.chatterbox_tts import ChatterboxTTSService

        voice = os.getenv("CHATTERBOX_VOICE", "ana_es")
        tts = ChatterboxTTSService(
            base_url=os.getenv("CHATTERBOX_BASE_URL", "http://localhost:4123/v1"),
            api_key=os.getenv("CHATTERBOX_API_KEY", "not-needed"),
            language=os.getenv("CHATTERBOX_LANGUAGE", "es"),
            settings=ChatterboxTTSService.Settings(
                voice=voice,
                model=os.getenv("CHATTERBOX_MODEL", "chatterbox-multilingual"),
            ),
        )
        logger.info(
            "TTS ready engine=chatterbox-multilingual voice={} language={}",
            voice,
            os.getenv("CHATTERBOX_LANGUAGE", "es"),
        )
        return tts

    from pipecat.services.kokoro.tts import KokoroTTSService

    voice = os.getenv("KOKORO_VOICE", "ef_dora")
    speed = float(os.getenv("TTS_SPEED", "1.0"))
    tts = KokoroTTSService(
        settings=KokoroTTSService.Settings(
            voice=voice, language=Language.ES, speed=speed
        ),
    )
    logger.info(
        "TTS ready engine=kokoro voice={} language=ES speed={}", voice, speed
    )
    return tts


def _load_metadata() -> dict:
    return load_call_metadata()


def _daily_params():
    # Daily is optional; WebRTC must not import/load its native dependency.
    from pipecat.transports.daily.transport import DailyParams

    return DailyParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    )


transport_params = {
    "daily": _daily_params,
    "twilio": lambda: FastAPIWebsocketParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
    "webrtc": lambda: TransportParams(
        audio_in_enabled=True,
        audio_out_enabled=True,
    ),
}


async def run_bot(transport: BaseTransport, runner_args: RunnerArguments):
    require_config()
    logger.info("Starting clinica-vida agent on Pipecat")

    metadata = merge_call_metadata(_load_metadata(), runner_args)
    session, flow = build_session(metadata)

    whisper_model = os.getenv("WHISPER_MODEL", "base")
    stt = _build_stt()
    logger.info(
        "STT ready engine={} model={}",
        os.getenv("STT_ENGINE", "whisper-http"),
        whisper_model,
    )

    tts = _build_tts()
    deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

    async def speak(text: str) -> None:
        for chunk in split_tts_utterances(text):
            await tts.queue_frame(TTSSpeakFrame(chunk))

    llm_holder: dict = {}
    worker_holder: dict = {}
    hud = attach_hud(session, transport)

    async def on_phase(phase: str) -> None:
        """Swap system prompt + tools. Never call llm.set_settings (missing on DeepSeek)."""
        await hud.emit_phase(phase)
        llm = llm_holder.get("llm")
        ctx = llm_holder.get("context")
        ctrl = llm_holder.get("controller")
        if not llm or not ctrl or not ctx:
            return
        if phase == "negotiation":
            ctx.set_tools(ctrl.tools_for_phase("negotiation"))
            ctx.set_tool_choice(ctrl.tool_choice_for_phase("negotiation"))
            await llm.queue_frame(
                LLMUpdateSettingsFrame(
                    delta=DeepSeekLLMService.Settings(
                        system_instruction=ctrl.negotiation_system_prompt(),
                        thinking=_THINKING_OFF,
                        temperature=0.3,
                        max_tokens=220,
                    )
                )
            )
        elif phase == "done":
            ctx.set_tools([])
            ctx.set_tool_choice("none")
            worker = worker_holder.get("worker")
            if worker is not None:
                await worker.stop_when_done()

    controller = FlowController(session, flow, speak=speak, on_phase=on_phase)

    llm = BitbitDeepSeekLLMService(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        settings=DeepSeekLLMService.Settings(
            model=deepseek_model,
            system_instruction=controller.identity_system_prompt(),
            thinking=_THINKING_OFF,
            temperature=0.3,
            max_tokens=220,
        ),
    )
    llm_holder["llm"] = llm
    llm_holder["controller"] = controller

    context = LLMContext(
        tools=controller.tools_for_phase("identity"),
        tool_choice=controller.tool_choice_for_phase("identity"),
    )
    llm_holder["context"] = context
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
    )
    wire_text_input(transport, user_aggregator)

    pipeline = Pipeline(
        [
            transport.input(),
            ClosedSessionGate(session),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,
            enable_usage_metrics=True,
        ),
        observers=[hud],
        idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
        # One DeepSeek 400 must not tear down the whole WebRTC call.
        processor_unusable_policy=ProcessorUnusablePolicy.CONTINUE,
    )
    worker_holder["worker"] = worker
    runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
    await runner.add_workers(worker)

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        await hud.emit_session()
        logger.info(
            "Client connected call_id={} paciente={}",
            session.call_id,
            session.nombre_deudor,
        )
        apertura = render_template(
            flow["flow_graph"]["nodes"]["task.identity_verification"]["params"][
                "identity_identificacion_breve"
            ],
            session.as_template_vars(),
        )
        pregunta = f"¿Hablo con {session.nombre_deudor}?"
        greeting = f"{apertura} {pregunta}"
        await speak(greeting)
        # Do not also add_message here: TTS text frames already land in the
        # assistant aggregator — seeding again duplicated the greeting.

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        payload = session.result_payload()
        logger.info("Client disconnected result={}", payload)
        await runner.cancel()

    await runner.run()


async def bot(runner_args: RunnerArguments):
    load_dotenv(override=True)
    transport = await create_transport(runner_args, transport_params)
    await run_bot(transport, runner_args)


def main() -> None:
    load_dotenv(override=True)
    require_config()
    from pipecat.runner.run import main as pipecat_main

    install_studio_frontend()
    pipecat_main()


if __name__ == "__main__":
    main()
