"""Metadata de la llamada para probar un flujo: JSON + TEST_* del .env (+ Redis opcional).

En colly el body vivía en Redis y se sembraba con TEST_*. Acá el studio local no
necesita Redis: las mismas variables alimentan CallSession.variables para que
los placeholders del spec ({dim_5}, {total_balance_palabras}, …) existan.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.utils.dates import amount_to_words, spoken_date

ROOT = Path(__file__).resolve().parents[2]

# TEST_* (env) → clave en metadata / session.variables
TEST_TO_META: dict[str, str] = {
    "TEST_COUNTRY": "country",
    "TEST_COUNTRY_ID": "country_id",
    "TEST_NAME": "name",
    "TEST_FIRST_NAME": "first_name",
    "TEST_LAST_NAME": "last_name",
    "TEST_AMOUNT": "amount",
    "TEST_DUE_DATE": "due_date",
    "TEST_DUE_BALANCE": "due_balance",
    "TEST_INVOICED_BALANCE": "invoiced_balance",
    "TEST_TOTAL_BALANCE": "total_balance",
    "TEST_PRINCIPAL_BALANCE": "principal_balance",
    "TEST_PROVISION_BALANCE": "provision_balance",
    "TEST_PAID_BALANCE": "paid_balance",
    "TEST_LOAN_AMOUNT": "loan_amount",
    "TEST_INFO_1": "info_1",
    "TEST_INFO_2": "info_2",
    "TEST_INFO_3": "info_3",
    "TEST_INFO_4": "info_4",
    "TEST_INFO_5": "info_5",
    "TEST_INFO_6": "info_6",
    "TEST_INFO_7": "info_7",
    "TEST_INFO_8": "info_8",
    "TEST_INFO_9": "info_9",
    "TEST_INFO_10": "info_10",
    "TEST_DIM_1_ID": "dim_1_id",
    "TEST_DIM_2_ID": "dim_2_id",
    "TEST_DIM_3_ID": "dim_3_id",
    "TEST_DIM_4_ID": "dim_4_id",
    "TEST_DIM_5_ID": "dim_5_id",
    "TEST_DIM_6_ID": "dim_6_id",
    "TEST_DIM_7_ID": "dim_7_id",
    "TEST_DIM_8_ID": "dim_8_id",
    "TEST_DIM_9_ID": "dim_9_id",
    "TEST_DIM_10_ID": "dim_10_id",
    "TEST_DIM_1": "dim_1",
    "TEST_DIM_2": "dim_2",
    "TEST_DIM_3": "dim_3",
    "TEST_DIM_4": "dim_4",
    "TEST_DIM_5": "dim_5",
    "TEST_DIM_6": "dim_6",
    "TEST_DIM_7": "dim_7",
    "TEST_DIM_8": "dim_8",
    "TEST_DIM_9": "dim_9",
    "TEST_DIM_10": "dim_10",
    "TEST_AGENCY": "agency",
    "TEST_CURRENCY": "currency",
    "TEST_COMPANY_NAME": "company_name",
    "TEST_COMPANY_ID": "company_id",
    "TEST_MAX_COMMITMENT_DAYS": "max_commitment_days",
    "TEST_MAX_DIAS": "max_dias",
    "TEST_PORTFOLIO_TYPE": "portfolio_type",
    "TEST_GENDER": "gender",
    "TEST_TIMEZONE": "timezone",
    "TEST_DELINQUENCY": "delinquency",
    "TEST_REFERENCE": "reference",
    "TEST_NOMBRE_AGENTE": "nombre_agente",
    "TEST_ESPECIALIDAD": "especialidad",
    "TEST_NOMBRE_MEDICO": "nombre_medico",
    "TEST_SUCURSAL": "sucursal",
    "TEST_FECHA_TURNO": "fecha_turno",
    "TEST_HORA_TURNO": "hora_turno",
    "TEST_FRANJA_TURNO": "franja_turno",
    "TEST_FLOW_KEY": "flow_key",
    "TEST_PRODUCTO": "producto",
    "TEST_CANTIDAD": "cantidad",
    "TEST_FINANCIAMIENTO": "financiamiento",
    "TEST_MAX_DISCOUNT_PCT": "max_discount_pct",
    "TEST_MIN_PAGO_PCT": "min_pago_pct",
}

_INFRA_TEST_PREFIXES = (
    "TEST_REDIS",
    "TEST_METADATA",
    "TEST_ARI",
    "TEST_PHONE",
    "TEST_CHANNEL",
    "TEST_TRUNK",
    "TEST_PROVIDER",
    "TEST_BOT_VOICE",
    "TEST_PASSWORD",
)
_INFRA_TEST_KEYS = frozenset({"TEST_CALL_ID", "TEST_TODAY", "TEST_METADATA_SOURCE"})

_MONEY_TO_WORDS = (
    ("total_balance", "total_balance_palabras"),
    ("due_balance", "due_balance_palabras"),
    ("amount", "monto_deuda_palabras"),
    ("amount", "amount_palabras"),
    ("loan_amount", "loan_amount_palabras"),
)


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "")
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def _delinquency_days(due_date: str) -> int:
    today_raw = os.getenv("TEST_TODAY")
    today = _parse_date(today_raw) if today_raw else date.today()
    due = _parse_date(due_date)
    if today is None or due is None:
        return 0
    return (today - due).days


def _spoken_money(raw: Any) -> str:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return ""
    try:
        return amount_to_words(float(text))
    except (TypeError, ValueError):
        return text


def _as_meta_float(raw: Any) -> Optional[float]:
    if raw in (None, ""):
        return None
    try:
        return float(str(raw).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None


def _is_infra_test_key(env_key: str) -> bool:
    if env_key in _INFRA_TEST_KEYS:
        return True
    return any(env_key == prefix or env_key.startswith(prefix + "_") for prefix in _INFRA_TEST_PREFIXES)


def _generic_test_field(env_key: str) -> str:
    return env_key[5:].lower()


def apply_test_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Pisa claves del payload si TEST_* está en el entorno (mapeo fijo + el resto en snake_case)."""
    out = dict(data)
    mapped = set(TEST_TO_META)
    for env_key, meta_key in TEST_TO_META.items():
        if env_key in os.environ:
            out[meta_key] = os.environ[env_key]
    for env_key, raw in os.environ.items():
        if not env_key.startswith("TEST_") or env_key in mapped or _is_infra_test_key(env_key):
            continue
        out[_generic_test_field(env_key)] = raw
    return out


