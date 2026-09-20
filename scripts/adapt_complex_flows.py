#!/usr/bin/env python3
"""Adapta los N flujos más complejos de colly-agent a sanatorio / venta de equipos.

Incluye:
- Specs con topología preservada (nombres/prompts/outcomes reescritos)
- KB correspondiente por flujo (formato lista question/answer como clinica_vida)

Uso:
  python scripts/adapt_complex_flows.py --limit 45
"""
from __future__ import annotations

import argparse
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
COLY_SPECS = Path("/Users/benjaminaseretto/Documents/Agent/colly-agent/app/flow_graph/specs")
COLY_KB = Path("/Users/benjaminaseretto/Documents/Agent/colly-agent/app/kb")
OUT_SPECS = ROOT / "app" / "flow_graph" / "specs"
OUT_KB = ROOT / "app" / "kb" / "complex"
INDEX = OUT_SPECS / "INDEX.md"

SANATORIO_BRANDS = [
    ("aurora_salud", "Sanatorio Aurora"),
    ("norte_vital", "Clínica Norte Vital"),
    ("pacifico_med", "Sanatorio Pacífico"),
    ("andes_care", "Andes Care"),
    ("rio_blanco", "Sanatorio Río Blanco"),
    ("sol_integral", "Centro Sol Integral"),
    ("vita_sur", "Vita Sur"),
    ("med_plaza", "MedPlaza"),
    ("horizonte_clinico", "Horizonte Clínico"),
    ("bosque_salud", "Bosque Salud"),
    ("celeste_hospital", "Hospital Celeste"),
    ("mirador_medico", "Mirador Médico"),
    ("laguna_clinica", "Clínica Laguna"),
    ("altos_del_sur", "Altos del Sur"),
    ("portal_salud", "Portal Salud"),
    ("estrella_medica", "Estrella Médica"),
    ("camino_verde", "Camino Verde Salud"),
    ("faro_clinico", "Faro Clínico"),
    ("sierra_vital", "Sierra Vital"),
    ("costa_salud", "Costa Salud"),
    ("nube_blanca", "Nube Blanca"),
    ("prisma_med", "Prisma Med"),
    ("valle_cuidado", "Valle Cuidado"),
    ("origen_salud", "Origen Salud"),
    ("lumen_clinica", "Lumen Clínica"),
]

EQUIPOS_BRANDS = [
    ("tecno_medico", "TecnoMédico Equipos"),
    ("oxigeno_plus", "Oxígeno Plus"),
    ("labtech_sur", "LabTech Sur"),
    ("imagen_pro", "ImagenPro"),
    ("quirurgica_nova", "Quirúrgica Nova"),
    ("monitor_vital", "Monitor Vital Systems"),
    ("steril_pack", "SterilPack"),
    ("infusion_max", "Infusión Max"),
    ("diagno_lab", "DiagnoLab Equipos"),
    ("rehab_motion", "Rehab Motion"),
    ("dental_core", "DentalCore"),
    ("cardio_gear", "CardioGear"),
    ("neonatal_kit", "Neonatal Kit"),
    ("ultra_scan", "UltraScan"),
    ("bio_analyze", "BioAnalyze"),
    ("or_suite", "OR Suite"),
    ("home_care_tech", "HomeCare Tech"),
    ("pharmacy_auto", "Pharmacy Auto"),
    ("sterile_flow", "Sterile Flow"),
    ("pulse_line", "Pulse Line"),
]

