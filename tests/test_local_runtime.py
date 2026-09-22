from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest
from pipecat.frames.frames import (
    ErrorFrame,
    InputAudioRawFrame,
    TTSAudioRawFrame,
    TranscriptionFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection

from app.pipecat_runtime.config import RuntimeConfig, TTS_BASE, TTS_PRESET
from app.pipecat_runtime.deepseek_llm import BitbitDeepSeekLLMService
from app.pipecat_runtime.flow_data import build_session
from app.pipecat_runtime.mac_bot import ClosedSessionGate, build_llm
from app.pipecat_runtime.mlx_services import MLXAudioEngine, MLXSTTService, QwenMLXTTSService
from app.pipecat_runtime.tools import FlowController
from pipecat.services.openai.llm import OpenAILLMService


@pytest.mark.parametrize(
    "url", ["https://api.openai.com/v1", "http://example.com/v1", "file:///tmp/a"]
)
def test_rejects_remote_mlx_llm(url):
    with pytest.raises(ValueError):
        replace(RuntimeConfig(), llm_provider="mlx", llm_url=url).validate(
            require_llm=False
        )


def test_clone_requires_real_file_and_transcript(tmp_path):
    config = replace(RuntimeConfig(), voice_mode="clone")
    with pytest.raises(ValueError):
        config.validate(require_llm=False)
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"test")
    config = replace(config, reference_audio=str(audio), reference_text="Hola")
    config.validate(require_llm=False)
    assert config.tts_model == TTS_BASE
    assert RuntimeConfig().tts_model == TTS_PRESET


def test_clinic_tools_serialize_without_internal_params():
    session, flow = build_session()
    controller = FlowController(session, flow, speak=AsyncMock())
    context = LLMContext(tools=[controller.agendar_cita, controller.finalizar])
    schemas = [tool.to_default_dict() for tool in context.tools.standard_tools]
    assert schemas[0]["name"] == "agendar_cita"
    assert "fecha_iso" in schemas[0]["parameters"]["properties"]
    assert "params" not in schemas[0]["parameters"]["properties"]


def test_llm_default_is_deepseek():
    service = build_llm(
        RuntimeConfig(deepseek_api_key="sk-test"),
        "Prompt",
    )
    assert isinstance(service, BitbitDeepSeekLLMService)


def test_llm_mlx_uses_local_endpoint_and_serial_tools():
    service = build_llm(
        RuntimeConfig(llm_provider="mlx"),
        "Prompt",
    )
    assert isinstance(service, OpenAILLMService)
    assert str(service._client.base_url).startswith("http://127.0.0.1:8080/")
    assert service._run_in_parallel is False


def test_stt_skips_while_tts_busy_and_cooldown():
    import time

    engine = MLXAudioEngine(RuntimeConfig())
    engine.tts_busy = True
    assert engine.transcribe(b"not-a-wav") == ""
    engine.tts_busy = False
    engine.playback_ended_at = time.monotonic()
    assert engine.transcribe(b"not-a-wav") == ""


