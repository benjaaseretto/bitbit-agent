"""Fechas habladas / relativas (ES) para tools de agenda."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from num2words import num2words


def today_in_tz(tz_name: str) -> date:
    try:
        return datetime.now(ZoneInfo(tz_name)).date()
    except Exception:
        return datetime.now(ZoneInfo("UTC")).date()


def parse_iso_date(value: str) -> Optional[date]:
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except Exception:
        return None


def spoken_date(iso: str) -> str:
    d = parse_iso_date(iso)
    if d is None:
        return iso
    months = (
        "enero",
        "febrero",
        "marzo",
        "abril",
        "mayo",
        "junio",
        "julio",
        "agosto",
        "septiembre",
        "octubre",
        "noviembre",
        "diciembre",
    )
    return f"{d.day} de {months[d.month - 1]}"


def resolve_relative_fecha(raw: str, *, timezone: str) -> str:
    """Map spoken Spanish relatives to ISO AAAA-MM-DD; pass through ISO/other."""
    s = " ".join(str(raw or "").strip().lower().split())
    if not s:
        return raw
    today = today_in_tz(timezone)
    relatives = {
        "hoy": 0,
        "today": 0,
        "mañana": 1,
        "manana": 1,
        "tomorrow": 1,
        "pasado mañana": 2,
        "pasado manana": 2,
        "mañana mismo": 1,
        "manana mismo": 1,
    }
    if s in relatives:
        return (today + timedelta(days=relatives[s])).isoformat()
    if "pasado mañana" in s or "pasado manana" in s:
        return (today + timedelta(days=2)).isoformat()
    if "mañana" in s or "manana" in s:
        return (today + timedelta(days=1)).isoformat()
    if s == "hoy" or s.startswith("hoy "):
        return today.isoformat()
    iso = parse_iso_date(raw)
    return iso.isoformat() if iso else raw


def validate_commitment_date(
    raw: str, *, timezone: str, max_dias: int
) -> tuple[bool, Optional[str], str]:
    resolved = resolve_relative_fecha(raw, timezone=timezone)
    target = parse_iso_date(resolved)
    human = raw
    if target is None:
        return False, None, human
    start = today_in_tz(timezone)
    end = start + timedelta(days=max(0, int(max_dias)))
    human = target.strftime("%d/%m/%Y")
    if start <= target <= end:
        return True, target.isoformat(), human
    return False, None, human


def amount_to_words(amount: float, lang: str = "es") -> str:
    try:
        whole = int(round(float(amount)))
        return num2words(whole, lang=lang)
    except Exception:
        return str(amount)