SANATORIO_OUTCOMES = {
    "Compromiso": "Cita agendada",
    "Sin compromiso": "Sin cita",
    "Pagado": "Ya atendido",
    "Ya pagó": "Ya atendido",
    "Ya pagué": "Ya atendido",
    "Pagado declarado": "Ya atendido",
    "Intención de pago": "Intención de agendar",
    "Intención de pago cuota atrasada": "Intención de reprogramar",
    "Oferta cuota atrasada": "Oferta reprogramación",
    "acepta cuota atrasada": "Acepta reprogramación",
    "no acepta": "No acepta",
    "No reconoce la deuda": "No reconoce la cita",
    "No reconoce deuda": "No reconoce la cita",
    "Reconoce compra": "Confirma datos",
    "Confirma negativa": "Niega datos",
    "Fecha tentativa capturada": "Fecha tentativa capturada",
    "Sin fecha": "Sin fecha",
    "Próximo contacto": "Próximo contacto",
    "Solicita próximo contacto": "Solicita próximo contacto",
    "Rechaza regularizar": "Rechaza agendar",
    "Rechaza Pago Total": "Rechaza paquete completo",
    "Pago Domiciliado o Debito Automático": "Tiene cobertura prepaga",
    "Derivacion": "Derivacion",
    "Transferencia": "Transferencia",
    "Seleccion": "Seleccion",
    "Completado": "Completado",
    "Cancelado": "Cancelado",
    "Acepta": "Acepta",
    "No acepta": "No acepta",
    "Rechaza": "Rechaza",
    "Cambiar": "Cambiar",
    "Continuar": "Continuar",
    "Cliente ocupado": "Cliente ocupado",
    "No colabora": "No colabora",
    "Fuera del país": "Fuera de la ciudad",
    "Terremoto": "Emergencia",
    "confirma la condonación": "confirma el plan",
    "rechaza la confirmación": "rechaza la confirmación",
    "Acuerdo previo": "Cita previa",
    "No Autenticado": "No Autenticado",
    "Fallecimiento": "Fallecimiento",
    "Fallecido": "Fallecido",
    "Tercero": "Tercero",
    "MaxTriesExceeded": "MaxTriesExceeded",
    "Entregado": "Entregado",
    "Equivocado": "Equivocado",
    "Recado conocido": "Recado conocido",
    "Buzon de Voz": "Buzon de Voz",
    "Sí": "Sí",
    "Si": "Si",
    "No": "No",
    "Repetir": "Repetir",
    "Recontacto": "Recontacto",
    "always": "always",
    "default": "default",
}

EQUIPOS_OUTCOMES = {
    **SANATORIO_OUTCOMES,
    "Compromiso": "Pedido confirmado",
    "Sin compromiso": "Sin pedido",
    "Pagado": "Ya compró",
    "Ya pagó": "Ya compró",
    "Ya pagué": "Ya compró",
    "Pagado declarado": "Ya compró",
    "Intención de pago": "Intención de compra",
    "Intención de pago cuota atrasada": "Intención de financiamiento",
    "Oferta cuota atrasada": "Oferta financiamiento",
    "acepta cuota atrasada": "Acepta financiamiento",
    "No reconoce la deuda": "No reconoce la cotización",
    "No reconoce deuda": "No reconoce la cotización",
    "Reconoce compra": "Reconoce cotización",
    "Rechaza regularizar": "Rechaza oferta",
    "Rechaza Pago Total": "Rechaza compra total",
    "Pago Domiciliado o Debito Automático": "Quiere financiamiento",
    "confirma la condonación": "confirma la cotización",
    "Acuerdo previo": "Pedido previo",
    "Fuera del país": "Fuera de cobertura logística",
}

SANATORIO_TASK_MAP = {
    "NegotiationTaskV2": "AppointmentSchedulingTask",
    "NegotiationTask": "AppointmentSchedulingTask",
    "MultiProductNegotiationTask": "AppointmentSchedulingTask",
    "PaymentIntentionDateTask": "AppointmentSchedulingTask",
    "OfferSelectionTask": "OfferSelectionTask",
    "NextContactTask": "NextContactTask",
    "FormTask": "FormTask",
    "FieldVerificationTask": "FieldVerificationTask",
    "KbaTask": "KBATask",
    "KBATask": "KBATask",
    "QuestionnaireTask": "QuestionnaireTask",
    "IdentityVerificationTask": "IdentityVerificationTask",
}

EQUIPOS_TASK_MAP = {
    "NegotiationTaskV2": "NegotiationTaskV2",
    "NegotiationTask": "NegotiationTaskV2",
    "MultiProductNegotiationTask": "MultiProductNegotiationTask",
    "PaymentIntentionDateTask": "PaymentIntentionDateTask",
    "OfferSelectionTask": "OfferSelectionTask",
    "NextContactTask": "NextContactTask",
    "FormTask": "FormTask",
    "FieldVerificationTask": "FieldVerificationTask",
    "KbaTask": "KBATask",
    "KBATask": "KBATask",
    "QuestionnaireTask": "QuestionnaireTask",
    "IdentityVerificationTask": "IdentityVerificationTask",
}

