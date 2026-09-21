"""PlayoutHoldTTSStopped delays TTSStopped until estimated audio duration elapses."""

import asyncio
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import TTSAudioRawFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection

from app.pipecat_runtime.playout_hold import PlayoutHoldTTSStopped


def _pcm(seconds: float) -> bytes:
    return b"\x00\x00" * int(24000 * seconds)


@pytest.mark.asyncio
async def test_hold_delays_tts_stopped_until_playout(monkeypatch):
    engine = SimpleNamespace(playback_until=0.0)
    proc = PlayoutHoldTTSStopped(engine)
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(frame)

    proc.push_frame = capture
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    await proc.process_frame(
        TTSAudioRawFrame(_pcm(0.2), 24000, 1), FrameDirection.DOWNSTREAM
    )
    await proc.process_frame(TTSStoppedFrame(), FrameDirection.DOWNSTREAM)
    assert proc._stop_task is not None
    await proc._stop_task

    assert isinstance(pushed[0], TTSAudioRawFrame)
    assert isinstance(pushed[1], TTSStoppedFrame)
    assert sleeps and sleeps[0] >= 0.2


@pytest.mark.asyncio
async def test_next_utterance_audio_is_not_blocked_by_hold(monkeypatch):
    proc = PlayoutHoldTTSStopped()
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(type(frame))

    proc.push_frame = capture

    async def fake_sleep(seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    downstream = FrameDirection.DOWNSTREAM
    await proc.process_frame(TTSAudioRawFrame(_pcm(0.2), 24000, 1), downstream)
    await proc.process_frame(TTSStoppedFrame(), downstream)
    await proc.process_frame(TTSAudioRawFrame(_pcm(0.2), 24000, 1), downstream)
    await proc.process_frame(TTSStoppedFrame(), downstream)
    assert proc._stop_task is not None
    await proc._stop_task

    assert pushed == [
        TTSAudioRawFrame,
        TTSAudioRawFrame,
        TTSStoppedFrame,
    ]
