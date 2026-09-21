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

from app.pipecat_runtime.studio import WEB_ROOT, list_studio_flows

ROOT = Path(__file__).resolve().parents[2]
BOT_HOST = "127.0.0.1"
BOT_PORT = int(os.getenv("BITBIT_BOT_PORT", "7870"))
STUDIO_PORT = int(os.getenv("BITBIT_STUDIO_PORT", "7860"))


class BotManager:
    """Hijo mac_bot (Pipecat WebRTC). El supervisor no muere al apagarlo."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def status(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "bot_port": BOT_PORT,
            "studio_port": STUDIO_PORT,
            "pid": self._proc.pid if self.running else None,
        }

    def start(self, *, wait_s: float = 180.0) -> dict[str, Any]:
        if self.running:
            return self.status()
        env = os.environ.copy()
        env["BITBIT_SUPERVISED"] = "1"
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
                return self.status()
            time.sleep(0.4)
        self.stop()
        raise RuntimeError(f"mac_bot no abrió el puerto {BOT_PORT} en {wait_s:.0f}s")

    def stop(self) -> dict[str, Any]:
        proc = self._proc
        self._proc = None
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

    @app.get("/api/studio/config", include_in_schema=False)
    async def studio_config():
        return {
            "default_flow_key": default_flow_key(),
            "flows": list_studio_flows(),
            **manager.status(),
        }

    @app.get("/api/studio/status", include_in_schema=False)
    async def studio_status():
        return manager.status()

    @app.post("/api/studio/start", include_in_schema=False)
    async def studio_start():
        try:
            status = await asyncio.to_thread(manager.start)
            return {"ok": True, **status}
        except RuntimeError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)

    @app.post("/api/studio/stop", include_in_schema=False)
    async def studio_stop():
        status = await asyncio.to_thread(manager.stop)
        return {"ok": True, **status}

    @app.post("/api/studio/shutdown", include_in_schema=False)
    async def studio_shutdown_alias():
        status = await asyncio.to_thread(manager.stop)
        return {"ok": True, "action": "stop", **status}

    @app.api_route("/api/offer", methods=["POST", "PATCH"], include_in_schema=False)
    async def proxy_offer(request: Request):
        # Sin `from __future__ import annotations`: FastAPI necesita Request concreto.
        if not manager.running:
            return JSONResponse(
                {
                    "error": "bot_off",
                    "detail": "Encendé el bot antes de iniciar el enlace.",
                },
                status_code=503,
            )
        body = await request.body()
        async with httpx.AsyncClient(timeout=120.0) as client:
            upstream = await client.request(
                request.method,
                f"{bot_base}/api/offer",
                content=body,
                headers={"content-type": "application/json"},
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