DEBT_PHRASE_SANATORIO = [
    (r"(?i)\bdeuda\b", "cita pendiente"),
    (r"(?i)\bsaldo\b", "turno"),
    (r"(?i)\bmora\b", "atraso de agenda"),
    (r"(?i)\bcobranza\b", "coordinación de agenda"),
    (r"(?i)\bpago\b", "turno"),
    (r"(?i)\bpagar\b", "agendar"),
    (r"(?i)\bpagó\b", "asistió"),
    (r"(?i)\bcompromiso de pago\b", "cita confirmada"),
    (r"(?i)\bcompromiso\b", "cita"),
    (r"(?i)\bcuota\b", "sesión"),
    (r"(?i)\brefinanciamiento\b", "reprogramación"),
    (r"(?i)\bcondonaci[oó]n\b", "paquete preventivo"),
    (r"(?i)\bdeudor\b", "paciente"),
    (r"(?i)\bcliente\b", "paciente"),
    (r"(?i)\bmonto\b", "especialidad"),
    (r"(?i)\bvencimiento\b", "fecha propuesta"),
    (r"(?i)\bregularizar\b", "confirmar la cita"),
    (r"(?i)\bmedios de pago\b", "coberturas y prepaga"),
    (r"(?i)\bbanco\b", "sanatorio"),
    (r"(?i)\btarjeta\b", "credencial"),
]

DEBT_PHRASE_EQUIPOS = [
    (r"(?i)\bdeuda\b", "cotización"),
    (r"(?i)\bsaldo\b", "importe"),
    (r"(?i)\bmora\b", "seguimiento comercial"),
    (r"(?i)\bcobranza\b", "seguimiento de venta"),
    (r"(?i)\bpago\b", "compra"),
    (r"(?i)\bpagar\b", "cerrar la compra"),
    (r"(?i)\bpagó\b", "compró"),
    (r"(?i)\bcompromiso de pago\b", "pedido confirmado"),
    (r"(?i)\bcompromiso\b", "pedido"),
    (r"(?i)\bcuota\b", "cuota de financiamiento"),
    (r"(?i)\brefinanciamiento\b", "financiamiento"),
    (r"(?i)\bcondonaci[oó]n\b", "descuento de lanzamiento"),
    (r"(?i)\bdeudor\b", "comprador"),
    (r"(?i)\bcliente\b", "comprador"),
    (r"(?i)\bvencimiento\b", "vigencia de oferta"),
    (r"(?i)\bregularizar\b", "cerrar la oferta"),
    (r"(?i)\bmedios de pago\b", "formas de pago y financiamiento"),
]

SANATORIO_CORE_KB = [
    {
        "question": "¿Qué especialidades tienen? | ¿Qué médicos atienden?",
        "answer": "En {nombre_empresa} coordinamos {especialidad} y otras especialidades según agenda. Esta llamada es para su consulta de {especialidad} con {nombre_medico}.",
    },
    {
        "question": "¿Dónde queda? | ¿Cuál es la dirección? | ¿Sucursal?",
        "answer": "La atención es en {sucursal}. Si necesita cómo llegar, indíqueme y le oriento con lo registrado.",
    },
    {
        "question": "¿Cuánto cuesta? | ¿Aceptan prepaga u obra social?",
        "answer": "Costos y coberturas dependen del convenio. En recepción de {sucursal} confirman el importe. Yo puedo reservar el turno.",
    },
    {
        "question": "¿Qué debo llevar? | ¿Documentos?",
        "answer": "Documento de identidad, credencial de cobertura y estudios previos si los tiene. Llegue unos diez minutos antes.",
    },
    {
        "question": "¿Puedo cancelar o reprogramar?",
        "answer": "Sí, con anticipación según disponibilidad. ¿Quiere que agendemos otra fecha ahora?",
    },
    {
        "question": "¿Atienden urgencias? | Me siento mal",
        "answer": "Urgencias graves: guardia o emergencias. Si es consulta programable de {especialidad}, ofrezco el turno más cercano.",
    },
    {
        "question": "¿Horarios? | ¿Mañana o tarde?",
        "answer": "La agenda de {especialidad} con {nombre_medico} se coordina por franjas. ¿Prefiere mañana o tarde?",
    },
    {
        "question": "¿Dan diagnóstico o receta por teléfono?",
        "answer": "No. Por teléfono solo coordinamos agenda. Diagnóstico e indicaciones las da el médico en consulta.",
    },
    {
        "question": "¿Por qué me llaman?",
        "answer": "Lo contactamos desde {nombre_empresa} para confirmar o agendar su consulta de {especialidad}.",
    },
    {
        "question": "Ya tengo cita | Ya estoy agendado",
        "answer": "Perfecto. Si ya tiene turno, solo confirmamos. ¿Desea dejar registrado que ya estaba agendado?",
    },
]

