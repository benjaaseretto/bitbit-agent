"""Índice de tasks de colly aún no portadas a Pipecat.

Cada entrada documenta el `task_type` del spec y el módulo origen en
legacy-agent-voice / colly-agent. Implementá un script en `app/tasks/`
y registralo con `@register_task` — no hace falta tocar el bot.
"""
from __future__ import annotations

from typing import Any, Dict

# task_type → metadata (origen colly + estado)
COLLY_TASK_STUBS: Dict[str, Dict[str, Any]] = {
    "CallScreeningTask": {
        "module": "agents/tasks/call_screening.py",
        "status": "stub",
        "notes": "AMD / screening pre-identidad.",
    },
    "FieldVerificationTask": {
        "module": "agents/tasks/field_verification.py",
        "status": "stub",
        "notes": "Verificación por campos (RUT, DOB, etc.).",
    },
    "KBATask": {
        "module": "agents/tasks/kba.py",
        "status": "stub",
        "notes": "Knowledge-based authentication.",
    },
    "NegotiationTask": {
        "module": "agents/tasks/negotiation.py",
        "status": "stub",
        "notes": "Negociación de cobranza clásica; ver AppointmentSchedulingTask para agenda médica.",
    },
    "NegotiationTaskV2": {
        "module": "agents/tasks/negotiation_v2.py",
        "status": "stub",
    },
    "NegotiationOptionsTask": {
        "module": "agents/tasks/negotiation_options.py",
        "status": "stub",
    },
    "NegotiationConvenioTask": {
        "module": "agents/tasks/negotiation_convenio.py",
        "status": "stub",
    },
    "MultiProductNegotiationTask": {
        "module": "agents/tasks/multi_product_negotiation.py",
        "status": "stub",
    },
    "PaymentIntentionDateTask": {
        "module": "agents/tasks/payment_intention_date.py",
        "status": "stub",
    },
    "PaymentCommitmentTask": {
        "module": "agents/tasks/payment_commitment.py",
        "status": "stub",
    },
    "NextContactTask": {
        "module": "agents/tasks/next_contact.py",
        "status": "stub",
    },
    "OfferSelectionTask": {
        "module": "agents/tasks/offer_selection.py",
        "status": "stub",
    },
    "OfferAcceptanceTask": {
        "module": "agents/tasks/offer_acceptance.py",
        "status": "stub",
    },
    "CollectPaymentMethodTask": {
        "module": "agents/tasks/collect_payment_method.py",
        "status": "stub",
    },
    "PayConfirmationTask": {
        "module": "agents/tasks/pay_confirmation.py",
        "status": "stub",
    },
    "DateSelectionTask": {
        "module": "agents/tasks/date_selection.py",
        "status": "stub",
    },
    "DateConfirmationTask": {
        "module": "agents/tasks/date_confirmation.py",
        "status": "stub",
    },
    "AmountSelectionTask": {
        "module": "agents/tasks/amount_selection.py",
        "status": "stub",
    },
    "FormTask": {
        "module": "agents/tasks/form.py",
        "status": "stub",
    },
    "QuestionnaireTask": {
        "module": "agents/tasks/questionnaire.py",
        "status": "stub",
    },
    "SalesTask": {
        "module": "agents/tasks/sales.py",
        "status": "stub",
    },
    "SplitPaymentScheduleTask": {
        "module": "agents/tasks/split_payment_schedule.py",
        "status": "stub",
    },
    "SplitPaymentScheduleLadderTask": {
        "module": "agents/tasks/split_payment_schedule_ladder.py",
        "status": "stub",
    },
    "ContractsTask": {
        "module": "agents/tasks/contracts.py",
        "status": "stub",
    },
}


def stub_message(task_type: str) -> str:
    meta = COLLY_TASK_STUBS.get(task_type) or {}
    origin = meta.get("module", "colly-agent/app/agents/tasks/")
    return (
        f"Task '{task_type}' aún no portada a Pipecat. "
        f"Origen colly: {origin}. "
        f"Creá app/tasks/<nombre>.py y registrá con @register_task."
    )