def build_payload_from_env(call_id: Optional[str] = None) -> dict[str, Any]:
    """Payload completo desde TEST_* (TEST_METADATA_SOURCE=env)."""
    cid = call_id or os.getenv("TEST_CALL_ID", "1")
    payload: dict[str, Any] = {
        "id": cid,
        "name": os.getenv("TEST_NAME", "Juan Pérez"),
        "first_name": os.getenv("TEST_FIRST_NAME", "Juan"),
        "last_name": os.getenv("TEST_LAST_NAME", "Pérez"),
        "company_name": os.getenv("TEST_COMPANY_NAME", "Clínica Vida"),
        "nombre_agente": os.getenv("TEST_NOMBRE_AGENTE", "Ana"),
        "especialidad": os.getenv("TEST_ESPECIALIDAD", "medicina general"),
        "nombre_medico": os.getenv("TEST_NOMBRE_MEDICO", "la doctora López"),
        "sucursal": os.getenv("TEST_SUCURSAL", "sucursal Centro"),
        "fecha_turno": os.getenv("TEST_FECHA_TURNO", "mañana"),
        "hora_turno": os.getenv("TEST_HORA_TURNO", "10:00"),
        "franja_turno": os.getenv("TEST_FRANJA_TURNO", "mañana"),
        "timezone": os.getenv("TEST_TIMEZONE", "America/Mexico_City"),
        "max_commitment_days": os.getenv("TEST_MAX_COMMITMENT_DAYS", "7"),
        "max_dias": os.getenv("TEST_MAX_DIAS") or os.getenv("TEST_MAX_COMMITMENT_DAYS", "7"),
        "currency": os.getenv("TEST_CURRENCY", "MXN"),
        "country": os.getenv("TEST_COUNTRY", "Mexico"),
        "country_id": os.getenv("TEST_COUNTRY_ID", "146"),
        "amount": os.getenv("TEST_AMOUNT", ""),
        "due_balance": os.getenv("TEST_DUE_BALANCE", ""),
        "total_balance": os.getenv("TEST_TOTAL_BALANCE", ""),
        "due_date": os.getenv("TEST_DUE_DATE", ""),
        "flow_key": os.getenv("TEST_FLOW_KEY") or os.getenv("BITBIT_FLOW_KEY") or "",
    }
    return apply_derived_fields(apply_test_env_overrides(payload))