EQUIPOS_CORE_KB = [
    {
        "question": "¿Qué equipos venden? | ¿Catálogo?",
        "answer": "En {nombre_empresa} trabajamos la línea {producto} y accesorios relacionados. Esta llamada es para su cotización de {producto}.",
    },
    {
        "question": "¿Plazos de entrega? | ¿Cuándo llega?",
        "answer": "El plazo depende de stock y zona logística. Al confirmar el pedido le indico la ventana de entrega estimada.",
    },
    {
        "question": "¿Financiamiento? | ¿Cuotas?",
        "answer": "Hay contado y planes en cuotas sujetos a aprobación comercial. ¿Quiere que revise opciones para {producto}?",
    },
    {
        "question": "¿Garantía? | ¿Servicio técnico?",
        "answer": "Cada equipo incluye garantía de fábrica. El detalle queda en la cotización y el contrato de servicio.",
    },
    {
        "question": "¿Puedo pedir demo o prueba?",
        "answer": "Sí, coordinamos demo técnica con un especialista según el equipo y disponibilidad.",
    },
    {
        "question": "¿Precio? | ¿Cotización?",
        "answer": "Le confirmo importe y vigencia de la oferta de {producto}. No invento precios fuera de lo registrado.",
    },
    {
        "question": "¿Instalación e insumos?",
        "answer": "Podemos incluir instalación, capacitación e insumos iniciales según el paquete contratado.",
    },
    {
        "question": "¿Por qué me llaman?",
        "answer": "Lo contactamos desde {nombre_empresa} por su interés o cotización de {producto}.",
    },
    {
        "question": "Ya compré | Ya cerré el pedido",
        "answer": "Excelente. Registramos que el pedido ya está cerrado y, si corresponde, coordinamos seguimiento de entrega.",
    },
    {
        "question": "¿Factura A / B? | ¿Datos fiscales?",
        "answer": "Al confirmar el pedido pedimos datos de facturación. Puedo tomar razón social y CUIT/RUT ahora si lo desea.",
    },
]


def rank_specs(limit: int) -> List[Path]:
    rows: List[Tuple[int, int, Path]] = []
    for p in COLY_SPECS.glob("*.json"):
        if " 2.json" in p.name:
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        nodes = (data.get("flow_graph") or {}).get("nodes") or {}
        rows.append((len(nodes), p.stat().st_size, p))
    rows.sort(key=lambda t: (-t[0], -t[1]))
    return [p for _, __, p in rows[:limit]]


def rewrite_text(text: str, phrases: List[Tuple[str, str]], brand: str, old_brands: List[str]) -> str:
    out = text
    for old in old_brands:
        if old and len(str(old)) > 2:
            out = re.sub(re.escape(str(old)), brand, out, flags=re.I)
    for pat, repl in phrases:
        out = re.sub(pat, repl, out)
    return out


def remap_key(key: str, outcomes: Dict[str, str]) -> str:
    return outcomes.get(key, key)