def test_stt_sanitize_drops_hallucinations():
    assert MLXAudioEngine._sanitize_transcript("Noticias desde Berlín.") == ""
    assert MLXAudioEngine._sanitize_transcript("Obvious service. Yeah, so") == ""
    assert MLXAudioEngine._sanitize_transcript("Ehh...") == ""
    assert MLXAudioEngine._sanitize_transcript("sí, soy Juan") == "sí, soy Juan"
    opening = (
        "Hola Carla Méndez, le habla Ana de BioAnalyze. "
        "Usted presenta un adeudo de dieciocho mil quinientos."
    )
    assert MLXAudioEngine._sanitize_transcript("¿Qué pasa si te trago algo?", opening) == ""
    assert MLXAudioEngine._sanitize_transcript("Así que, se te da un...", opening) == ""
    assert MLXAudioEngine._sanitize_transcript("No, " * 40, opening) == ""
    assert MLXAudioEngine._sanitize_transcript(
        "como lo que yo siento es aquí y entonces uno se te da la cabeza, el corazón",
        opening,
    ) == ""
    assert MLXAudioEngine._sanitize_transcript("no me alcanza el total", opening)
    # Identidad: no tirar negaciones / terceros (regresión log 19:07)
    assert (
        MLXAudioEngine._sanitize_transcript("No, no, ella no se encuentra en este momento.")
        == "No, no, ella no se encuentra en este momento."
    )
    assert MLXAudioEngine._sanitize_transcript("No, he equivocado.") == "No, he equivocado."
    assert (
        MLXAudioEngine._sanitize_transcript(
            "me repetís para qué me estás llamando."
        )
        == "me repetís para qué me estás llamando."
    )
    assert (
        MLXAudioEngine._sanitize_transcript(
            "Me he repetido, ¿dónde le estás llamando?"
        )
        == "Me he repetido, ¿dónde le estás llamando?"
    )
    assert (
        MLXAudioEngine._sanitize_transcript("¿De dónde me está llamando?")
        == "¿De dónde me está llamando?"
    )
    assert MLXAudioEngine._sanitize_transcript("¿Qué pasó?") == "¿Qué pasó?"
    assert MLXAudioEngine._sanitize_transcript("no te escucho") == "no te escucho"
    assert (
        MLXAudioEngine._sanitize_transcript("No, no, he equivocado.")
        == "No, no, he equivocado."
    )
    assert MLXAudioEngine._sanitize_transcript("sí, correcto") == "sí, correcto"
    # Log 10:09: micrófono descartado como off-domain/eco; el HUD tipado sí avanzaba.
    assert MLXAudioEngine._sanitize_transcript("ok", opening) == "ok"
    assert (
        MLXAudioEngine._sanitize_transcript(
            "Dale comentar como podemos hacer", opening
        )
        == "Dale comentar como podemos hacer"
    )
    assert (
        MLXAudioEngine._sanitize_transcript("Hola, ¿me escuchás?", opening)
        == "Hola, ¿me escuchás?"
    )
    assert (
        MLXAudioEngine._sanitize_transcript("No, no, no, me des imposible.", opening)
        == "No, no, no, me des imposible."
    )
    # Eco puro: solo palabras del TTS.
    assert MLXAudioEngine._sanitize_transcript("adeudo dieciocho", opening) == ""


def test_split_tts_utterances_breaks_long_script():
    from app.utils.templates import split_tts_utterances

    text = (
        "Hola Carla Méndez, le habla Ana, Agente Virtual del área de Servicio y "
        "seguimiento de venta de BioAnalyze. Le informo que esta llamada está siendo "
        "grabada para fines de calidad. Le llamo para apoyarle a cerrar la oferta su "
        "cuenta. De acuerdo con nuestro sistema, usted presenta un adeudo de "
        "dieciocho mil quinientos. Revisemos juntos la mejor forma de cubrirlo."
    )
    chunks = split_tts_utterances(text)
    assert chunks == [text]
    # Streaming Mac: paquetes cortos → primer audio sin esperar el guion entero.
    packs = split_tts_utterances(text, max_chars=140)
    assert len(packs) >= 3
    assert all(len(p) <= 200 for p in packs)
    assert "".join(packs).replace(" ", "") == text.replace(" ", "")
    huge = ". ".join([text] * 4)
    split = split_tts_utterances(huge)
    assert len(split) > 1
    assert all(len(chunk) <= 800 for chunk in split)
    assert "dieciocho mil quinientos" in " ".join(split)


def test_mac_turn_start_ignores_fillers_and_disables_barge_in():
    from app.pipecat_runtime.turn_start import (
        interruption_word_threshold,
        is_turn_filler,
    )

    assert is_turn_filler("Ehh...")
    assert is_turn_filler("mmm")
    assert not is_turn_filler("sí")
    assert not is_turn_filler("no")
    assert not is_turn_filler("¿De parte de quién?")
    assert interruption_word_threshold(bot_speaking=True, min_words=0) == 0
    assert interruption_word_threshold(bot_speaking=False, min_words=0) == 1


@pytest.mark.asyncio
async def test_esperar_titular_exige_evidencia_de_pase():
    from unittest.mock import AsyncMock
    from types import SimpleNamespace
    from app.pipecat_runtime.flow_data import build_session
    from app.pipecat_runtime.tools import FlowController

    spoken = []

    async def speak(t):
        spoken.append(t)

    session, flow = build_session({"name": "Juan Pérez"})
    ctrl = FlowController(session, flow, speak=speak)
    cb = AsyncMock()
    params = SimpleNamespace(result_callback=cb)
    await ctrl.esperar_titular(params, evidencia="hola ruido")
    assert any("hablo con" in s.lower() for s in spoken)
    assert cb.await_args.args[0].get("rejected") is True


