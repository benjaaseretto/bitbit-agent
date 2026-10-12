"""Dataset demo determinista para insights (SIN datos reales ni PII).

Los registros son sintéticos, generados con seed fijo y anclados a la fecha
de la llamada, para que los períodos (mes / semana / 3 meses) siempre tengan
datos. En producción este módulo se reemplaza por un adapter del DataSource
que apunte al CRM/DB real (ver docs/INSIGHTS.md).
"""
from __future__ import annotations

import random
from datetime import date, timedelta

_STATUSES = ("al_dia", "atrasado", "en_gestion", "recuperado")

_FIRST = (
    "Ana", "Luis", "María", "Carlos", "Sofía", "Jorge", "Lucía", "Diego",
    "Elena", "Marta", "Pablo", "Rocío", "Iván", "Carmen", "Nuria", "Óscar",
)
_LAST = (
    "Demo", "Prueba", "Ejemplo", "Test", "Muestra", "Sandbox",
)


def build_demo_dataset(today: date, *, seed: int = 20260922) -> dict:
    """Dataset sintético con 120 días de evolución y ~60 deudores demo."""
    rng = random.Random(seed)

    daily: list[dict[str, float | str]] = []
    pending = 4_800_000.0
    for offset in range(120, -1, -1):
        day = today - timedelta(days=offset)
        if day.weekday() >= 5:  # fines de semana sin gestión
            recovered = round(rng.uniform(0, 8_000), 2)
        else:
            base = 55_000 if day.day <= 15 else 38_000
            recovered = round(max(0.0, rng.gauss(base, 14_000)), 2)
        new_debt = round(max(0.0, rng.gauss(46_000, 12_000)), 2)
        pending = round(max(150_000.0, pending - recovered + new_debt), 2)
        daily.append(
            {
                "date": day.isoformat(),
                "recovered_amount": recovered,
                "new_debt_amount": new_debt,
                "pending_balance": pending,
            }
        )

    debtors: list[dict] = []
    for index in range(1, 61):
        status = rng.choices(
            _STATUSES, weights=(0.35, 0.30, 0.25, 0.10), k=1
        )[0]
        debtors.append(
            {
                "id": f"demo-{index:03d}",
                "name": f"{_FIRST[index % len(_FIRST)]} {_LAST[index % len(_LAST)]} {index:03d}",
                "pending_balance": round(rng.uniform(1_200, 240_000), 2),
                "status": status,
                "last_payment": (
                    (today - timedelta(days=rng.randint(0, 90))).isoformat()
                    if status in ("al_dia", "recuperado")
                    else None
                ),
            }
        )

    portfolio_total = round(
        sum(row["pending_balance"] for row in daily[-1:]) + rng.uniform(0, 50_000), 2
    )
    return {
        "meta": {
            "source": "fixture-demo",
            "note": "Datos sintéticos de demostración; sin PII real.",
            "currency": "MXN",
        },
        "daily": daily,
        "debtors": debtors,
        "portfolio": {"total_debt": portfolio_total},
    }