def walk_remap(
    obj: Any,
    outcomes: Dict[str, str],
    phrases: List[Tuple[str, str]],
    brand: str,
    old_brands: List[str],
) -> Any:
    if isinstance(obj, dict):
        new: Dict[str, Any] = {}
        for k, v in obj.items():
            nk = remap_key(k, outcomes) if k in outcomes else k
            if k in ("status", "label") and isinstance(v, str):
                new[nk] = outcomes.get(v, rewrite_text(v, phrases, brand, old_brands))
            elif k in (
                "prompt",
                "custom_instructions",
                "identity_identificacion_breve",
                "invalid_date_message",
                "invalid_date_retry_message",
                "description",
                "say",
                "text",
            ) and isinstance(v, str):
                new[nk] = rewrite_text(v, phrases, brand, old_brands)
            elif k == "prompt_by" and isinstance(v, dict):
                new[nk] = {
                    (remap_key(sk, outcomes) if sk in outcomes else sk): (
                        rewrite_text(sv, phrases, brand, old_brands)
                        if isinstance(sv, str)
                        else walk_remap(sv, outcomes, phrases, brand, old_brands)
                    )
                    for sk, sv in v.items()
                }
            elif k in ("on", "on_by", "goto_by") and isinstance(v, dict):
                new[nk] = {
                    remap_key(sk, outcomes): walk_remap(sv, outcomes, phrases, brand, old_brands)
                    for sk, sv in v.items()
                }
            else:
                new[nk] = walk_remap(v, outcomes, phrases, brand, old_brands)
        return new
    if isinstance(obj, list):
        return [walk_remap(x, outcomes, phrases, brand, old_brands) for x in obj]
    if isinstance(obj, str):
        if obj in outcomes:
            return outcomes[obj]
        return rewrite_text(obj, phrases, brand, old_brands)
    return obj


def remap_tasks(nodes: Dict[str, Any], task_map: Dict[str, str], vertical: str) -> None:
    for node in nodes.values():
        if node.get("type") != "task":
            continue
        tt = node.get("task_type")
        if tt in task_map:
            node["task_type"] = task_map[tt]
        params = node.setdefault("params", {})
        if vertical == "sanatorio" and node["task_type"] == "AppointmentSchedulingTask":
            params.setdefault(
                "custom_instructions",
                "Sos asistente de agenda de sanatorio. No des diagnósticos ni recetas. "
                "Confirmá día y franja. Ofrecé alternativas si rechaza. Tono empático y breve.",
            )
            params.setdefault("max_attempts", 3)
        if vertical == "equipos" and node["task_type"] in (
            "NegotiationTaskV2",
            "MultiProductNegotiationTask",
        ):
            params.setdefault(
                "custom_instructions",
                "Sos asesor comercial de equipos médicos. Presentá beneficios, plazos de entrega "
                "y opciones de financiamiento. No inventes precios fuera de la KB. Cerrá con pedido o próximo contacto.",
            )


def extract_old_brands(data: dict, src: Path) -> List[str]:
    brands: List[str] = []
    cat = data.get("flow_catalog") or {}
    cfg = data.get("flow_config") or {}
    for v in (cat.get("visible_name"), cfg.get("company_pronunciation")):
        if isinstance(v, str):
            brands.append(v)
    brands.append(src.stem.replace("_flow_graph", "").replace("_", " "))
    return brands


def build_catalog(flow_key: str, visible: str, vertical: str, source_file: str, n_nodes: int) -> dict:
    if vertical == "sanatorio":
        fields = [
            {"label": "Nombre del paciente", "field": "name", "type": "text", "required": True},
            {"label": "Nombre del sanatorio", "field": "company_name", "type": "text", "required": True},
            {"label": "Especialidad / estudio", "field": "especialidad", "type": "text", "required": True},
            {"label": "Médico", "field": "nombre_medico", "type": "text", "required": False},
            {"label": "Sucursal", "field": "sucursal", "type": "text", "required": False},
            {"label": "Cobertura / prepaga", "field": "cobertura", "type": "text", "required": False},
        ]
        desc = (
            f"Flujo complejo ({n_nodes} nodos) sanatorio: identidad, agenda, reprogramación, "
            f"coberturas y derivaciones."
        )
    else:
        fields = [
            {"label": "Nombre del comprador", "field": "name", "type": "text", "required": True},
            {"label": "Empresa / marca", "field": "company_name", "type": "text", "required": True},
            {"label": "Equipo / línea", "field": "producto", "type": "text", "required": True},
            {"label": "Cantidad", "field": "cantidad", "type": "number", "required": False},
            {"label": "Sucursal / depósito", "field": "sucursal", "type": "text", "required": False},
            {"label": "Modalidad de pago", "field": "financiamiento", "type": "text", "required": False},
        ]
        desc = (
            f"Flujo complejo ({n_nodes} nodos) venta de equipos: identidad, cotización, "
            f"multiproducto, financiamiento y próximo contacto."
        )
    return {
        "platform_flow_key": f"{flow_key}_flow",
        "visible_name": visible,
        "flow_type": "test",
        "enabled": True,
        "description": desc,
        "fields": fields,
        "knowledge_base": {
            "file": f"complex/{flow_key}.json",
            "company_id": f"{flow_key}-demo",
            "description": f"Base de conocimiento de {visible}.",
        },
        "company_id": f"{flow_key}-demo",
        "meta": {
            "vertical": vertical,
            "structural_pattern": source_file,
            "node_count": n_nodes,
            "runtime_note": (
                "IdentityVerificationTask y AppointmentSchedulingTask implementadas; "
                "otras task_type en app/tasks/stubs.py."
            ),
        },
    }


