"""Barge-in en Mac (mic + parlantes): no cortar el TTS por eco o muletillas."""
from __future__ import annotations

import re

from loguru import logger
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
    """

    async def _handle_transcription(
        self, frame: TranscriptionFrame | InterimTranscriptionFrame
    ) -> ProcessFrameResult:
        raw = (getattr(frame, "text", None) or "").strip()
        if is_turn_filler(raw):
            logger.debug("{} ignore filler={!r}", self, raw)
            return ProcessFrameResult.CONTINUE

        word_count = len(raw.split())
        min_words = interruption_word_threshold(
            bot_speaking=self._bot_speaking, min_words=self._min_words
        )
        # 0 mientras habla = no interrumpir (el STT a menudo transcribe el propio TTS).
        if self._bot_speaking and min_words <= 0:
            logger.debug("{} skip barge-in while bot speaking text={!r}", self, raw)
            return ProcessFrameResult.CONTINUE

        should_trigger = word_count >= max(min_words, 1)
        is_interim = isinstance(frame, InterimTranscriptionFrame)
        logger.debug(
            f"{self} should_trigger={should_trigger} num_spoken_words={word_count} "
            f"min_words={min_words} bot_speaking={self._bot_speaking} "
            f"interim_transcription={is_interim}"
        )
        if should_trigger:
            await self.trigger_user_turn_started()
            return ProcessFrameResult.STOP
        if self._bot_speaking:
            return ProcessFrameResult.CONTINUE
        await self.trigger_reset_aggregation()
        return ProcessFrameResult.CONTINUE
