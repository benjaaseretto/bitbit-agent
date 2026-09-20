"""Pipecat Mac: Parakeet/Qwen-TTS (MLX) + DeepSeek Flash (default LLM)."""
from __future__ import annotations

import asyncio
import os

import httpx
from loguru import logger
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.frames.frames import InputAudioRawFrame, LLMUpdateSettingsFrame, TTSSpeakFrame
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
from pipecat.transports.base_transport import TransportParams
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.workers.runner import WorkerRunner

from app.orchestrator import FlowController, build_session
from app.pipecat_runtime.config import RuntimeConfig
from app.pipecat_runtime.deepseek_llm import BitbitDeepSeekLLMService
from app.pipecat_runtime.hud import attach_hud, wire_text_input
from app.pipecat_runtime.mlx_services import MLXAudioEngine, MLXSTTService, QwenMLXTTSService
from app.pipecat_runtime.studio import install_studio_frontend, merge_call_metadata
from app.pipecat_runtime.turn_start import MacMinWordsUserTurnStartStrategy
from app.utils.call_metadata import load_call_metadata
from app.utils.templates import render_template, split_tts_utterances

_THINKING_OFF = DeepSeekLLMService.ThinkingConfig(type="disabled")

_engine = None
_active_call = False


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
    config = RuntimeConfig.from_env()
    await check_llm(config)
    session, flow = build_session(merge_call_metadata(load_metadata(), runner_args))
    _active_call = True
    engine = _engine or MLXAudioEngine(config)
    owned = _engine is None
    worker_holder: dict = {}
    try:
        if owned:
            await engine.load()
            await engine.warmup()
        stt = MLXSTTService(engine)
        tts = QwenMLXTTSService(engine)
        logger.info(
            "TTS ready engine=qwen-mlx voice={} speed={} volume={}",
            config.voice,
            config.tts_speed,
            config.tts_volume,
        )
        if config.voice_mode == "preset":
            logger.warning(
                "VOICE mode=preset: voz de prueba; pendiente referencia humana en español"
            )

        async def speak(text):
            for chunk in split_tts_utterances(text):
                await tts.queue_frame(TTSSpeakFrame(chunk))

        hud = attach_hud(session, transport)

        async def on_phase(phase):
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

        controller = FlowController(session, flow, speak=speak, on_phase=on_phase)
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
                        start_secs=float(os.getenv("VAD_START_SECS", "0.35")),
                        stop_secs=float(os.getenv("VAD_STOP_SECS", "0.45")),
                    )
                ),
                user_turn_strategies=UserTurnStrategies(
                    start=[
                        MacMinWordsUserTurnStartStrategy(
                            min_words=int(os.getenv("INTERRUPTION_MIN_WORDS", "0")),
                            use_interim=False,
                        )
                    ]
                ),
            ),
        )
        wire_text_input(transport, user)
        latency = UserBotLatencyObserver()

        @latency.event_handler("on_latency_measured")
        async def measured(observer, seconds):
            logger.info("LATENCY user_to_audio_ms={:.0f}", seconds * 1000)

        pipeline = Pipeline(
            [
                transport.input(),
                ClosedSessionGate(session),
                stt,
                user,
                llm,
                tts,
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
            observers=[latency, hud],
            idle_timeout_secs=runner_args.pipeline_idle_timeout_secs,
            processor_unusable_policy=ProcessorUnusablePolicy.CONTINUE,
        )
        worker_holder["worker"] = worker
        runner = WorkerRunner(handle_sigint=runner_args.handle_sigint)
        await runner.add_workers(worker)

        @transport.event_handler("on_client_connected")
        async def connected(transport, client):
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
            logger.info("Session finished status={}", session.final_status)
            await runner.cancel()

        await runner.run()
    finally:
        _active_call = False
        if owned:
            await engine.close()


async def bot(runner_args: RunnerArguments):
    transport = await create_transport(
        runner_args,
        {
            "webrtc": lambda: TransportParams(
                audio_in_enabled=True, audio_out_enabled=True
            )
        },
    )
    await run_bot(transport, runner_args)


def main():
    global _engine
    config = RuntimeConfig.from_env()
    _engine = MLXAudioEngine(config)

    async def prepare():
        await check_llm(config)
        await _engine.load()
        await _engine.warmup()

    from pipecat.runner.run import main as run

    try:
        install_studio_frontend()
        asyncio.run(prepare())
        run()
    finally:
        asyncio.run(_engine.close())


if __name__ == "__main__":
    main()
