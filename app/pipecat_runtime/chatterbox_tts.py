"""Chatterbox Multilingual TTS via OpenAI-compatible HTTP API.

Default server: chatterbox-tts-api on :4123 (ResembleAI Chatterbox Multilingual).
Spanish: register a voice with ``language=es`` (see scripts/register_chatterbox_voice.py).
"""
from __future__ import annotations

import io
import wave
from collections.abc import AsyncGenerator
from typing import Any

import aiohttp
from loguru import logger

from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts
from pipecat.utils.types import assert_given

CHATTERBOX_SAMPLE_RATE = 24_000


class ChatterboxTTSService(TTSService):
    """HTTP client for Chatterbox Multilingual (OpenAI-compatible /v1/audio/speech)."""

    Settings = TTSSettings
    _settings: Settings

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:4123/v1",
        api_key: str = "not-needed",
        language: str = "es",
        sample_rate: int | None = None,
        settings: TTSSettings | None = None,
        **kwargs: Any,
    ) -> None:
        default = self.Settings(
            model="chatterbox-multilingual",
            voice="ana_es",
            language=None,
        )
        if settings is not None:
            default.apply_update(settings)

        super().__init__(
            sample_rate=sample_rate or CHATTERBOX_SAMPLE_RATE,
            push_start_frame=True,
            push_stop_frames=True,
            settings=default,
            **kwargs,
        )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._language = language
        self._session: aiohttp.ClientSession | None = None

    def can_generate_metrics(self) -> bool:
        return True

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=180, connect=15),
            )
        return self._session

    async def cleanup(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        await super().cleanup()

    @staticmethod
    def _wav_to_pcm(data: bytes) -> tuple[bytes, int]:
        with wave.open(io.BytesIO(data), "rb") as wf:
            if wf.getsampwidth() != 2:
                raise ValueError(f"Expected 16-bit PCM WAV, got sampwidth={wf.getsampwidth()}")
            return wf.readframes(wf.getnframes()), wf.getframerate()

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        voice = assert_given(self._settings.voice)
        if not voice:
            yield ErrorFrame(error="Chatterbox voice must be set (CHATTERBOX_VOICE)")
            return

        url = f"{self._base_url}/audio/speech"
        payload: dict[str, Any] = {
            "input": text,
            "voice": voice,
            "model": self._settings.model or "chatterbox-multilingual",
            "response_format": "wav",
            # Some forks accept language; chatterbox-tts-api prefers voice metadata.
            "language": self._language,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            session = await self._get_session()
            async with session.post(url, json=payload, headers=headers) as resp:
                body = await resp.read()
                if resp.status != 200:
                    msg = f"Chatterbox TTS HTTP {resp.status}: {body[:400]!r}"
                    logger.error("{} {}", self, msg)
                    yield ErrorFrame(error=msg)
                    return

                await self.start_tts_usage_metrics(text)
                await self.stop_ttfb_metrics()

                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "wav" in ctype or body[:4] == b"RIFF":
                    pcm, sr = self._wav_to_pcm(body)
                    if sr != self.sample_rate:
                        logger.warning(
                            "Chatterbox sample_rate={} (service configured {})",
                            sr,
                            self.sample_rate,
                        )
                        self._sample_rate = sr
                else:
                    # Assume raw PCM 16-bit mono
                    pcm = body
                    sr = self.sample_rate

                chunk_size = self.chunk_size
                for i in range(0, len(pcm), chunk_size):
                    chunk = pcm[i : i + chunk_size]
                    if chunk:
                        yield TTSAudioRawFrame(chunk, sr, 1, context_id=context_id)

        except aiohttp.ClientError as exc:
            msg = (
                f"Chatterbox TTS unreachable at {url}: {exc}. "
                "Start it: docker compose -f docker-compose.oss.yml up -d chatterbox"
            )
            logger.error(msg)
            yield ErrorFrame(error=msg)
        except Exception as exc:
            logger.exception("Chatterbox TTS failed")
            yield ErrorFrame(error=f"Chatterbox TTS error: {exc}")