def load_source_kb(spec_data: dict) -> Optional[List[dict]]:
    kb_name = ((spec_data.get("flow_catalog") or {}).get("knowledge_base") or {}).get("file")
    if not kb_name:
        return None
    path = COLY_KB / kb_name
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and isinstance(raw.get("faqs"), list):
        return raw["faqs"]
    return None


def adapt_kb_entry(entry: dict, phrases: List[Tuple[str, str]], brand: str, old_brands: List[str]) -> Optional[dict]:
    q = entry.get("question") or entry.get("q")
    a = entry.get("answer") or entry.get("a")
    if not isinstance(q, str) or not isinstance(a, str):
        return None
    out: Dict[str, Any] = {
        "question": rewrite_text(q, phrases, brand, old_brands),
        "answer": rewrite_text(a, phrases, brand, old_brands),
    }
    # Drop available_when tied to debt dims — replace with soft domain note only if generic
    return out


def build_kb(
    visible: str,
    vertical: str,
    source_kb: Optional[List[dict]],
    phrases: List[Tuple[str, str]],
    old_brands: List[str],
) -> List[dict]:
    core = copy.deepcopy(SANATORIO_CORE_KB if vertical == "sanatorio" else EQUIPOS_CORE_KB)
    # Brand-tune core answers lightly
    for item in core:
        item["answer"] = item["answer"].replace("{nombre_empresa}", "{nombre_empresa}")

    adapted: List[dict] = []
    seen_q = set()
    for item in core:
        adapted.append(item)
        seen_q.add(item["question"].split("|")[0].strip().lower())

    if source_kb:
        for entry in source_kb:
            converted = adapt_kb_entry(entry, phrases, visible, old_brands)
            if not converted:
                continue
            key = converted["question"].split("|")[0].strip().lower()
            if key in seen_q:
                continue
            # Skip entries that still look like pure debt after rewrite heuristics fail
            blob = (converted["question"] + " " + converted["answer"]).lower()
            if any(w in blob for w in ("collection", "charge-off", "write-off")):
                continue
            adapted.append(converted)
            seen_q.add(key)

    # Vertical extras keyed by brand flavor
    if vertical == "sanatorio":
        extras = [
            {
                "question": "¿Estudios previos? | ¿Necesito análisis?",
                "answer": f"Según el motivo de consulta en {visible}, recepción indica si debe traer estudios. Puedo anotar el pedido al agendar.",
            },
            {
                "question": "¿Internación? | ¿Cirugía?",
                "answer": "Para internación o quirófano derivamos a admisión. En esta llamada priorizamos consulta ambulatoria o estudio.",
            },
            {
                "question": "¿Resultados de estudios?",
                "answer": "Los resultados los entrega el área correspondiente o el médico. Yo no informo hallazgos clínicos por teléfono.",
            },
        ]
    else:
        extras = [
            {
                "question": "¿Capacitación del personal?",
                "answer": f"{visible} puede incluir inducción operativa al entregar { '{producto}' }. Confirmamos al cerrar el pedido.",
            },
            {
                "question": "¿Repuestos y consumibles?",
                "answer": "Hay catálogo de consumibles y repuestos. Puedo sumarlos a la misma cotización si lo necesita.",
            },
            {
                "question": "¿Contrato de mantenimiento?",
                "answer": "Ofrecemos planes de mantenimiento preventivo anuales. ¿Quiere incluirlo en la propuesta?",
            },
        ]
    for item in extras:
        key = item["question"].split("|")[0].strip().lower()
        if key not in seen_q:
            adapted.append(item)
    return adapted


