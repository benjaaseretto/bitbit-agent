"""Catálogo de voces del Studio: presets Qwen + clones locales."""
from __future__ import annotations

import json
import re
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.pipecat_runtime.config import ROOT

VOICES_DIR = ROOT / "presets" / "voices"
CLONES_DIR = VOICES_DIR / "clones"
ACTIVE_PATH = VOICES_DIR / "active.json"
CALL_LOCK_PATH = VOICES_DIR / ".call_lock"
CATALOG_PATH = ROOT / "presets" / "voices.json"

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_AUDIO_BYTES = 8 * 1024 * 1024  # 8 MB
_MIN_REF_CHARS = 12
_DEFAULT_REF_HINT = (
    "Hola, este es un audio de referencia para clonar mi voz en bitbit."
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(name: str) -> str:
    base = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return (base or "voz")[:48]


def ensure_dirs() -> None:
    CLONES_DIR.mkdir(parents=True, exist_ok=True)


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def list_presets() -> list[dict[str, Any]]:
    catalog = _read_json(CATALOG_PATH, {})
    return list(catalog.get("qwen_custom_voice") or [])


def list_clones() -> list[dict[str, Any]]:
    ensure_dirs()
    clones: list[dict[str, Any]] = []
    for meta_path in sorted(CLONES_DIR.glob("*.json")):
        meta = _read_json(meta_path, None)
        if not isinstance(meta, dict):
            continue
        audio = CLONES_DIR / f"{meta_path.stem}.wav"
        if not audio.is_file():
            continue
        clones.append(
            {
                "id": meta_path.stem,
                "name": meta.get("name") or meta_path.stem,
                "reference_text": meta.get("reference_text") or "",
                "created_at": meta.get("created_at"),
                "audio_rel": str(audio.relative_to(ROOT)),
                "duration_s": meta.get("duration_s"),
            }
        )
    return clones


def load_active() -> dict[str, Any]:
    data = _read_json(ACTIVE_PATH, {})
    if not isinstance(data, dict):
        data = {}
    mode = (data.get("mode") or "preset").strip().lower()
    if mode not in {"preset", "clone"}:
        mode = "preset"
    return {
        "engine": (data.get("engine") or "qwen-mlx").strip(),
        "mode": mode,
        "preset_id": (data.get("preset_id") or "Serena").strip() or "Serena",
        "clone_id": (data.get("clone_id") or "").strip() or None,
        "reference_audio": (data.get("reference_audio") or "").strip(),
        "reference_text": (data.get("reference_text") or "").strip(),
        "updated_at": data.get("updated_at"),
    }


def save_active(payload: dict[str, Any]) -> dict[str, Any]:
    ensure_dirs()
    current = load_active()
    mode = (payload.get("mode") or current["mode"]).strip().lower()
    if mode not in {"preset", "clone"}:
        raise ValueError("mode debe ser preset o clone")
    engine = (payload.get("engine") or "qwen-mlx").strip() or "qwen-mlx"
    active = {
        "engine": engine,
        "mode": mode,
        "preset_id": (payload.get("preset_id") or current["preset_id"] or "Serena").strip(),
        "clone_id": None,
        "reference_audio": "",
        "reference_text": "",
        "updated_at": _now(),
    }
    if mode == "clone":
        clone_id = (payload.get("clone_id") or "").strip()
        if not clone_id:
            raise ValueError("clone_id es obligatorio en modo clone")
        meta_path = CLONES_DIR / f"{clone_id}.json"
        audio_path = CLONES_DIR / f"{clone_id}.wav"
        meta = _read_json(meta_path, None)
        if not isinstance(meta, dict) or not audio_path.is_file():
            raise ValueError(f"No existe el clone '{clone_id}'")
        active["clone_id"] = clone_id
        active["reference_audio"] = str(audio_path.relative_to(ROOT))
        active["reference_text"] = (meta.get("reference_text") or "").strip()
        if not active["reference_text"]:
            raise ValueError("El clone no tiene transcripción")
    _write_json(ACTIVE_PATH, active)
    return active


def wav_duration_seconds(path: Path) -> float | None:
    try:
        with wave.open(str(path), "rb") as handle:
            frames = handle.getnframes()
            rate = handle.getframerate() or 1
            return round(frames / rate, 3)
    except (OSError, wave.Error):
        return None


def save_clone(
    *,
    name: str,
    reference_text: str,
    audio_bytes: bytes,
    content_type: str | None = None,
) -> dict[str, Any]:
    ensure_dirs()
    text = " ".join((reference_text or "").split())
    if len(text) < _MIN_REF_CHARS:
        raise ValueError(
            f"La transcripción debe tener al menos {_MIN_REF_CHARS} caracteres "
            "(tiene que coincidir con lo que dijiste en el audio)."
        )
    if not audio_bytes:
        raise ValueError("Falta el audio de referencia")
    if len(audio_bytes) > _MAX_AUDIO_BYTES:
        raise ValueError("El audio supera 8 MB")
    ctype = (content_type or "").lower()
    if ctype and "wav" not in ctype and "wave" not in ctype and "octet" not in ctype:
        # Aceptamos webm/ogg y los guardamos igual; Qwen suele preferir wav.
        # Convertimos solo si ya es wav; si no, pedimos wav desde el front.
        if "webm" in ctype or "ogg" in ctype or "mpeg" in ctype or "mp4" in ctype:
            raise ValueError(
                "Subí o exportá el audio en WAV (el Studio lo graba así)."
            )
    slug = slugify(name)
    stem = slug
    index = 2
    while (CLONES_DIR / f"{stem}.json").exists() or (CLONES_DIR / f"{stem}.wav").exists():
        stem = f"{slug}-{index}"
        index += 1
    audio_path = CLONES_DIR / f"{stem}.wav"
    meta_path = CLONES_DIR / f"{stem}.json"
    # Validar cabecera RIFF/WAVE mínima.
    if len(audio_bytes) < 12 or audio_bytes[:4] != b"RIFF" or audio_bytes[8:12] != b"WAVE":
        raise ValueError("El archivo no es un WAV válido")
    audio_path.write_bytes(audio_bytes)
    duration = wav_duration_seconds(audio_path)
    meta = {
        "id": stem,
        "name": (name or stem).strip() or stem,
        "reference_text": text,
        "created_at": _now(),
        "duration_s": duration,
        "hint": _DEFAULT_REF_HINT,
    }
    _write_json(meta_path, meta)
    return {
        "id": stem,
        "name": meta["name"],
        "reference_text": text,
        "created_at": meta["created_at"],
        "audio_rel": str(audio_path.relative_to(ROOT)),
        "duration_s": duration,
    }


def resolve_clone_audio(clone_id: str) -> Path:
    path = CLONES_DIR / f"{slugify(clone_id)}.wav"
    if not path.is_file():
        raise FileNotFoundError(clone_id)
    return path


def env_overrides_from_active(active: dict[str, Any] | None = None) -> dict[str, str]:
    """Variables que el bot hijo debe heredar al arrancar."""
    data = active or load_active()
    env = {
        "TTS_ENGINE": data.get("engine") or "qwen-mlx",
        "TTS_VOICE_MODE": data.get("mode") or "preset",
        "QWEN_TTS_VOICE": data.get("preset_id") or "Serena",
        "QWEN_TTS_REFERENCE_AUDIO": "",
        "QWEN_TTS_REFERENCE_TEXT": "",
    }
    if data.get("mode") == "clone":
        env["QWEN_TTS_REFERENCE_AUDIO"] = data.get("reference_audio") or ""
        env["QWEN_TTS_REFERENCE_TEXT"] = data.get("reference_text") or ""
    return env


def set_call_lock(*, active: bool, voice_label: str = "") -> None:
    """Marca si hay una llamada WebRTC viva (el supervisor no debe reiniciar voz)."""
    ensure_dirs()
    if active:
        _write_json(
            CALL_LOCK_PATH,
            {
                "active": True,
                "voice": voice_label,
                "updated_at": _now(),
            },
        )
        return
    try:
        CALL_LOCK_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def load_call_lock() -> dict[str, Any]:
    data = _read_json(CALL_LOCK_PATH, {})
    if not isinstance(data, dict):
        return {"active": False}
    return {
        "active": bool(data.get("active")),
        "voice": (data.get("voice") or "").strip(),
        "updated_at": data.get("updated_at"),
    }


def is_call_active() -> bool:
    return bool(load_call_lock().get("active"))


def studio_voice_payload() -> dict[str, Any]:
    active = load_active()
    return {
        "engine": active["engine"],
        "active": active,
        "presets": list_presets(),
        "clones": list_clones(),
        "reference_hint": _DEFAULT_REF_HINT,
        "call_lock": load_call_lock(),
        "notes": [
            "Grabá 8–20 s de voz limpia leyendo exactamente la transcripción.",
            "Solo audio propio o con permiso escrito (no celebridades).",
            "Elegí la voz acá; al iniciar el enlace se aplica sola.",
            "Durante la llamada la voz queda fija; cambiá recién al cortar.",
        ],
    }
