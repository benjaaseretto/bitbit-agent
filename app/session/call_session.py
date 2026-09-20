"""Estado de sesión de llamada para runtime Pipecat."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CallSession:
    """Sesión de conversación (identidad → fase de negocio → cierre)."""

    call_id: str = ""
    nombre_agente: str = "Ana"
    nombre_deudor: str = "Paciente"  # nombre del contacto / paciente
    nombre_empresa: str = "Clínica Vida"
    especialidad: str = "medicina general"
    nombre_medico: str = "el médico de turno"
    sucursal: str = "sucursal Centro"
    max_dias: int = 7
    timezone: str = "America/Mexico_City"
    fecha_limite: str = ""
    fecha_turno: str = ""
    fecha_turno_spoken: str = ""
    hora_turno: str = ""
    hora_turno_spoken: str = ""
    franja_turno: str = ""
    commitment_date: Optional[str] = None
    commitment_date_spoken: Optional[str] = None
    final_status: Optional[str] = None
    current_node_id: str = ""
    phase: str = "identity"  # identity | negotiation | done
    negotiation_attempts: int = 0
    dates_intentions: list[str] = field(default_factory=list)
    last_kb_answer: Optional[str] = None
    kb_repeats: int = 0
    knowledge_base: list[dict[str, Any]] = field(default_factory=list)
    variables: dict[str, Any] = field(default_factory=dict)
    flow_key: str = ""

    def as_template_vars(self) -> dict[str, Any]:
        return {
            "nombre_agente": self.nombre_agente,
            "nombre_deudor": self.nombre_deudor,
            "nombre_paciente": self.nombre_deudor,
            "nombre_empresa": self.nombre_empresa,
            "especialidad": self.especialidad,
            "nombre_medico": self.nombre_medico,
            "sucursal": self.sucursal,
            "max_dias": self.max_dias,
            "fecha_turno": self.fecha_turno,
            "fecha_turno_spoken": self.fecha_turno_spoken,
            "hora_turno": self.hora_turno,
            "hora_turno_spoken": self.hora_turno_spoken,
            "franja_turno": self.franja_turno,
            "commitment_date": self.commitment_date or "",
            "commitment_date_spoken": self.commitment_date_spoken or "",
            "fecha_limite": self.fecha_limite,
            "nombre_deudor_completo": self.nombre_deudor,
            "saludo_por_horario": str(self.variables.get("saludo_por_horario") or "Buenos días"),
            **self.variables,
        }

    def result_payload(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "flow_key": self.flow_key,
            "final_status": self.final_status,
            "appointment_date": self.commitment_date,
            "phase": self.phase,
            "nombre_paciente": self.nombre_deudor,
            "especialidad": self.especialidad,
        }
