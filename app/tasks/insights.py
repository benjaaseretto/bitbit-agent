"""DataInsightsTask: consultas de recupero/deuda con visualizaciones.

Arquitectura (ver docs/INSIGHTS.md):
- Las tools calculan métricas en código (app/analytics/metrics.py) y hablan
  SOLO valores reales; nunca inventan cifras.
- La spec de visualización la generan los builders (app/analytics/
  visualizations.py) y viaja validada (app/analytics/contract.py) por el
  data channel al panel del Studio (web/js/viz.js).
- El LLM solo elige la tool y el período; nunca escribe la spec ni JS.
- Habilitación: BITBIT_INSIGHTS=1 (FlowController inyecta las tools y el
  hint de prompt en fase negotiation). Default OFF: el agente original no
  cambia.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal

from loguru import logger
from pipecat.frames.frames import FunctionCallResultProperties

from app.analytics.contract import build_insight_message
from app.analytics.datasource import DataSourceError, get_data_source
from app.analytics.metrics import (
    UnknownPeriod,
    distribution_by_status,
    format_money,
    recovery_summary,
    top_debtors,
)
from app.analytics.visualizations import (
    VisualizationError,
    bar_chart,
    line_chart,
    ring_chart,
    table,
)
from app.tasks.base import BaseTask, TaskContext
from app.tasks.registry import register_task
from app.utils.tools_registry import register_tool

_WAIT = FunctionCallResultProperties(run_llm=False)
_CONTINUE = FunctionCallResultProperties(run_llm=True)

Periodo = Literal[
    "este_mes", "mes_anterior", "ultima_semana", "ultimos_3_meses"
]


@register_task
class DataInsightsTask(BaseTask):
    task_type = "DataInsightsTask"
    phase = "negotiation"
    tool_choice = "auto"

    def __init__(self, ctx: TaskContext, *, node_id: str = "task.insights") -> None:
        super().__init__(ctx)
        self.node_id = node_id

    def system_prompt(self) -> str:
        return (
            f"Sos {self.session.nombre_agente}, asistente de datos de "
            f"{self.session.nombre_empresa}.\n"
            "FASE: CONSULTAS DE DATOS (recupero, deuda, pagos).\n"
            "- consultar_recupero(periodo) para evolución y métricas del período.\n"
            "- comparar_periodos() para comparar este mes vs el anterior.\n"
            "- distribucion_deuda() para la distribución por estado.\n"
            "- top_deudores(limite) para el ranking de mayor saldo pendiente.\n"
            "NO inventes cifras: los valores salen de las tools. Si no hay "
            "datos para el período, decilo tal cual.\n"
            "Explicá los resultados en UNA o DOS oraciones cortas.\n"
        )

    def tools(self) -> Sequence[Callable[..., Any]]:
        return [
            self.consultar_recupero,
            self.comparar_periodos,
            self.distribucion_deuda,
            self.top_deudores,
        ]

    def _dataset(self) -> dict[str, Any]:
        """Snapshot del datasource. Levanta DataSourceError si falla."""
        return get_data_source().snapshot()

    async def _report_error(self, params, exc: Exception) -> None:
        logger.warning("insights error: {}", exc)
        await self.speak(
            "No pude consultar los datos en este momento. ¿Querés que lo intente de nuevo?"
        )
        await params.result_callback(
            {"ok": False, "error": type(exc).__name__}, properties=_CONTINUE
        )

    async def _guard(self, params) -> bool:
        if self.session.phase == "done":
            await params.result_callback(
                {"ok": False, "error": "Llamada ya cerrada."}, properties=_WAIT
            )
            return False
        return True

    async def _send_visualization(self, message: str, spec: dict[str, Any]) -> bool:
        """Valida y emite la visualización. Nunca tumba el turno de voz."""
        try:
            payload = build_insight_message(message, spec)
        except (VisualizationError, ValueError) as exc:
            logger.warning("insights spec inválida: {}", exc)
            return False
        return await self.emit_visual(payload)

    @register_tool(type="normal")
    async def consultar_recupero(self, params, periodo: Periodo = "este_mes") -> None:
        """Evolución y métricas de recupero del período (mes, semana o 3 meses)."""
        if not await self._guard(params):
            return
        try:
            dataset = self._dataset()
            summary = recovery_summary(dataset, periodo, self._today())
        except (DataSourceError, UnknownPeriod) as exc:
            await self._report_error(params, exc)
            return

        rows = summary["days"]
        if not rows:
            await self.speak(f"No hay datos de recupero para {summary['period_label']}.")
            await params.result_callback(
                {"ok": True, "empty": True, "period": periodo}, properties=_WAIT
            )
            return

        spec = line_chart(
            id="recovery-trend",
            title=f"Recupero diario · {summary['period_label']}",
            x_label="Fecha",
            unit="MXN",
            rows=[
                {"date": row["date"], "recovered_amount": row["recovered_amount"]}
                for row in rows
            ],
            series=[("recovered_amount", "Importe recuperado")],
        )
        message = (
            f"Recupero {summary['period_label']}: {format_money(summary['recovered_total'])} "
            f"({summary['start']} → {summary['end']})."
        )
        await self._send_visualization(message, spec)
        await self.speak(self._recovery_speech(summary))
        await params.result_callback(
            {
                "ok": True,
                "period": periodo,
                "recovered_total": summary["recovered_total"],
                "recovery_pct": summary["recovery_pct"],
            },
            properties=_WAIT,
        )

    @register_tool(type="normal")
    async def comparar_periodos(self, params, periodo: Periodo = "este_mes") -> None:
        """Compara el recupero del período con el período anterior inmediato."""
        if not await self._guard(params):
            return
        try:
            dataset = self._dataset()
            summary = recovery_summary(dataset, periodo, self._today())
        except (DataSourceError, UnknownPeriod) as exc:
            await self._report_error(params, exc)
            return
        if not summary["has_previous_data"]:
            await self.speak(
                "No hay datos suficientes del período anterior para comparar."
            )
            await params.result_callback(
                {"ok": True, "empty": True, "reason": "no_previous_data"},
                properties=_WAIT,
            )
            return

        current = summary["recovered_total"]
        previous = summary["previous"]["recovered_total"]
        spec = bar_chart(
            id="recovery-comparison",
            title=f"Recupero vs período anterior · {summary['period_label']}",
            unit="MXN",
            labels=["Período actual", "Período anterior"],
            values=[current, previous],
        )
        delta_pct = summary["delta_pct"]
        if delta_pct is None:
            trend = "sin variación significativa"
        elif delta_pct > 0:
            trend = f"mejoró {delta_pct} puntos"
        elif delta_pct < 0:
            trend = f"bajó {abs(delta_pct)} puntos"
        else:
            trend = "se mantuvo igual"
        message = (
            f"Actual {format_money(current)} vs anterior {format_money(previous)}: {trend}."
        )
        await self._send_visualization(message, spec)
        await self.speak(
            f"Comparados con el período anterior, pasaste de "
            f"{format_money(previous)} a {format_money(current)}: {trend} "
            "en el porcentaje de recupero."
        )
        await params.result_callback(
            {
                "ok": True,
                "current_total": current,
                "previous_total": previous,
                "delta_pct": delta_pct,
            },
            properties=_WAIT,
        )

    @register_tool(type="normal")
    async def distribucion_deuda(self, params) -> None:
        """Distribución del saldo pendiente por estado de gestión."""
        if not await self._guard(params):
            return
        try:
            dataset = self._dataset()
        except DataSourceError as exc:
            await self._report_error(params, exc)
            return
        rows = distribution_by_status(dataset.get("debtors") or [])
        if not rows:
            await self.speak("No hay deuda registrada para distribuir.")
            await params.result_callback({"ok": True, "empty": True}, properties=_WAIT)
            return
        spec = ring_chart(
            id="debt-distribution",
            title="Saldo pendiente por estado",
            unit="MXN",
            labels=[row["status"] for row in rows],
            values=[row["pending_balance"] for row in rows],
        )
        top_status = rows[0]
        message = (
            f"El estado con mayor saldo es {top_status['status']} "
            f"con {format_money(top_status['pending_balance'])}."
        )
        await self._send_visualization(message, spec)
        await self.speak(
            f"Por estados, {top_status['status']} concentra el mayor saldo "
            f"pendiente: {format_money(top_status['pending_balance'])}. "
            "En el panel vas a ver la distribución completa."
        )
        await params.result_callback(
            {"ok": True, "distribution": rows}, properties=_WAIT
        )

    @register_tool(type="normal")
    async def top_deudores(self, params, limite: int = 10) -> None:
        """Ranking de deudores con mayor saldo pendiente (autorización: adapter)."""
        if not await self._guard(params):
            return
        try:
            dataset = self._dataset()
        except DataSourceError as exc:
            await self._report_error(params, exc)
            return
        limit = max(1, min(int(limite or 10), 20))
        rows = top_debtors(dataset.get("debtors") or [], limit)
        if not rows:
            await self.speak("No hay deudores registrados.")
            await params.result_callback({"ok": True, "empty": True}, properties=_WAIT)
            return
        spec = table(
            id="top-debtors",
            title=f"Top {len(rows)} por saldo pendiente",
            headers=["Deudor", "Saldo pendiente", "Estado"],
            rows=[
                [row["name"], row["pending_balance"], row["status"]]
                for row in rows
            ],
        )
        leader = rows[0]
        message = (
            f"Mayor saldo: {leader['name']} con {format_money(leader['pending_balance'])}."
        )
        await self._send_visualization(message, spec)
        await self.speak(
            f"El caso con mayor saldo pendiente es {leader['name']}, "
            f"con {format_money(leader['pending_balance'])}. "
            "El ranking completo está en el panel."
        )
        await params.result_callback({"ok": True, "count": len(rows)}, properties=_WAIT)

    def _today(self):
        from app.utils.dates import today_in_tz

        return today_in_tz(self.session.timezone)

    def _recovery_speech(self, summary: dict[str, Any]) -> str:
        """Resumen hablado SOLO con valores calculados. Sin datos → se dice."""
        parts = [
            (
                f"Durante {summary['period_label']} recuperaste "
                f"{format_money(summary['recovered_total'])}."
            )
        ]
        if summary["recovery_pct"] is not None:
            parts.append(f"El porcentaje de recupero es {summary['recovery_pct']} por ciento.")
        best = summary.get("best_day")
        if best and float(best.get("amount") or 0) > 0:
            day = best["date"]
            parts.append(
                f"El día con mayor recuperación fue el {day} con "
                f"{format_money(float(best['amount']))}."
            )
        if summary.get("pending_end") is not None:
            parts.append(f"Queda un saldo pendiente de {format_money(summary['pending_end'])}.")
        return " ".join(parts)