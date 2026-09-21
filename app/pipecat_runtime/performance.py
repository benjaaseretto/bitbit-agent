"""Bounded, text-free performance diagnostics for local calls."""
import asyncio
import json
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger


@asynccontextmanager
async def monitor_runtime(engine, report_path=None):
    lag_ms = []
    started = time.monotonic()
    engine.work_stats.clear()
    engine.tts_stats.clear()

    async def probe():
        while True:
            before = time.monotonic()
            await asyncio.sleep(0.25)
            lag_ms.append(max(0.0, time.monotonic() - before - 0.25) * 1000)
            # Bound memory even during very long calls.
            if len(lag_ms) > 2400:
                del lag_ms[:1200]

    task = asyncio.create_task(probe())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        values = sorted(lag_ms)
        report = {
            "at": datetime.now(timezone.utc).isoformat(),
            "call_seconds": round(time.monotonic() - started, 3),
            "loop_lag_max_ms": round(max(values, default=0), 2),
            "loop_lag_p95_ms": round(values[int((len(values)-1)*0.95)], 2) if values else 0,
            "mlx": dict(engine.work_stats),
            "tts": list(engine.tts_stats),
        }
        logger.info("PERFORMANCE {}", json.dumps(report))
        path = report_path or Path(__file__).resolve().parents[2] / "reports" / "runtime-performance.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Keep local diagnostics bounded; contains no audio or dialogue.
            if path.exists() and path.stat().st_size > 2_000_000:
                path.replace(path.with_suffix(".previous.jsonl"))
            with path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(report) + "\n")
        except OSError:
            logger.warning("Could not save local performance report")
