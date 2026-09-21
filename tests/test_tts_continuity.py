"""Exercise Pipecat's real audio queue with a temporarily slow local model."""

import asyncio
import time
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import TTSStartedFrame, TTSStoppedFrame, TTSAudioRawFrame

from app.pipecat_runtime.config import RuntimeConfig
from app.pipecat_runtime.mlx_services import QwenMLXTTSService


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_start", [False, True])
async def test_slow_synthesis_does_not_end_audio_context_early(slow_start):
    class SlowEngine:
        config = RuntimeConfig(tts_prebuffer=0)
        calls = 0

        def remember_spoken(self, text):
            pass

        def speech(self, text):
            yield b"\x01\x00" * 100, 24000
            yield b"\x02\x00" * 100, 24000

        def next_pcm(self, generator):
            return next(generator, None)

        async def call(self, fn, *args):
            if fn == self.next_pcm:
                # Longer than the queue timeout, both before and between audio.
                if slow_start or self.calls:
                    await asyncio.sleep(0.12)
                self.calls += 1
            return fn(*args)

    service = QwenMLXTTSService(SlowEngine())
    service._sample_rate = 24000
    service._stop_frame_timeout_s = 0.06
    context_id = "slow-local-model"
    queue = asyncio.Queue()
    service._audio_contexts[context_id] = queue
    # Mock only downstream delivery and metrics, retaining the real queue
    # consumer and its timeout/stop behavior.
    service.push_frame = AsyncMock()
    for name in (
        "start_word_timestamps", "process_ttfa_metrics", "_apply_force_complete",
        "_maybe_reset_word_timestamps", "_record_context_audio_outcome",
    ):
        setattr(service, name, AsyncMock())
    await queue.put(TTSStartedFrame(context_id=context_id))
    consumer = asyncio.create_task(service._handle_audio_context(context_id))
    try:
        async for frame in service.run_tts("Una frase completa.", context_id):
            await queue.put(frame)
        await queue.put(TTSStoppedFrame(context_id=context_id))
        await queue.put(None)
        await asyncio.wait_for(consumer, timeout=1)
    finally:
        if not consumer.done():
            consumer.cancel()
            await asyncio.gather(consumer, return_exceptions=True)

    delivered = [call.args[0] for call in service.push_frame.await_args_list]
    assert [type(frame) for frame in delivered] == [
        TTSStartedFrame, TTSAudioRawFrame, TTSAudioRawFrame, TTSStoppedFrame,
    ]
    assert delivered[2].audio == b"\x02\x00" * 100


@pytest.mark.asyncio
@pytest.mark.parametrize("reserve", [0, 0.16, 1.2])
async def test_prebuffer_preserves_audio_and_absorbs_a_generation_stall(reserve):
    class BurstyEngine:
        config = RuntimeConfig(tts_prebuffer=reserve)
        generated = 0
        clock = 0.0
        closed = False
        playback_until = 0.0

        def remember_spoken(self, text):
            pass

        def speech(self, text):
            try:
                for delay in [0.01, 0.12, 0.01, 0.01]:
                    self.clock += delay
                    self.generated += 1
                    yield bytes([self.generated, 0]) * 1920, 24000  # 80 ms
            finally:
                self.closed = True

        def next_pcm(self, generator):
            return next(generator, None)

        async def call(self, fn, *args):
            return fn(*args)

    engine = BurstyEngine()
    service = QwenMLXTTSService(engine)
    service._sample_rate = 24000
    frames = []
    playback_until = None
    gaps = 0.0
    async for frame in service.run_tts("Una frase completa", "buffer-test"):
        assert isinstance(frame, TTSAudioRawFrame)
        if playback_until is None:
            playback_until = engine.clock
            # Streaming still begins before all chunks when threshold allows it.
            assert engine.generated == {0: 1, 0.16: 2, 1.2: 4}[reserve]
        gaps += max(0, engine.clock - playback_until)
        playback_until = max(playback_until, engine.clock) + len(frame.audio) / 48000
        frames.append(frame.audio)
    assert b"".join(frames) == b"".join(bytes([i, 0]) * 1920 for i in range(1, 5))
    assert engine.closed
    assert gaps == pytest.approx(0.04 if reserve == 0 else 0)


@pytest.mark.asyncio
async def test_fast_gpu_drains_before_releasing_tts_context():
    """GPU ahead of realtime must hold the context until estimated playout ends."""

    class FastEngine:
        config = RuntimeConfig(tts_prebuffer=0)
        playback_until = 0.0
        closed = False

        def remember_spoken(self, text):
            pass

        def speech(self, text):
            try:
                yield b"\x01\x00" * 4800, 24000
                yield b"\x02\x00" * 4800, 24000
            finally:
                self.closed = True

        def next_pcm(self, generator):
            return next(generator, None)

        async def call(self, fn, *args):
            return fn(*args)

    engine = FastEngine()
    service = QwenMLXTTSService(engine)
    service._sample_rate = 24000
    service._stop_frame_timeout_s = 30.0
    started = time.perf_counter()
    frames = [frame async for frame in service.run_tts("hola", "drain-test")]
    elapsed = time.perf_counter() - started
    assert len(frames) == 2
    assert engine.closed
    assert elapsed >= 0.35



@pytest.mark.parametrize("reserve", [-1, 6, float("nan")])
def test_invalid_prebuffer_is_rejected(reserve):
    with pytest.raises(ValueError, match="TTS_PREBUFFER_SECONDS"):
        replace(RuntimeConfig(), tts_prebuffer=reserve).validate(require_llm=False)