class FakeEngine:
    def __init__(self):
        self.config = RuntimeConfig()
        self.closed = False
        self.generated = 0
        self.last_spoken = ""
        self.tts_busy = False
        self.tts_ended_at = 0.0

    def remember_spoken(self, text: str) -> None:
        self.last_spoken = text or ""

    def stt_is_blocked(self):
        return self.stt_block_reason() != "open"

    def stt_block_reason(self) -> str:
        return "tts_busy" if self.tts_busy else "open"

    async def call(self, fn, *args):
        return fn(*args)

    def speech(self, text):
        try:
            for _ in range(3):
                self.generated += 1
                yield SimpleNamespace(audio=np.ones(100), sample_rate=24000)
        finally:
            self.closed = True

    def next_pcm(self, generator):
        return MLXAudioEngine.next_pcm(self, generator)


def test_pcm_clips_and_streams_incrementally():
    engine = MLXAudioEngine(RuntimeConfig())
    generator = iter(
        [SimpleNamespace(audio=np.array([-2.0, 0.0, 2.0]), sample_rate=24000)]
    )
    data, rate = engine.next_pcm(generator)
    assert np.frombuffer(data, dtype="<i2").tolist() == [-32767, 0, 32767]
    assert rate == 24000
    assert engine.next_pcm(generator) is None


def test_pcm_applies_speed_and_volume():
    engine = MLXAudioEngine(RuntimeConfig(tts_speed=2.0, tts_volume=0.5))
    samples = np.ones(100, dtype=np.float32)
    generator = iter([SimpleNamespace(audio=samples, sample_rate=24000)])
    data, rate = engine.next_pcm(generator)
    out = np.frombuffer(data, dtype="<i2")
    assert rate == 24000
    assert len(out) == 50
    assert int(out[0]) == 16383


@pytest.mark.asyncio
async def test_tts_yields_before_whole_utterance_and_closes_on_interrupt():
    engine = FakeEngine()
    engine.config = replace(engine.config, tts_prebuffer=0)
    service = QwenMLXTTSService(engine)
    service._sample_rate = 24000
    stream = service.run_tts("Hola", "test-context")
    frame = await anext(stream)
    assert isinstance(frame, TTSAudioRawFrame)
    assert frame.context_id == "test-context"
    assert engine.generated == 1
    await stream.aclose()
    assert engine.closed
    assert engine.generated == 1


@pytest.mark.asyncio
async def test_tts_error_is_exposed():
    engine = FakeEngine()

    def broken(text):
        yield SimpleNamespace(audio=np.ones(10), sample_rate=16000)

    engine.speech = broken
    service = QwenMLXTTSService(engine)
    service._sample_rate = 24000
    frames = [f async for f in service.run_tts("Hola", "test")]
    assert len(frames) == 1 and isinstance(frames[0], ErrorFrame)


@pytest.mark.asyncio
async def test_stt_passes_final_spanish_transcript():
    engine = FakeEngine()
    engine.transcribe = lambda audio: "Quiero una cita mañana."
    service = MLXSTTService(engine)
    frames = [f async for f in service.run_stt(b"fixture")]
    assert len(frames) == 1 and isinstance(frames[0], TranscriptionFrame)
    assert frames[0].text == "Quiero una cita mañana."


@pytest.mark.asyncio
async def test_done_gate_stops_new_audio_but_allows_control_frames():
    gate = ClosedSessionGate(SimpleNamespace(phase="done"))
    gate.push_frame = AsyncMock()
    audio = InputAudioRawFrame(b"\0\0", 16000, 1)
    await gate.process_frame(audio, FrameDirection.DOWNSTREAM)
    gate.push_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_executor_closes_after_failed_load():
    engine = MLXAudioEngine(RuntimeConfig())
    await engine.close()
    await engine.close()
    with pytest.raises(RuntimeError):
        await engine.call(lambda: None)
