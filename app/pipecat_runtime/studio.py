"""Studio WebRTC: front propio (no Pipecat prebuilt) + catálogo de flujos."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.flow_graph.catalog import get_flow_catalog_metadata, list_flow_spec_files

WEB_ROOT = Path(__file__).resolve().parents[2] / "web"

_BODY_KEYS = (
    "flow_key",
    "name",
    "nombre_paciente",
    "nombre_deudor",
    "nombre_agente",
    "company_name",
    "fecha_turno",
    "hora_turno",
)


def list_studio_flows() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in list_flow_spec_files():
        try:
            meta = get_flow_catalog_metadata(path)
        except (OSError, ValueError, TypeError):
            continue
        key = str(meta.get("flow_key") or meta.get("platform_flow_key") or "").strip()
        if not key:
            continue
        items.append(
            {
                "flow_key": key,
                "visible_name": (
                    "Clínica Vida" if key == "clinica_vida_flow" else str(meta.get("visible_name") or key)
                ),
                "flow_type": str(meta.get("flow_type") or ""),
            }
        )
    items.sort(
        key=lambda row: (row["flow_key"] != "clinica_vida_flow", row["visible_name"].lower())
    )
    return items


def merge_call_metadata(base: dict[str, Any] | None, runner_args: Any) -> dict[str, Any]:
    """Combina preset + request_data del cliente WebRTC (flow_key, nombre, …)."""
    meta = dict(base or {})
    body = getattr(runner_args, "body", None)
    if not isinstance(body, dict):
        return meta
    for key in _BODY_KEYS:
        value = body.get(key)
        if value is not None and str(value).strip():
            meta[key] = value
    return meta


def install_studio_frontend() -> None:
    """Reemplaza el redirect a /client por el HUD de bitbit."""
    from pipecat.runner import run as run_mod

    run_mod._setup_frontend_routes = _setup_studio_routes


def install_no_store_static(app) -> None:
    """El Studio es local y cambia seguido: nada de cache en HTML/JS/CSS.

    Un `webrtc.js` cacheado siguió mandando `ping` cada 4 s tras el fix a 1 s
    y el transporte volvió a tirar audio (log 10:05:02 transport.drop).
    """

    @app.middleware("http")
    async def _no_store(request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path in ("/", "/studio", "/styles.css") or path.startswith("/js/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response


def _setup_studio_routes(app) -> None:
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    from app.orchestrator.loader import default_flow_key

    install_no_store_static(app)

    @app.get("/api/studio/config", include_in_schema=False)
    async def studio_config():
        return {
            "default_flow_key": default_flow_key(),
            "flows": list_studio_flows(),
        }

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

    try:
        from pipecat_ai_prebuilt.frontend import PipecatPrebuiltUI

        app.mount("/client", PipecatPrebuiltUI)
    except ImportError:
        pass
