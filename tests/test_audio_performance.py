import asyncio
import json
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.stt_service import SegmentedSTTService

from app.pipecat_runtime.config import RuntimeConfig
from app.pipecat_runtime.mlx_services import MLXAudioEngine, MLXSTTService
from app.pipecat_runtime.performance import monitor_runtime
from app.pipecat_runtime.runtime_lock import single_mac_runtime


@pytest.mark.asyncio
async def test_echo_guard_follows_playback_and_accepts_prompt_reply(monkeypatch):
    engine = MLXAudioEngine(RuntimeConfig())
    service = MLXSTTService(engine)
    monkeypatch.setattr(SegmentedSTTService, "process_frame", AsyncMock())
    clock = [100.0]
    monkeypatch.setattr("app.pipecat_runtime.mlx_services.time.monotonic", lambda: clock[0])
    try:
        await service.process_frame(BotStartedSpeakingFrame(), FrameDirection.UPSTREAM)
        engine.tts_busy = False  # GPU finished, speakers still playing queued audio.
        engine.tts_ended_at = 90.0
        assert engine.stt_is_blocked()
        engine.call = AsyncMock()
        assert [f async for f in service.run_stt(b"echo")] == []
        engine.call.assert_not_awaited()
        await service.process_frame(BotStoppedSpeakingFrame(), FrameDirection.UPSTREAM)
        assert engine.stt_is_blocked()
        clock[0] += 0.25
        assert not engine.stt_is_blocked()
        # Estimated playout deadline still blocks STT after BotStopped.
        engine.playback_until = clock[0] + 1.5
        assert engine.stt_is_blocked()
        clock[0] += 1.6
        assert not engine.stt_is_blocked()
        engine.call.return_value = "Sí, soy yo."
        frames = [f async for f in service.run_stt(b"reply")]
        assert frames[0].text == "Sí, soy yo."
    finally:
        await engine.close()


@pytest.mark.asyncio
async def test_worker_measures_queue_contention():
    engine = MLXAudioEngine(RuntimeConfig())
    try:
        await asyncio.gather(engine.call(time.sleep, 0.04), engine.call(time.sleep, 0.01))
        assert engine.work_stats["sleep"]["calls"] == 2
        assert engine.work_stats["sleep"]["max_queue_ms"] >= 20
    finally:
        await engine.close()


def test_runtime_lock_rejects_duplicate_and_releases(tmp_path):
    with single_mac_runtime(tmp_path):
        with pytest.raises(RuntimeError, match="Ya hay"):
            with single_mac_runtime(tmp_path):
                pytest.fail("duplicate acquired the lock")
    with single_mac_runtime(tmp_path):
        pass


@pytest.mark.asyncio
async def test_report_persists_metrics_even_after_failure(tmp_path):
    engine = SimpleNamespace(work_stats={}, tts_stats=deque())
    path = tmp_path / "performance.jsonl"
    with pytest.raises(ValueError):
        async with monitor_runtime(engine, path):
            engine.tts_stats.append({"completed": True, "estimated_starvation_ms": 0})
            raise ValueError("test")
    data = json.loads(path.read_text())
    assert data["tts"][0]["completed"]
    assert data["loop_lag_max_ms"] == 0
