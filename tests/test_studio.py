from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from pipecat.frames.frames import TranscriptionFrame
from pipecat.observers.base_observer import FramePushed
from pipecat.processors.frame_processor import FrameDirection

from app.pipecat_runtime.hud import HudObserver
from app.pipecat_runtime.studio import list_studio_flows, merge_call_metadata
from app.pipecat_runtime.supervisor import BotManager
from app.session.call_session import CallSession


def test_list_studio_flows_includes_clinica():
    flows = list_studio_flows()
    keys = {item["flow_key"] for item in flows}
    assert "clinica_vida_flow" in keys
    assert flows[0]["flow_key"] == "clinica_vida_flow"
    assert flows[0]["visible_name"] == "Clínica Vida"
    assert all(item["visible_name"] for item in flows)


def test_merge_call_metadata_overrides_flow_key():
    runner = SimpleNamespace(body={"flow_key": "aurora_salud_flow", "name": "Lucía"})
    merged = merge_call_metadata({"flow_key": "clinica_vida_flow"}, runner)
    assert merged["flow_key"] == "aurora_salud_flow"
    assert merged["name"] == "Lucía"


def test_merge_call_metadata_ignores_empty_body():
    runner = SimpleNamespace(body=None)
    merged = merge_call_metadata({"flow_key": "clinica_vida_flow"}, runner)
    assert merged["flow_key"] == "clinica_vida_flow"


def test_bot_manager_stop_without_process():
    manager = BotManager()
    status = manager.stop()
    assert status["running"] is False
    assert status["pid"] is None


def test_bot_manager_start_reuses_running_child(monkeypatch):
    manager = BotManager()
    fake = MagicMock()
    fake.poll.return_value = None
    fake.pid = 99
    manager._proc = fake
    status = manager.start()
    assert status["running"] is True
    assert status["pid"] == 99


@pytest.mark.asyncio
async def test_hud_observer_emits_user_transcript_once():
    session = CallSession(call_id="sess1", flow_key="clinica_vida_flow")
    observer = HudObserver(session)
    emitted = []

    async def emit(payload):
        emitted.append(payload)

    observer.bind(emit)
    frame = TranscriptionFrame(text="hola", user_id="u", timestamp="t", finalized=True)
    pushed = FramePushed(
        source=SimpleNamespace(),
        destination=SimpleNamespace(),
        frame=frame,
        direction=FrameDirection.DOWNSTREAM,
        timestamp=0,
    )
    await observer.on_push_frame(pushed)
    await observer.on_push_frame(pushed)
    assert len(emitted) == 1
    assert emitted[0]["role"] == "user"
    assert emitted[0]["text"] == "hola"
