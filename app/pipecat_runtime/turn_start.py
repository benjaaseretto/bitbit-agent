"""Barge-in en Mac (mic + parlantes): no cortar el TTS por eco o muletillas."""
from __future__ import annotations

import re

from loguru import logger

from app.pipecat_runtime.audio_map import map_log
from pipecat.frames.frames import InterimTranscriptionFrame, TranscriptionFrame
from pipecat.turns.types import ProcessFrameResult
from pipecat.turns.user_start.min_words_user_turn_start_strategy import (
    MinWordsUserTurnStartStrategy,
)

_FILLER_RE = re.compile(
    r"^(eh+|ehm+|mmm+|mm+|ah+|ajá|aja|este|esto|bueno|\.{2,}|…)+$",
    re.IGNORECASE,
)


def is_turn_filler(text: str) -> bool:
    cleaned = (text or "").strip().lower().strip(".…,¿?¡! ")
    if not cleaned:
        return True
    return bool(_FILLER_RE.match(cleaned))


def interruption_word_threshold(*, bot_speaking: bool, min_words: int) -> int:
    """Idle: 1 palabra real (sí/no). TTS en curso: 0 = no cortar; N = barge-in."""
    if bot_speaking:
        return max(int(min_words), 0)
    return 1


class MacMinWordsUserTurnStartStrategy(MinWordsUserTurnStartStrategy):
    """Pipecat baja a 1 palabra en silencio y usa min_words para cortar el TTS.

    Con parlantes, el eco y 'Ehh...' disparan InterruptionFrame a mitad de frase.
    Default Mac: no barge-in mientras el bot habla (INTERRUPTION_MIN_WORDS=0).

    ``playback_active`` cubre el tramo en que la GPU ya terminó pero WebRTC
    sigue reproduciendo (sin drenar el contexto TTS ~1s extra).
    """

    def __init__(self, *args, playback_active=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._playback_active = playback_active

    def _bot_or_playback(self) -> bool:
        if self._bot_speaking:
            return True
        if self._playback_active is not None:
            try:
                return bool(self._playback_active())
            except Exception:
                return False
        return False

    async def _handle_transcription(
        self, frame: TranscriptionFrame | InterimTranscriptionFrame
    ) -> ProcessFrameResult:
        raw = (getattr(frame, "text", None) or "").strip()
        if is_turn_filler(raw):
            map_log("turn.filler", text=repr(raw))
            logger.info("{} ignore filler={!r}", self, raw)
            return ProcessFrameResult.CONTINUE

        speaking = self._bot_or_playback()
        word_count = len(raw.split())
        min_words = interruption_word_threshold(
            bot_speaking=speaking, min_words=self._min_words
        )
        # 0 mientras habla = no interrumpir (el STT a menudo transcribe el propio TTS).
        if speaking and min_words <= 0:
            map_log(
                "turn.skip_bargein",
                text=repr(raw),
                bot_speaking=self._bot_speaking,
                playback=speaking,
            )
            logger.info("{} skip barge-in while bot/playback text={!r}", self, raw)
            return ProcessFrameResult.CONTINUE

        should_trigger = word_count >= max(min_words, 1)
        is_interim = isinstance(frame, InterimTranscriptionFrame)
        map_log(
            "turn.decide",
            trigger=should_trigger,
            words=word_count,
            min_words=min_words,
            bot_speaking=self._bot_speaking,
            playback=speaking,
            interim=is_interim,
            text=repr(raw),
        )
        logger.info(
            f"{self} should_trigger={should_trigger} num_spoken_words={word_count} "
            f"min_words={min_words} bot_speaking={self._bot_speaking} "
            f"playback={speaking and not self._bot_speaking} "
            f"interim_transcription={is_interim} text={raw!r}"
        )
        if should_trigger:
            await self.trigger_user_turn_started()
            return ProcessFrameResult.STOP
        if speaking:
            return ProcessFrameResult.CONTINUE
        await self.trigger_reset_aggregation()
        return ProcessFrameResult.CONTINUE
