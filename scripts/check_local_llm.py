"""Exercise the real clinic tool schemas against the local Qwen server."""
import asyncio
import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

from openai import AsyncOpenAI
from pipecat.processors.aggregators.llm_context import LLMContext

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.pipecat_runtime.config import RuntimeConfig
from app.pipecat_runtime.flow_data import build_session
from app.pipecat_runtime.tools import FlowController


async def main():
    config = RuntimeConfig.from_env()
    session, flow = build_session({"name": "Juan Pérez"})
    controller = FlowController(session, flow, speak=AsyncMock())
    context = LLMContext(tools=[controller.esperar_titular, controller.registrar_resultado_identidad])
    tools = [{"type": "function", "function": t.to_default_dict()} for t in context.tools.standard_tools]
    rows = []
    async with AsyncOpenAI(base_url=config.llm_url, api_key="local", max_retries=0, timeout=60) as client:
        for run in range(3):
            started = time.perf_counter()
            first = None
            calls = {}
            text = ""
            stream = await client.chat.completions.create(
                model=config.llm_model, temperature=0.3, max_tokens=220,
                messages=[{"role": "system", "content": controller.identity_system_prompt()},
                          {"role": "assistant", "content": "¿Hablo con Juan Pérez?"},
                          {"role": "user", "content": "Sí, soy Juan Pérez."}],
                tools=tools, tool_choice="auto", stream=True,
            )
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if first is None and (delta.content or delta.tool_calls):
                    first = time.perf_counter() - started
                text += delta.content or ""
                for call in delta.tool_calls or []:
                    item = calls.setdefault(call.index, {"name": "", "arguments": ""})
                    if call.function:
                        item["name"] += call.function.name or ""
                        item["arguments"] += call.function.arguments or ""
            valid = any(c["name"] == "registrar_resultado_identidad" and
                        json.loads(c["arguments"]).get("resultado") == "titular_confirmado"
                        for c in calls.values())
            row = {"run": run, "first_output_ms": round(first*1000) if first is not None else None,
                   "complete_ms": round((time.perf_counter()-started)*1000),
                   "correct_tool": valid, "text": text, "calls": list(calls.values())}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / "reports/benchmark_llm.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    if not all(row["correct_tool"] for row in rows):
        raise SystemExit("Qwen did not select the expected tool in every run")


if __name__ == "__main__":
    asyncio.run(main())
