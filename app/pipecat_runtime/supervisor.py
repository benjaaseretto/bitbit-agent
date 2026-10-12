"""Supervisor local: la UI vive siempre; el bot MLX se apaga y enciende a demanda."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from loguru import logger

from app.pipecat_runtime.studio import WEB_ROOT, install_no_store_static, list_studio_flows

ROOT = Path(__file__).resolve().parents[2]
BOT_HOST = "127.0.0.1"
BOT_PORT = int(os.getenv("BITBIT_BOT_PORT", "7870"))
STUDIO_PORT = int(os.getenv("BITBIT_STUDIO_PORT", "7860"))


class BotManager:
    """Hijo mac_bot (Pipecat WebRTC). El supervisor no muere al apagarlo."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._applied_voice: dict[str, str] = {}
        self._starting = False

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def ready(self) -> bool:
        return self.running and not self._starting and _port_open(BOT_HOST, BOT_PORT)

    @property
    def starting(self) -> bool:
        return self._starting

    def _current_voice_env(self) -> dict[str, str]:
        try:
            from app.pipecat_runtime.voice_lab import env_overrides_from_active

            overrides = env_overrides_from_active()
        except Exception as exc:
            logger.warning("No se pudo cargar active voice: {}", exc)
            overrides = {}
        if "TTS_ENGINE" not in overrides:
            overrides = {**overrides, "TTS_ENGINE": "qwen-mlx"}
        return overrides

    def voice_needs_reload(self) -> bool:
        if not self.running:
            return True
        return self._current_voice_env() != self._applied_voice

    def start(self, *, wait_s: float = 180.0) -> dict[str, Any]:
        if self.running and self.ready and not self.voice_needs_reload():
            return self.status()
        if self.running:
            self._reject_if_call_active("reiniciar el bot")
            self.stop(force=True)
        env = os.environ.copy()
        env["BITBIT_SUPERVISED"] = "1"
        overrides = self._current_voice_env()
        env.update(overrides)
        voice_label = (
            env.get("QWEN_TTS_REFERENCE_AUDIO")
            if env.get("TTS_VOICE_MODE") == "clone"
            else env.get("QWEN_TTS_VOICE")
        )
        logger.info(
            "Bot child env TTS_ENGINE={} mode={} voice={}",
            env.get("TTS_ENGINE"),
            env.get("TTS_VOICE_MODE"),
            voice_label,
        )
        self._starting = True
        self._applied_voice = {}
        try:
            self._proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "app.pipecat_runtime.mac_bot",
                    "--transport",
                    "webrtc",
                    "--host",
                    BOT_HOST,
                    "--port",
                    str(BOT_PORT),
                ],
                cwd=ROOT,
                env=env,
            )
            logger.info("Bot child started pid={} port={}", self._proc.pid, BOT_PORT)
            deadline = time.monotonic() + wait_s
            while time.monotonic() < deadline:
                if self._proc.poll() is not None:
                    code = self._proc.returncode
                    self._proc = None
                    raise RuntimeError(f"mac_bot salió antes de estar listo (code={code})")
                if _port_open(BOT_HOST, BOT_PORT):
                    self._applied_voice = dict(overrides)
                    return self.status()
                time.sleep(0.4)
            self.stop(force=True)
            raise RuntimeError(f"mac_bot no abrió el puerto {BOT_PORT} en {wait_s:.0f}s")
        finally:
            self._starting = False

    def restart(self, *, wait_s: float = 180.0, force: bool = False) -> dict[str, Any]:
        """Aplica active.json (clone/preset) reiniciando el hijo."""
        if not force:
            self._reject_if_call_active("cambiar la voz")
        self.stop(force=True)
        return self.start(wait_s=wait_s)

    def ensure_voice(self, *, wait_s: float = 180.0) -> dict[str, Any]:
        """Arranca o reinicia el bot si la voz de active.json no está aplicada."""
        if self.running and self.ready and not self.voice_needs_reload():
            return self.status()
        if self.running:
            self._reject_if_call_active("aplicar otra voz")
            return self.restart(wait_s=wait_s, force=True)
        return self.start(wait_s=wait_s)

    def stop(self, *, force: bool = False) -> dict[str, Any]:
        # force=True: apagado explícito desde UI (también corta la llamada).
        if not force:
            self._reject_if_call_active("apagar el bot")
        proc = self._proc
        self._proc = None
        self._applied_voice = {}
        self._starting = False
        try:
            from app.pipecat_runtime.voice_lab import set_call_lock

            set_call_lock(active=False)
        except Exception:
            pass
        if proc is None:
            return self.status()
        if proc.poll() is None:
            logger.info("Stopping bot child pid={}", proc.pid)
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        return self.status()

    def _reject_if_call_active(self, action: str) -> None:
        try:
            from app.pipecat_runtime.voice_lab import is_call_active, load_call_lock

            if is_call_active():
                lock = load_call_lock()
                raise RuntimeError(
                    f"Hay una llamada en curso ({lock.get('voice') or 'voz fija'}). "
                    f"Cortá el enlace antes de {action}."
                )
        except RuntimeError:
            raise
        except Exception as exc:
            logger.warning("No se pudo leer call lock: {}", exc)

    def status(self) -> dict[str, Any]:
        call_lock: dict[str, Any] = {"active": False}
        try:
            from app.pipecat_runtime.voice_lab import load_call_lock

            call_lock = load_call_lock()
        except Exception:
            pass
        return {
            "running": self.running,
            "ready": self.ready,
            "starting": self._starting,
            "bot_port": BOT_PORT,
            "studio_port": STUDIO_PORT,
            "pid": self._proc.pid if self.running else None,
            "voice_applied": dict(self._applied_voice),
            "voice_pending_reload": self.voice_needs_reload() if self.running else False,
            "call_active": bool(call_lock.get("active")),
            "call_voice": call_lock.get("voice") or "",
        }


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.4):
            return True
    except OSError:
        return False


