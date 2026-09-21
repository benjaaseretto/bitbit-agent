"""Config del perfil Mac: STT/TTS MLX local + LLM DeepSeek (default)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

# Audio local (Apple Silicon)
PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
WHISPER_MODEL = "mlx-community/whisper-small-mlx"
TTS_BASE = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"
TTS_PRESET = "mlx-community/Qwen3-TTS-12Hz-0.6B-CustomVoice-bf16"

# LLM local opcional (A/B); el default de producto es DeepSeek
MLX_LLM_MODEL = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
DEEPSEEK_MODEL = "deepseek-flash"


def load_config_env() -> None:
    # .env.local gana (TEST_* de prueba, como colly). Luego perfil Mac y .env general.
    load_dotenv(ROOT / ".env.local", override=False)
    load_dotenv(ROOT / ".env.mac", override=False)
    load_dotenv(ROOT / ".env", override=False)


@dataclass(frozen=True)
class RuntimeConfig:
    """llm_provider: deepseek (API) | mlx (servidor local mlx_lm)."""

    llm_provider: str = "deepseek"
    deepseek_api_key: str = ""
    deepseek_model: str = DEEPSEEK_MODEL
    llm_url: str = "http://127.0.0.1:8080/v1"
    llm_model: str = MLX_LLM_MODEL
    stt_engine: str = "whisper-mlx"
    parakeet_model: str = PARAKEET_MODEL
    whisper_model: str = WHISPER_MODEL
    voice_mode: str = "preset"
    voice: str = "Serena"
    reference_audio: str = ""
    reference_text: str = ""
    tts_interval: float = 0.4
    tts_prebuffer: float = 0.45  # menor = responde antes; 1.2 sumaba ~1.5s de TTFB
    tts_speed: float = 1.0  # >1 más rápido, <1 más lento
    tts_volume: float = 1.0  # ganancia lineal (1.0 = normal)

    @property
    def tts_model(self) -> str:
        return TTS_BASE if self.voice_mode == "clone" else TTS_PRESET

    @classmethod
    def from_env(cls, *, require_llm: bool = True) -> RuntimeConfig:
        load_config_env()
        provider = (os.getenv("LLM_PROVIDER") or "deepseek").strip().lower()
        # .env del bot HTTP puede traer whisper-http; el perfil Mac solo acepta MLX.
        stt = (os.getenv("STT_ENGINE") or "whisper-mlx").strip().lower()
        if stt not in {"parakeet", "whisper-mlx"}:
            stt = "whisper-mlx"
        config = cls(
            llm_provider=provider,
            deepseek_api_key=(os.getenv("DEEPSEEK_API_KEY") or "").strip(),
            deepseek_model=os.getenv("DEEPSEEK_MODEL", DEEPSEEK_MODEL),
            llm_url=os.getenv("LLM_BASE_URL", cls.llm_url),
            llm_model=os.getenv("LLM_MODEL", MLX_LLM_MODEL),
            stt_engine=stt,
            parakeet_model=os.getenv("PARAKEET_MODEL", PARAKEET_MODEL),
            whisper_model=os.getenv("WHISPER_MLX_MODEL", WHISPER_MODEL),
            voice_mode=os.getenv("TTS_VOICE_MODE", "preset"),
            voice=os.getenv("QWEN_TTS_VOICE", "Serena"),
            reference_audio=os.getenv("QWEN_TTS_REFERENCE_AUDIO", ""),
            reference_text=os.getenv("QWEN_TTS_REFERENCE_TEXT", ""),
            tts_interval=float(os.getenv("TTS_STREAMING_INTERVAL", "0.4")),
            tts_prebuffer=float(os.getenv("TTS_PREBUFFER_SECONDS", "0.45")),
            tts_speed=float(os.getenv("TTS_SPEED", "1.0")),
            tts_volume=float(os.getenv("TTS_VOLUME", "1.0")),
        )
        config.validate(require_llm=require_llm)
        return config

    def validate(self, *, require_llm: bool = True) -> None:
        if self.llm_provider not in {"deepseek", "mlx"}:
            raise ValueError("LLM_PROVIDER debe ser deepseek o mlx.")
        if require_llm and self.llm_provider == "deepseek":
            if not self.deepseek_api_key:
                raise ValueError(
                    "DEEPSEEK_API_KEY es obligatorio con LLM_PROVIDER=deepseek."
                )
        if self.llm_provider == "mlx":
            url = urlparse(self.llm_url)
            if url.scheme != "http" or url.hostname not in {
                "127.0.0.1",
                "localhost",
                "::1",
            }:
                raise ValueError(
                    "Con LLM_PROVIDER=mlx, LLM_BASE_URL debe ser HTTP local."
                )
        if self.stt_engine not in {"parakeet", "whisper-mlx"}:
            raise ValueError("STT_ENGINE debe ser parakeet o whisper-mlx.")
        if self.voice_mode not in {"preset", "clone"}:
            raise ValueError("TTS_VOICE_MODE debe ser preset o clone.")
        if not 0.16 <= self.tts_interval <= 2.0:
            raise ValueError("TTS_STREAMING_INTERVAL debe estar entre 0.16 y 2 segundos.")
        if not 0.0 <= self.tts_prebuffer <= 5.0:
            raise ValueError("TTS_PREBUFFER_SECONDS debe estar entre 0 y 5 segundos.")
        if not 0.5 <= self.tts_speed <= 2.0:
            raise ValueError("TTS_SPEED debe estar entre 0.5 y 2.0.")
        if not 0.1 <= self.tts_volume <= 2.0:
            raise ValueError("TTS_VOLUME debe estar entre 0.1 y 2.0.")
        if self.voice_mode == "clone":
            path = Path(self.reference_audio).expanduser()
            if not path.is_absolute():
                path = ROOT / path
            if (
                not self.reference_audio
                or not path.is_file()
                or not self.reference_text.strip()
            ):
                raise ValueError(
                    "La voz clone requiere un audio real y su transcripción exacta."
                )

    def reference_path(self) -> str:
        path = Path(self.reference_audio).expanduser()
        return str(path if path.is_absolute() else ROOT / path)
