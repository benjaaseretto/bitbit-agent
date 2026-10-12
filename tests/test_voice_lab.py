"""Voice lab: presets, clones, and active voice selection."""

import wave
from pathlib import Path

import pytest

from app.pipecat_runtime import voice_lab as vl


@pytest.fixture()
def voice_dirs(tmp_path, monkeypatch):
    root = tmp_path
    voices = root / "presets" / "voices"
    clones = voices / "clones"
    clones.mkdir(parents=True)
    catalog = root / "presets" / "voices.json"
    catalog.write_text(
        '{"qwen_custom_voice":[{"id":"Serena","recommended":true}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(vl, "ROOT", root)
    monkeypatch.setattr(vl, "VOICES_DIR", voices)
    monkeypatch.setattr(vl, "CLONES_DIR", clones)
    monkeypatch.setattr(vl, "ACTIVE_PATH", voices / "active.json")
    monkeypatch.setattr(vl, "CATALOG_PATH", catalog)
    return root


def _tiny_wav(path: Path, seconds: float = 0.2) -> bytes:
    rate = 16000
    frames = int(rate * seconds)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return path.read_bytes()


def test_save_and_activate_clone(voice_dirs, tmp_path):
    wav_path = tmp_path / "ref.wav"
    audio = _tiny_wav(wav_path, 0.3)
    clone = vl.save_clone(
        name="Ana Demo",
        reference_text="Hola, este es un audio de referencia para clonar.",
        audio_bytes=audio,
        content_type="audio/wav",
    )
    assert clone["id"] == "ana-demo"
    active = vl.save_active(
        {"engine": "qwen-mlx", "mode": "clone", "clone_id": clone["id"]}
    )
    assert active["mode"] == "clone"
    assert active["reference_audio"].endswith("ana-demo.wav")
    env = vl.env_overrides_from_active(active)
    assert env["TTS_ENGINE"] == "qwen-mlx"
    assert env["TTS_VOICE_MODE"] == "clone"
    assert "ana-demo.wav" in env["QWEN_TTS_REFERENCE_AUDIO"]


def test_activate_preset_clears_clone(voice_dirs):
    active = vl.save_active(
        {"engine": "qwen-mlx", "mode": "preset", "preset_id": "Vivian"}
    )
    assert active["mode"] == "preset"
    assert active["preset_id"] == "Vivian"
    assert active["reference_audio"] == ""
    env = vl.env_overrides_from_active(active)
    assert env["TTS_VOICE_MODE"] == "preset"
    assert env["QWEN_TTS_VOICE"] == "Vivian"


def test_reject_short_transcript(voice_dirs, tmp_path):
    audio = _tiny_wav(tmp_path / "x.wav")
    with pytest.raises(ValueError, match="transcripción"):
        vl.save_clone(name="x", reference_text="hola", audio_bytes=audio)