def create_supervisor_app(manager: BotManager):
    """FastAPI: studio + start/stop + proxy WebRTC al hijo."""
    import httpx
    from fastapi import FastAPI, Request
    from fastapi.responses import FileResponse, JSONResponse, Response
    from fastapi.staticfiles import StaticFiles

    from app.orchestrator.loader import default_flow_key

    app = FastAPI(title="bitbit-studio-supervisor")
    bot_base = f"http://{BOT_HOST}:{BOT_PORT}"
    install_no_store_static(app)

    @app.get("/api/studio/config", include_in_schema=False)
    async def studio_config():
        from app.pipecat_runtime.voice_lab import studio_voice_payload

        return {
            "default_flow_key": default_flow_key(),
            "flows": list_studio_flows(),
            "voice": studio_voice_payload(),
            **manager.status(),
        }

    @app.get("/api/studio/status", include_in_schema=False)
    async def studio_status():
        return manager.status()

    @app.get("/api/studio/voices", include_in_schema=False)
    async def studio_voices():
        from app.pipecat_runtime.voice_lab import studio_voice_payload

        return studio_voice_payload()

    @app.post("/api/studio/voices/activate", include_in_schema=False)
    async def studio_voices_activate(request: Request):
        """Guarda la voz elegida. No reinicia: se aplica al iniciar el enlace."""
        from app.pipecat_runtime.voice_lab import save_active

        body = await request.json()
        payload = body if isinstance(body, dict) else {}
        try:
            active = save_active(payload)
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return {
            "ok": True,
            "active": active,
            "restarted": False,
            "restart_required": manager.running and manager.voice_needs_reload(),
            "running": manager.running,
            **manager.status(),
        }

    @app.post("/api/studio/voices/ensure", include_in_schema=False)
    async def studio_voices_ensure(request: Request):
        """Aplica active.json al bot (start/restart) y espera a que quede listo."""
        from app.pipecat_runtime.voice_lab import load_active, save_active

        try:
            body = await request.json()
        except Exception:
            body = {}
        if isinstance(body, dict) and body:
            try:
                save_active(body)
            except ValueError as exc:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        try:
            status = await asyncio.to_thread(manager.ensure_voice)
        except RuntimeError as exc:
            msg = str(exc)
            code = 409 if "llamada en curso" in msg.lower() else 500
            return JSONResponse(
                {
                    "ok": False,
                    "error": msg,
                    "active": load_active(),
                    **manager.status(),
                },
                status_code=code,
            )
        return {"ok": True, "active": load_active(), **status}

    @app.post("/api/studio/voices/clone", include_in_schema=False)
    async def studio_voices_clone(request: Request):
        from app.pipecat_runtime.voice_lab import save_active, save_clone

        form = await request.form()
        name = str(form.get("name") or "").strip()
        reference_text = str(form.get("reference_text") or "").strip()
        activate = str(form.get("activate") or "1").strip().lower() not in {
            "0",
            "false",
            "no",
        }
        upload = form.get("audio")
        if upload is None or not hasattr(upload, "read"):
            return JSONResponse(
                {"ok": False, "error": "Falta el archivo audio"}, status_code=400
            )
        audio_bytes = await upload.read()
        content_type = getattr(upload, "content_type", None)
        try:
            clone = save_clone(
                name=name or "mi-voz",
                reference_text=reference_text,
                audio_bytes=audio_bytes,
                content_type=content_type,
            )
            active = None
            if activate:
                active = save_active(
                    {
                        "engine": "qwen-mlx",
                        "mode": "clone",
                        "clone_id": clone["id"],
                    }
                )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return {
            "ok": True,
            "clone": clone,
            "active": active,
            "restarted": False,
            "restart_required": bool(activate and manager.running and manager.voice_needs_reload()),
            "running": manager.running,
            **manager.status(),
        }

    @app.get("/api/studio/voices/clones/{clone_id}/audio", include_in_schema=False)
    async def studio_clone_audio(clone_id: str):
        from app.pipecat_runtime.voice_lab import resolve_clone_audio

        try:
            path = resolve_clone_audio(clone_id)
        except FileNotFoundError:
            return JSONResponse({"ok": False, "error": "clone no encontrado"}, status_code=404)
        return FileResponse(path, media_type="audio/wav", filename=f"{clone_id}.wav")

    @app.post("/api/studio/start", include_in_schema=False)
    async def studio_start():
        try:
            status = await asyncio.to_thread(manager.start)
            return {"ok": True, **status}
        except RuntimeError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.post("/api/studio/stop", include_in_schema=False)
    async def studio_stop():
        status = await asyncio.to_thread(manager.stop, force=True)
        return {"ok": True, **status}

    @app.post("/api/studio/shutdown", include_in_schema=False)
    async def studio_shutdown_alias():
        status = await asyncio.to_thread(manager.stop, force=True)
        return {"ok": True, "action": "stop", **status}

    @app.api_route("/api/offer", methods=["POST", "PATCH"], include_in_schema=False)
    async def proxy_offer(request: Request):
        # Sin `from __future__ import annotations`: FastAPI necesita Request concreto.
        if not manager.ready:
            detail = (
                "El bot está aplicando la voz. Esperá un momento."
                if manager.running or manager.starting
                else "Encendé el bot antes de iniciar el enlace."
            )
            return JSONResponse(
                {
                    "error": "bot_not_ready",
                    "detail": detail,
                    **manager.status(),
                },
                status_code=503,
            )
        body = await request.body()
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                upstream = await client.request(
                    request.method,
                    f"{bot_base}/api/offer",
                    content=body,
                    headers={"content-type": "application/json"},
                )
            except httpx.ConnectError:
                return JSONResponse(
                    {
                        "error": "bot_not_ready",
                        "detail": "El bot aún no acepta WebRTC. Reintentá en unos segundos.",
                        **manager.status(),
                    },
                    status_code=503,
                )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            media_type=upstream.headers.get("content-type", "application/json"),
        )

    @app.get("/", include_in_schema=False)
    async def studio_root():
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/studio", include_in_schema=False)
    async def studio_alias():
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/styles.css", include_in_schema=False)
    async def studio_css():
        return FileResponse(WEB_ROOT / "styles.css", media_type="text/css")

    app.mount("/js", StaticFiles(directory=str(WEB_ROOT / "js")), name="studio-js")
    return app