def adapt_one(src: Path, flow_key: str, visible: str, vertical: str) -> Tuple[dict, List[dict]]:
    data = json.loads(src.read_text(encoding="utf-8"))
    outcomes = SANATORIO_OUTCOMES if vertical == "sanatorio" else EQUIPOS_OUTCOMES
    phrases = DEBT_PHRASE_SANATORIO if vertical == "sanatorio" else DEBT_PHRASE_EQUIPOS
    task_map = SANATORIO_TASK_MAP if vertical == "sanatorio" else EQUIPOS_TASK_MAP
    old_brands = extract_old_brands(data, src)

    adapted = walk_remap(copy.deepcopy(data), outcomes, phrases, visible, old_brands)
    nodes = (adapted.get("flow_graph") or {}).get("nodes") or {}
    remap_tasks(nodes, task_map, vertical)

    n_nodes = len(nodes)
    adapted["flow_catalog"] = build_catalog(flow_key, visible, vertical, src.name, n_nodes)
    adapted["flow_config"] = {"company_pronunciation": visible, "vertical": vertical}

    source_kb = load_source_kb(data)
    kb = build_kb(visible, vertical, source_kb, phrases, old_brands)
    return adapted, kb


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=45)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not COLY_SPECS.is_dir():
        print(f"No encuentro colly-agent specs en {COLY_SPECS}")
        return 1

    sources = rank_specs(args.limit)
    brands = list(SANATORIO_BRANDS) + list(EQUIPOS_BRANDS)
    i = 1
    while len(brands) < args.limit:
        brands.append((f"sanatorio_demo_{i:02d}", f"Sanatorio Demo {i:02d}"))
        i += 1

    OUT_SPECS.mkdir(parents=True, exist_ok=True)
    OUT_KB.mkdir(parents=True, exist_ok=True)

    index_rows = []
    for idx, src in enumerate(sources):
        flow_key, visible = brands[idx]
        vertical = "sanatorio" if idx < 25 else "equipos"
        adapted, kb = adapt_one(src, flow_key, visible, vertical)
        n = len(adapted["flow_graph"]["nodes"])
        spec_path = OUT_SPECS / f"{flow_key}_flow_graph.json"
        kb_path = OUT_KB / f"{flow_key}.json"
        index_rows.append(
            {
                "i": idx + 1,
                "flow_key": flow_key,
                "visible": visible,
                "vertical": vertical,
                "nodes": n,
                "kb_entries": len(kb),
                "pattern": src.name,
            }
        )
        if args.dry_run:
            print(
                f"{idx+1:02d} {vertical:10s} {flow_key:22s} nodes={n:3d} kb={len(kb):2d} ← {src.name}"
            )
            continue
        spec_path.write_text(json.dumps(adapted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        kb_path.write_text(json.dumps(kb, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if not args.dry_run:
        lines = [
            "# Flujos complejos adaptados (sanatorio / venta equipos)",
            "",
            "Cada fila tiene **spec** + **KB** (`app/kb/complex/<flow_key>.json`).",
            "Patrón estructural de colly-agent; marcas y textos reescritos.",
            "",
            "```bash",
            "BITBIT_FLOW_KEY=aurora_salud_flow python -m app.pipecat_runtime.bot --transport webrtc",
            "```",
            "",
            "| # | flow_key | Vertical | Nodos | KB | Patrón |",
            "|---|----------|----------|------:|---:|--------|",
        ]
        for r in index_rows:
            lines.append(
                f"| {r['i']} | `{r['flow_key']}_flow` | {r['vertical']} | {r['nodes']} | {r['kb_entries']} | `{r['pattern']}` |"
            )
        lines += [
            "",
            "## Archivos",
            "",
            f"- Specs: `{OUT_SPECS.relative_to(ROOT)}/`",
            f"- KB: `{OUT_KB.relative_to(ROOT)}/`",
            "",
            "## Runtime",
            "",
            "- Implementadas: `IdentityVerificationTask`, `AppointmentSchedulingTask`.",
            "- Resto: `app/tasks/stubs.py` (portar bajo demanda).",
            "",
        ]
        INDEX.write_text("\n".join(lines), encoding="utf-8")
        print(f"OK: {len(index_rows)} specs → {OUT_SPECS}")
        print(f"OK: {len(index_rows)} KB → {OUT_KB}")
        print(f"OK: índice → {INDEX}")
        print(f"KB entries total: {sum(r['kb_entries'] for r in index_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
