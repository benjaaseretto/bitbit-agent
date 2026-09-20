"""Arranque Mac: audio MLX + bot WebRTC. LLM = DeepSeek (no levanta mlx_lm)."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pipecat_runtime.config import RuntimeConfig


def _ensure_mlx_llm(config: RuntimeConfig, children: list) -> None:
    endpoint = f"{config.llm_url.rstrip('/')}/models"
    try:
        response = httpx.get(endpoint, timeout=2)
        response.raise_for_status()
    except httpx.HTTPError:
        url = urlparse(config.llm_url)
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mlx_lm.server",
                "--model",
                config.llm_model,
                "--host",
                url.hostname or "127.0.0.1",
                "--port",
                str(url.port or 8080),
                "--max-tokens",
                "220",
                "--prompt-cache-size",
                "2",
                "--prompt-cache-bytes",
                "512MB",
            ],
            cwd=ROOT,
        )
        children.append(server)
        deadline = time.monotonic() + 180
        while True:
            if server.poll() is not None:
                raise RuntimeError("MLX LLM no pudo arrancar; revisá el error anterior.")
            try:
                response = httpx.get(endpoint, timeout=2)
                response.raise_for_status()
                break
            except httpx.HTTPError:
                if time.monotonic() > deadline:
                    raise RuntimeError("MLX LLM no arrancó en 180 segundos.")
                time.sleep(0.5)
    models = {m["id"] for m in response.json()["data"]}
    if config.llm_model not in models:
        raise RuntimeError("El puerto configurado está ocupado por otro modelo.")


def main() -> int:
    config = RuntimeConfig.from_env()
    # Solo offline si el usuario lo pidió; prepare_models puede dejar gaps.
    # os.environ.setdefault("HF_HUB_OFFLINE", "1")
    children: list = []

    def stop(signum=None, frame=None):
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        if signum is not None:
            raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        if config.llm_provider == "mlx":
            _ensure_mlx_llm(config, children)
            print("LLM local MLX listo.", flush=True)
        else:
            print(
                f"LLM DeepSeek model={config.deepseek_model} (sin servidor local).",
                flush=True,
            )
        print(
            f"Flujo BITBIT_FLOW_KEY={os.getenv('BITBIT_FLOW_KEY') or 'clinica_vida_flow'}",
            flush=True,
        )
        print(
            "Preparando audio MLX. Studio: http://localhost:7860/",
            flush=True,
        )
        child = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "app.pipecat_runtime.mac_bot",
                "--transport",
                "webrtc",
                *sys.argv[1:],
            ],
            cwd=ROOT,
            env=os.environ.copy(),
        )
        children.append(child)
        return child.wait()
    finally:
        stop()


if __name__ == "__main__":
    raise SystemExit(main())