def apply_derived_fields(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    name = str(out.get("name") or "").strip()
    if name:
        out.setdefault("nombre_deudor", name)
        out.setdefault("nombre_deudor_completo", name)
        out.setdefault("nombre_paciente", name)
    if out.get("max_commitment_days") not in (None, "") and not out.get("max_dias"):
        out["max_dias"] = out["max_commitment_days"]
    due = str(out.get("due_date") or "").strip()
    if due:
        spoken_due = spoken_date(due) if len(due) >= 10 else due
        out.setdefault("fecha_vencimiento", spoken_due)
        out.setdefault("due_date_spoken", spoken_due)
        if "delinquency" not in out and "TEST_DELINQUENCY" not in os.environ:
            out["delinquency"] = str(_delinquency_days(due))
    mora = str(out.get("delinquency") or "").strip()
    if mora:
        out.setdefault("dias_mora", mora)
        out.setdefault("cuotas_en_mora_texto", f"{mora} días")
    total = _as_meta_float(out.get("total_balance") or out.get("amount"))
    min_pct = _as_meta_float(out.get("min_pago_pct"))
    disc_pct = _as_meta_float(out.get("max_discount_pct"))
    if total is not None and not out.get("monto_minimo"):
        if min_pct is not None:
            out["monto_minimo"] = str(int(round(total * min_pct / 100)))
        elif disc_pct is not None:
            out["monto_minimo"] = str(int(round(total * (100 - disc_pct) / 100)))
    if out.get("monto_minimo"):
        out.setdefault("monto_minimo_palabras", _spoken_money(out["monto_minimo"]))
    if disc_pct is not None:
        out.setdefault("max_discount_pct_palabras", amount_to_words(disc_pct))
    if not out.get("payment_amount"):
        out["payment_amount"] = out.get("total_balance") or out.get("amount") or ""
    if out.get("payment_amount"):
        out.setdefault("payment_amount_palabras", _spoken_money(out["payment_amount"]))
    producto = str(out.get("producto") or "").strip()
    if producto:
        out.setdefault("especialidad", producto)
    for src, dest in _MONEY_TO_WORDS:
        if out.get(dest):
            continue
        raw = out.get(src)
        if raw in (None, ""):
            continue
        out[dest] = _spoken_money(raw)
    return out


def _load_json_base() -> dict[str, Any]:
    raw = (os.getenv("BITBIT_METADATA_JSON") or "").strip()
    if raw:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    path_raw = (os.getenv("BITBIT_METADATA_FILE") or "presets/demo_call.json").strip()
    path = Path(path_raw)
    if not path.is_absolute():
        path = ROOT / path
    if path.exists():
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    return {}


def redis_key(call_id: Optional[str] = None) -> str:
    env = (os.getenv("ENV") or "dev").lower()
    prefix = os.getenv("TEST_REDIS_KEY_PREFIX") or os.getenv("REDIS_KEY_PREFIX") or f"{env}:calls"
    cid = call_id or os.getenv("TEST_CALL_ID") or os.getenv("CALL_ID") or "1"
    return f"{prefix}:{cid}"


def _redis_client():
    url = os.getenv("CLIENT_REDIS_URL") or os.getenv("TEST_REDIS_URL")
    host = os.getenv("CLIENT_REDIS_HOST") or os.getenv("TEST_REDIS_HOST")
    if not url and not host:
        return None
    try:
        import redis as redis_lib
    except ImportError:
        logger.warning("Paquete redis ausente; pip install 'bitbit-agent[redis]'")
        return None
    if url:
        return redis_lib.from_url(url, decode_responses=True)
    port = int(os.getenv("CLIENT_REDIS_PORT") or os.getenv("TEST_REDIS_PORT") or "6379")
    db = int(os.getenv("CLIENT_REDIS_DB") or os.getenv("TEST_REDIS_DB") or "0")
    password = os.getenv("CLIENT_REDIS_PASSWORD") or os.getenv("TEST_REDIS_PASSWORD")
    return redis_lib.Redis(
        host=host or "localhost",
        port=port,
        db=db,
        password=password,
        decode_responses=True,
    )


def load_payload_from_redis(call_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    client = _redis_client()
    if client is None:
        return None
    key = redis_key(call_id)
    try:
        raw = client.hget(key, "body")
    except Exception:
        logger.exception("Redis hget falló key={}", key)
        return None
    if not raw:
        logger.warning("Redis sin body key={}", key)
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("Redis body no es JSON key={}", key)
        return None
    return parsed if isinstance(parsed, dict) else None


def seed_redis_body(call_id: Optional[str] = None) -> str:
    client = _redis_client()
    if client is None:
        raise RuntimeError("Redis no configurado (TEST_REDIS_URL / TEST_REDIS_HOST)")
    payload = apply_derived_fields(apply_test_env_overrides(build_payload_from_env(call_id)))
    key = redis_key(call_id)
    client.hset(key, "body", json.dumps(payload, ensure_ascii=False))
    return key


def load_call_metadata() -> dict[str, Any]:
    """Carga metadata de prueba: json (default), env o redis; siempre aplica TEST_*."""
    source = (os.getenv("TEST_METADATA_SOURCE") or "json").strip().lower()
    data: dict[str, Any] = {}
    if source == "env":
        data = build_payload_from_env()
    elif source == "redis":
        data = load_payload_from_redis() or {}
        if not data:
            logger.warning("TEST_METADATA_SOURCE=redis sin body; fallback a JSON/env")
            data = _load_json_base() or build_payload_from_env()
    else:
        data = _load_json_base()
    data = apply_test_env_overrides(data)
    data = apply_derived_fields(data)
    logger.info(
        "call metadata source={} flow_key={} name={} company={} delinquency={} total_balance={}",
        source,
        data.get("flow_key"),
        data.get("name"),
        data.get("company_name"),
        data.get("delinquency"),
        data.get("total_balance"),
    )
    return data
