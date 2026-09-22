"""PlayoutHoldTTSStopped forwards TTSStopped so the transport can flush PCM."""

from types import SimpleNamespace

import pytest
from pipecat.frames.frames import TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection

from app.pipecat_runtime.playout_hold import PlayoutHoldTTSStopped


def _pcm(seconds: float) -> bytes:
    return b"\x00\x00" * int(24000 * seconds)


@pytest.mark.asyncio
async def test_stop_is_forwarded_immediately_behind_audio():
    engine = SimpleNamespace(playback_until=0.0, tts_busy=False)
    proc = PlayoutHoldTTSStopped(engine)
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(type(frame))

    proc.push_frame = capture
    downstream = FrameDirection.DOWNSTREAM
    await proc.process_frame(TTSAudioRawFrame(_pcm(0.2), 24000, 1), downstream)
    await proc.process_frame(TTSStoppedFrame(), downstream)

    assert pushed == [TTSAudioRawFrame, TTSStoppedFrame]
    assert engine.tts_busy is True
    assert engine.playback_until > 0


@pytest.mark.asyncio
async def test_second_utterance_is_not_blocked_by_first_stop():
    proc = PlayoutHoldTTSStopped()
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(type(frame))

    proc.push_frame = capture
    downstream = FrameDirection.DOWNSTREAM
    await proc.process_frame(TTSAudioRawFrame(_pcm(0.2), 24000, 1), downstream)
    await proc.process_frame(TTSStoppedFrame(), downstream)
    await proc.process_frame(TTSAudioRawFrame(_pcm(0.2), 24000, 1), downstream)
    await proc.process_frame(TTSStoppedFrame(), downstream)

    assert pushed == [
        TTSAudioRawFrame,
        TTSStoppedFrame,
        TTSAudioRawFrame,
        TTSStoppedFrame,
    ]


@pytest.mark.asyncio
async def test_tts_started_marks_busy_before_pcm():
    engine = SimpleNamespace(tts_busy=False, playback_until=0.0)
    proc = PlayoutHoldTTSStopped(engine)
    pushed = []

    async def capture(frame, direction=FrameDirection.DOWNSTREAM):
        pushed.append(type(frame))

    proc.push_frame = capture
    await proc.process_frame(TTSStartedFrame(), FrameDirection.DOWNSTREAM)
    assert engine.tts_busy is True
    assert pushed == [TTSStartedFrame]
