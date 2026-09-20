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


def spoken_greeting(tz_name: str) -> str:
    """Saludo según hora local: Buenos días / Buenas tardes / Buenas noches."""
    try:
        hour = datetime.now(ZoneInfo(tz_name)).hour
    except Exception:
        hour = datetime.now(ZoneInfo("UTC")).hour
    if hour < 12:
        return "Buenos días"
    if hour < 20:
        return "Buenas tardes"
    return "Buenas noches"


def spoken_clock(hhmm: str) -> str:
    """'10:00' → 'las diez de la mañana'."""
    raw = str(hhmm or "").strip()
    if not raw:
        return ""
    parts = raw.replace(".", ":").split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return raw
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return raw
    h12 = hour % 12 or 12
    if hour < 12:
        period = "de la mañana"
    elif hour == 12 and minute == 0:
        period = "del mediodía"
    elif hour < 20:
        period = "de la tarde"
    else:
        period = "de la noche"
    if h12 == 1:
        article = "la"
        hour_words = "una"
    else:
        article = "las"
        hour_words = num2words(h12, lang="es")
    if minute == 0:
        if hour == 12:
            return "las doce del mediodía"
        return f"{article} {hour_words} {period}"
    minute_words = num2words(minute, lang="es")
    return f"{article} {hour_words} y {minute_words} {period}"


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
