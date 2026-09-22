"""Structured AUDIO MAP logs. Grep: `MAP `."""
from __future__ import annotations

from collections import deque

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    ErrorFrame,
    FunctionCallInProgressFrame,
    InterruptionFrame,
    InterruptionTaskFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    OutputAudioRawFrame,
    SpeechOutputAudioRawFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    TTSTextFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.metrics.metrics import TTFBMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection


def map_log(layer: str, **fields) -> None:
    parts = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("MAP {} {}", layer, parts)


def _name(proc) -> str:
    return getattr(proc, "name", None) or type(proc).__name__


def _pcm_seconds(frame) -> float:
    audio = getattr(frame, "audio", b"") or b""
    rate = getattr(frame, "sample_rate", None) or 24000
    channels = getattr(frame, "num_channels", None) or 1
    return len(audio) / max(rate * 2 * channels, 1)


class AudioMapObserver(BaseObserver):
    """One MAP line per interesting frame as it crosses the pipeline."""

    def __init__(self):
        super().__init__()
        self._seen: set[int] = set()
        self._seen_order: deque[int] = deque(maxlen=800)
        self._out_s = 0.0
        self._out_n = 0
        self._last_out_log = 0.0
        self._llm_chars = 0
        self._tts_text_chars = 0

    def _mark(self, frame_id: int) -> bool:
        if frame_id in self._seen:
            return False
        self._seen.add(frame_id)
        self._seen_order.append(frame_id)
        if len(self._seen) > len(self._seen_order):
            self._seen = set(self._seen_order)
        return True

    def _note_output(self, frame) -> None:
        seconds = _pcm_seconds(frame)
        self._out_s += seconds
        self._out_n += 1
        if self._out_s - self._last_out_log < 1.0 and seconds < 0.4:
            return
        self._last_out_log = self._out_s
        map_log(
            "transport.pcm",
            type=type(frame).__name__,
            chunk_s=f"{seconds:.3f}",
            total_s=f"{self._out_s:.3f}",
            frames=self._out_n,
            bytes=len(getattr(frame, "audio", b"") or b""),
            rate=getattr(frame, "sample_rate", None),
        )

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        frame_id = getattr(frame, "id", None)
        if frame_id is not None and not self._mark(frame_id):
            return
        src = _name(data.source)
        dst = _name(data.destination)
        direction = getattr(data.direction, "name", data.direction)

        if isinstance(frame, (OutputAudioRawFrame, SpeechOutputAudioRawFrame)):
            if data.direction == FrameDirection.DOWNSTREAM:
                self._note_output(frame)
            return

        if isinstance(frame, TTSAudioRawFrame):
            map_log(
                "frame.tts_pcm",
                src=src,
                dst=dst,
                dir=direction,
                bytes=len(frame.audio or b""),
                s=f"{_pcm_seconds(frame):.3f}",
                rate=frame.sample_rate,
                ctx=getattr(frame, "context_id", None),
            )
            return

        if isinstance(frame, TTSStartedFrame):
            self._out_s = 0.0
            self._out_n = 0
            self._last_out_log = 0.0
            map_log("frame.tts_started", src=src, dst=dst, ctx=getattr(frame, "context_id", None))
            return

        if isinstance(frame, TTSStoppedFrame):
            map_log(
                "frame.tts_stopped",
                src=src,
                dst=dst,
                ctx=getattr(frame, "context_id", None),
                transport_s=f"{self._out_s:.3f}",
                transport_frames=self._out_n,
            )
            return

        if isinstance(frame, TTSSpeakFrame):
            text = frame.text or ""
            map_log(
                "frame.speak",
                src=src,
                chars=len(text),
                preview=repr(text[:72] + ("…" if len(text) > 72 else "")),
            )
            return

        if isinstance(frame, TTSTextFrame):
            chunk = frame.text or ""
            self._tts_text_chars += len(chunk)
            map_log(
                "frame.tts_text",
                src=src,
                chunk=len(chunk),
                total=self._tts_text_chars,
                preview=repr(chunk[:48]),
            )
            return

        if isinstance(frame, BotStartedSpeakingFrame):
            map_log("frame.bot_started", src=src, dst=dst)
            return

        if isinstance(frame, BotStoppedSpeakingFrame):
            map_log(
                "frame.bot_stopped",
                src=src,
                dst=dst,
                transport_s=f"{self._out_s:.3f}",
                transport_frames=self._out_n,
            )
            return

        if isinstance(frame, (InterruptionFrame, InterruptionTaskFrame)):
            map_log(
                "frame.interrupt",
                type=type(frame).__name__,
                src=src,
                dst=dst,
                dir=direction,
                transport_s=f"{self._out_s:.3f}",
            )
            return

        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            map_log("frame.user_start", type=type(frame).__name__, src=src)
            return

        if isinstance(frame, (VADUserStoppedSpeakingFrame, UserStoppedSpeakingFrame)):
            map_log("frame.user_stop", type=type(frame).__name__, src=src)
            return

        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            map_log(
                "frame.transcript",
                src=src,
                chars=len(text),
                finalized=getattr(frame, "finalized", None),
                text=repr(text[:80]),
            )
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            self._llm_chars = 0
            map_log("frame.llm_start", src=src)
            return

        if isinstance(frame, LLMTextFrame):
            chunk = frame.text or ""
            self._llm_chars += len(chunk)
            if self._llm_chars <= len(chunk) or self._llm_chars % 80 < len(chunk):
                map_log("frame.llm_text", src=src, total=self._llm_chars, preview=repr(chunk[:48]))
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            map_log("frame.llm_end", src=src, chars=self._llm_chars)
            return

        if isinstance(frame, FunctionCallInProgressFrame):
            map_log(
                "frame.tool",
                src=src,
                name=getattr(frame, "function_name", None),
                tool=getattr(frame, "tool_name", None),
            )
            return

        if isinstance(frame, ErrorFrame):
            map_log(
                "frame.error",
                src=src,
                fatal=getattr(frame, "fatal", None),
                error=repr(str(getattr(frame, "error", frame))[:160]),
            )
            return

        if isinstance(frame, MetricsFrame) and data.direction == FrameDirection.DOWNSTREAM:
            for item in frame.data or []:
                if isinstance(item, TTFBMetricsData):
                    map_log(
                        "frame.ttfb",
                        processor=getattr(item, "processor", None),
                        ms=f"{float(item.value) * 1000:.0f}",
                    )
            return
