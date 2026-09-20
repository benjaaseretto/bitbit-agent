"""Estado de sesión bitbit para runtime Pipecat."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class BitbitSession:
    call_id: str = ""
    nombre_agente: str = "Ana"
    nombre_deudor: str = "Cliente"
    nombre_empresa: str = "Bitbit"
    amount: float = 1500.0
    due_balance: float = 1500.0
    due_date: str = ""
    dias_mora: int = 0
    max_dias: int = 7
    timezone: str = "America/Mexico_City"
    monto_deuda_palabras: str = ""
    fecha_limite: str = ""
    commitment_date: Optional[str] = None
    commitment_date_spoken: Optional[str] = None
    final_status: Optional[str] = None
    current_node_id: str = ""
    phase: str = "identity"  # identity | opening | negotiation | done
    negotiation_attempts: int = 0
    dates_intentions: list[str] = field(default_factory=list)
    last_kb_answer: Optional[str] = None
    kb_repeats: int = 0
    knowledge_base: list[dict[str, Any]] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)

    def as_template_vars(self) -> dict[str, Any]:
        return {
            "nombre_agente": self.nombre_agente,
            "nombre_deudor": self.nombre_deudor,
            "nombre_empresa": self.nombre_empresa,
            "dias_mora": self.dias_mora,
            "max_dias": self.max_dias,
            "monto_deuda_palabras": self.monto_deuda_palabras,
            "fecha_vencimiento": self.due_date,
            "commitment_date": self.commitment_date or "",
            "commitment_date_spoken": self.commitment_date_spoken or "",
            "fecha_limite": self.fecha_limite,
            **self.variables,
        }

    def result_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "final_status": self.final_status,
            "commitment_date": self.commitment_date,
            "phase": self.phase,
            "nombre_deudor": self.nombre_deudor,
        }
