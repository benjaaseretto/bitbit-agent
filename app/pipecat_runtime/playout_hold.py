"""Keep STT muted while Kokoro audio is in flight.

Do not delay TTSStoppedFrame. Pipecat's output transport flushes the last
PCM chunk only when it sees TTSStopped; holding that frame leaves the tail
in `_audio_buffer` and the WebRTC track fills the hole with auto-silence
("se corta"). TTSStopped must sit behind the audio on the transport queue.
"""
from __future__ import annotations

import time

from pipecat.frames.frames import (
    Frame,
    InterruptionFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from app.pipecat_runtime.audio_map import map_log


class PlayoutHoldTTSStopped(FrameProcessor):
    """Track estimated playout for STT mute; forward TTSStopped immediately."""

    def __init__(self, engine=None):
        super().__init__()
        self._engine = engine
        self._playout_until = 0.0
        self._pcm_frames = 0
        self._pcm_seconds = 0.0
        self._utterance_started = 0.0

    def _remaining(self) -> float:
        return max(0.0, self._playout_until - time.monotonic())

    def _note_audio(self, frame: TTSAudioRawFrame) -> None:
        channels = getattr(frame, "num_channels", None) or 1
        rate = frame.sample_rate or 24000
        seconds = len(frame.audio) / max(rate * 2 * channels, 1)
        now = time.monotonic()
        if self._playout_until < now:
            self._playout_until = now
        self._playout_until += seconds
        self._pcm_frames += 1
        self._pcm_seconds += seconds
        if self._engine is not None:
            self._engine.playback_until = self._playout_until
        map_log(
            "hold.pcm",
            frame=self._pcm_frames,
            bytes=len(frame.audio),
            rate=rate,
            chunk_s=f"{seconds:.3f}",
            total_s=f"{self._pcm_seconds:.3f}",
            remain_s=f"{self._remaining():.3f}",
            ctx=getattr(frame, "context_id", None),
        )

    def _set_busy(self, busy: bool) -> None:
        if self._engine is None:
            return
        self._engine.tts_busy = busy
        if not busy:
            return
        now = time.monotonic()
        if self._engine.playback_until < now:
            self._engine.playback_until = now + 0.5

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, InterruptionFrame):
            map_log(
                "hold.interrupt",
                remain_s=f"{self._remaining():.3f}",
                pcm_s=f"{self._pcm_seconds:.3f}",
                frames=self._pcm_frames,
            )
            self._playout_until = 0.0
            self._pcm_frames = 0
            self._pcm_seconds = 0.0
            self._set_busy(False)
            if self._engine is not None:
                self._engine.playback_until = 0.0
        elif isinstance(frame, TTSStartedFrame) and direction == FrameDirection.DOWNSTREAM:
            self._pcm_frames = 0
            self._pcm_seconds = 0.0
            self._utterance_started = time.monotonic()
            self._set_busy(True)
            map_log("hold.started", ctx=getattr(frame, "context_id", None))
        elif isinstance(frame, TTSAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            self._set_busy(True)

        await super().process_frame(frame, direction)

        if isinstance(frame, TTSAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            self._note_audio(frame)
        elif isinstance(frame, TTSStoppedFrame) and direction == FrameDirection.DOWNSTREAM:
            elapsed = (
                time.monotonic() - self._utterance_started if self._utterance_started else 0.0
            )
            map_log(
                "hold.stopped",
                ctx=getattr(frame, "context_id", None),
                pcm_s=f"{self._pcm_seconds:.3f}",
                frames=self._pcm_frames,
                remain_s=f"{self._remaining():.3f}",
                since_start_s=f"{elapsed:.3f}",
            )

        await self.push_frame(frame, direction)
