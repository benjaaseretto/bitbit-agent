"""Puente pipeline → data channel: transcripción, estado y métricas para el HUD."""
from __future__ import annotations

import time
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from loguru import logger
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    FunctionCallInProgressFrame,
    InterimTranscriptionFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    MetricsFrame,
    OutputTransportMessageFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
)
from pipecat.metrics.metrics import LLMUsageMetricsData, TTFBMetricsData, TTSUsageMetricsData
from pipecat.observers.base_observer import BaseObserver, FramePushed
from pipecat.processors.frame_processor import FrameDirection

from app.session.call_session import CallSession

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


class HudObserver(BaseObserver):
    """Observa frames y los manda al cliente por el data channel de SmallWebRTC."""

    def __init__(self, session: CallSession):
        super().__init__()
        self._session = session
        self._emit_fn: EmitFn | None = None
        self._seen: set[int] = set()
        self._seen_order: deque[int] = deque(maxlen=400)
        self._bot_buf = ""
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._tts_chars = 0
        self._user_stop_at: float | None = None

    def bind(self, emit: EmitFn) -> None:
        self._emit_fn = emit

    async def emit_session(self) -> None:
        catalog_name = self._session.nombre_empresa
        await self._emit(
            {
                "type": "session",
                "session_id": self._session.call_id,
                "flow_key": self._session.flow_key,
                "agent": self._session.nombre_agente,
                "user_name": self._session.nombre_deudor,
                "company": catalog_name,
                "phase": self._session.phase,
                "status": "ACTIVE",
            }
        )

    async def emit_phase(self, phase: str) -> None:
        await self._emit({"type": "phase", "phase": phase})

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if frame.id in self._seen:
            return
        self._seen.add(frame.id)
        self._seen_order.append(frame.id)
        if len(self._seen) > len(self._seen_order):
            self._seen = set(self._seen_order)

        if isinstance(frame, (VADUserStartedSpeakingFrame, UserStartedSpeakingFrame)):
            await self._emit({"type": "status", "listening": True, "generating": False})
            return

        if isinstance(frame, UserStoppedSpeakingFrame):
            self._user_stop_at = time.monotonic()
            await self._emit({"type": "status", "listening": False})
            return

        if isinstance(frame, BotStartedSpeakingFrame):
            latency_ms = None
            if self._user_stop_at is not None:
                latency_ms = int((time.monotonic() - self._user_stop_at) * 1000)
                self._user_stop_at = None
            await self._emit(
                {
                    "type": "status",
                    "speaking": True,
                    "generating": False,
                    "latency_total_ms": latency_ms,
                }
            )
            return

        if isinstance(frame, BotStoppedSpeakingFrame):
            await self._emit({"type": "status", "speaking": False})
            return

        if isinstance(frame, FunctionCallInProgressFrame):
            await self._emit({"type": "status", "generating": True})
            return

        if isinstance(frame, InterimTranscriptionFrame):
            text = (frame.text or "").strip()
            if text:
                await self._emit(
                    {
                        "type": "transcript",
                        "role": "user",
                        "text": text,
                        "streaming": True,
                    }
                )
            return

        if isinstance(frame, TranscriptionFrame):
            text = (frame.text or "").strip()
            if text:
                await self._emit(
                    {
                        "type": "transcript",
                        "role": "user",
                        "text": text,
                        "streaming": False,
                    }
                )
            return

        if isinstance(frame, LLMFullResponseStartFrame):
            self._bot_buf = ""
            await self._emit({"type": "status", "generating": True, "listening": False})
            return

        if isinstance(frame, LLMTextFrame):
            chunk = frame.text or ""
            if not chunk:
                return
            self._bot_buf += chunk
            await self._emit(
                {
                    "type": "transcript",
                    "role": "bitbit",
                    "text": self._bot_buf.strip(),
                    "streaming": True,
                }
            )
            return

        if isinstance(frame, LLMFullResponseEndFrame):
            final = self._bot_buf.strip()
            self._bot_buf = ""
            if final:
                await self._emit(
                    {
                        "type": "transcript",
                        "role": "bitbit",
                        "text": final,
                        "streaming": False,
                    }
                )
            await self._emit({"type": "status", "generating": False})
            return

        if isinstance(frame, TTSSpeakFrame):
            text = (frame.text or "").strip()
            if text and text not in self._bot_buf:
                await self._emit(
                    {
                        "type": "transcript",
                        "role": "bitbit",
                        "text": text,
                        "streaming": False,
                    }
                )
            return

        if isinstance(frame, MetricsFrame) and data.direction == FrameDirection.DOWNSTREAM:
            await self._on_metrics(frame)

    async def _on_metrics(self, frame: MetricsFrame) -> None:
        ttfb_ms = None
        for item in frame.data or []:
            if isinstance(item, TTFBMetricsData):
                ttfb_ms = int(float(item.value) * 1000)
            elif isinstance(item, LLMUsageMetricsData):
                usage = item.value
                prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
                completion = int(getattr(usage, "completion_tokens", 0) or 0)
                self._prompt_tokens += prompt
                self._completion_tokens += completion
            elif isinstance(item, TTSUsageMetricsData):
                self._tts_chars += int(item.value or 0)
        payload: dict[str, Any] = {
            "type": "metrics",
            "tokens_prompt": self._prompt_tokens,
            "tokens_completion": self._completion_tokens,
            "tokens_total": self._prompt_tokens + self._completion_tokens,
            "tts_chars": self._tts_chars,
        }
        if ttfb_ms is not None:
            payload["latency_infer_ms"] = ttfb_ms
        await self._emit(payload)

    async def _emit(self, payload: dict[str, Any]) -> None:
        if not self._emit_fn:
            return
        try:
            await self._emit_fn(payload)
        except Exception as exc:
            logger.debug("HUD emit failed: {}", exc)


def attach_hud(session: CallSession, transport) -> HudObserver:
    observer = HudObserver(session)

    async def emit(payload: dict[str, Any]) -> None:
        await transport.output().send_message(OutputTransportMessageFrame(message=payload))

    observer.bind(emit)
    return observer


def wire_text_input(transport, user_aggregator) -> None:
    """El HUD puede mandar texto por el data channel además del micrófono."""

    @transport.event_handler("on_app_message")
    async def _on_app_message(transport, message, sender):
        if not isinstance(message, dict) or message.get("type") != "user_text":
            return
        text = str(message.get("text") or "").strip()
        if not text:
            return
        frame = TranscriptionFrame(
            text=text,
            user_id="studio",
            timestamp=datetime.now(timezone.utc).isoformat(),
            finalized=True,
        )
        await user_aggregator.queue_frame(frame)
