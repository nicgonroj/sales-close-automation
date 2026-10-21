"""Utilidades de calendario: períodos AAAA-MM y días hábiles en Chile."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

# Feriados nacionales de referencia para el demo (jul–dic 2026). En producción esta
# lista vendría de una tabla corporativa de calendario, no del código.
FERIADOS = {
    date(2026, 7, 16),
    date(2026, 8, 15),
    date(2026, 9, 18),
    date(2026, 9, 19),
    date(2026, 10, 12),
    date(2026, 10, 31),
    date(2026, 11, 1),
    date(2026, 12, 8),
    date(2026, 12, 25),
}


def validar_periodo(periodo: str) -> tuple[int, int]:
    """Convierte 'AAAA-MM' en (año, mes) o lanza ValueError."""
    try:
        anio, mes = (int(p) for p in periodo.split("-"))
    except ValueError as exc:
        raise ValueError(f"Período inválido: {periodo!r} (se espera AAAA-MM)") from exc
    if not 1 <= mes <= 12 or len(periodo) != 7:
        raise ValueError(f"Período inválido: {periodo!r} (se espera AAAA-MM)")
    return anio, mes


def dias_del_periodo(periodo: str) -> list[date]:
    anio, mes = validar_periodo(periodo)
    ultimo = calendar.monthrange(anio, mes)[1]
    return [date(anio, mes, d) for d in range(1, ultimo + 1)]


def es_habil(dia: date) -> bool:
    return dia.isoweekday() <= 5 and dia not in FERIADOS


def periodo_anterior(periodo: str) -> str:
    anio, mes = validar_periodo(periodo)
    return f"{anio - 1}-12" if mes == 1 else f"{anio}-{mes - 1:02d}"


def primer_dia_habil_siguiente(periodo: str) -> date:
    """Día hábil siguiente al cierre del período: la fecha objetivo de envío."""
    dia = dias_del_periodo(periodo)[-1] + timedelta(days=1)
    while not es_habil(dia):
        dia += timedelta(days=1)
    return dia
