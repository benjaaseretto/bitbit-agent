"""Hold TTSStopped until estimated WebRTC playout catches up.

Kokoro dumps PCM and then TTSStopped immediately. If this processor sleeps
inside process_frame, the next utterance's audio sits behind that sleep.
The output transport then sees an empty queue, fires BotStoppedSpeaking on
its 3s fallback, and drops whatever is still buffered ("se corta").

Audio is forwarded immediately. TTSStopped is released later, on a task, and
a following utterance cancels that release so both clips stay in one playout.
"""
from __future__ import annotations

import asyncio
import time

from loguru import logger
from pipecat.frames.frames import Frame, InterruptionFrame, TTSAudioRawFrame, TTSStoppedFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor


class PlayoutHoldTTSStopped(FrameProcessor):
    """Delay TTSStoppedFrame until wall-clock matches queued audio duration."""

    def __init__(self, engine=None):
        super().__init__()
        self._engine = engine
        self._playout_until = 0.0
        self._generation = 0
        self._stop_task: asyncio.Task | None = None

    def _note_audio(self, frame: TTSAudioRawFrame) -> None:
        channels = getattr(frame, "num_channels", None) or 1
        rate = frame.sample_rate or 24000
        seconds = len(frame.audio) / max(rate * 2 * channels, 1)
        now = time.monotonic()
        if self._playout_until < now:
            self._playout_until = now
        self._playout_until += seconds
        if self._engine is not None:
            self._engine.playback_until = self._playout_until

    def _invalidate_stop(self) -> None:
        """Drop a pending TTSStopped so it cannot land in front of new audio."""
        self._generation += 1
        task = self._stop_task
        self._stop_task = None
        if task is not None and not task.done():
            task.cancel()

    async def _release_stop(
        self, generation: int, frame: TTSStoppedFrame, direction: FrameDirection, delay: float
    ) -> None:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if generation != self._generation:
            return
        self._playout_until = 0.0
        self._stop_task = None
        await self.push_frame(frame, direction)

    async def cleanup(self) -> None:
        self._invalidate_stop()
        self._playout_until = 0.0
        await super().cleanup()

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Cancel before the first await. Otherwise the pending release runs
        # while this frame is still queued and pushes TTSStopped first.
        if isinstance(frame, InterruptionFrame):
            self._invalidate_stop()
            self._playout_until = 0.0
            if self._engine is not None:
                self._engine.playback_until = 0.0
        elif isinstance(frame, TTSAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            self._invalidate_stop()

        await super().process_frame(frame, direction)

        if isinstance(frame, InterruptionFrame):
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            self._note_audio(frame)
            await self.push_frame(frame, direction)
            return

        if isinstance(frame, TTSStoppedFrame) and direction == FrameDirection.DOWNSTREAM:
            delay = self._playout_until - time.monotonic()
            if delay > 0.05:
                logger.info("AUDIO hold_tts_stopped_s={:.2f}", delay)
                self._generation += 1
                generation = self._generation
                self._stop_task = asyncio.create_task(
                    self._release_stop(generation, frame, direction, delay + 0.05)
                )
                return
            self._playout_until = 0.0
            await self.push_frame(frame, direction)
            return

        await self.push_frame(frame, direction)
