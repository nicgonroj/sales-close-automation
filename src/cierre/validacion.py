"""Validación de operaciones contra las reglas de negocio declaradas en JSON.

Las reglas viven en `reglas/reglas_negocio.json` (no en el código): el área comercial
puede revisarlas y cambiar parámetros sin tocar Python. Este módulo solo sabe evaluar
*tipos* de regla; agregar una regla nueva de un tipo existente es editar el JSON.

Criterios:
- Cada regla se evalúa por separado y se registran **todos** los motivos de una fila.
- Las reglas que miran un campo no opinan si el campo viene vacío: eso es trabajo de
  la regla de obligatoriedad, así un mismo defecto no se cuenta dos veces.
- Una fila con al menos un motivo no entra al modelo; queda en el registro de rechazos.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from .calendario import validar_periodo


@dataclass
class Rechazo:
    linea: int
    id_operacion: str
    regla: str
    motivo: str


@dataclass
class ResultadoValidacion:
    validas: list[dict]
    rechazos: list[Rechazo]
    filas_leidas: int

    @property
    def filas_rechazadas(self) -> int:
        return len({r.linea for r in self.rechazos})

    def rechazos_por_regla(self) -> dict[str, int]:
        conteo: dict[str, int] = {}
        for r in self.rechazos:
            conteo[r.regla] = conteo.get(r.regla, 0) + 1
        return dict(sorted(conteo.items()))


def cargar_reglas(ruta: Path) -> list[dict]:
    datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    reglas = datos["reglas"]
    for regla in reglas:
        if regla["tipo"] not in EVALUADORES:
            raise ValueError(f"Tipo de regla desconocido en {regla['id']}: {regla['tipo']}")
    return reglas


# ───────────── Contexto de evaluación ─────────────

class Contexto:
    """Datos de referencia que necesitan las reglas: período, maestros y estado (duplicados)."""

    def __init__(self, periodo: str, maestros: dict[str, list[dict]]):
        anio, mes = validar_periodo(periodo)
        self.anio, self.mes = anio, mes
        self.claves = {
            "ejecutivos": {f["id_ejecutivo"] for f in maestros["ejecutivos"]},
            "sucursales": {f["id_sucursal"] for f in maestros["sucursales"]},
            "segmentos": {f["id_segmento"] for f in maestros["segmentos"]},
        }
        self.tarifas = {f["id_producto"]: f.get("tarifa_comision", "") for f in maestros["productos"]}
        self.vistos: dict[tuple[str, str], int] = {}  # (regla, valor) → línea de la primera aparición


# ───────────── Evaluadores por tipo de regla ─────────────
# Firma común: (fila, regla, contexto) → motivo (str) si incumple, o None si cumple.

def _obligatorio(fila: dict, regla: dict, ctx: Contexto) -> str | None:
    faltan = [c for c in regla["campos"] if not fila.get(c)]
    return f"campos vacíos: {', '.join(faltan)}" if faltan else None


def _unico(fila: dict, regla: dict, ctx: Contexto) -> str | None:
    valor = fila.get(regla["campo"])
    if not valor:
        return None
    clave = (regla["id"], valor)
    if clave in ctx.vistos:
        return f"{regla['campo']} {valor} repetido (primera aparición en línea {ctx.vistos[clave]})"
    ctx.vistos[clave] = fila["_linea"]
    return None


def _monto_positivo(fila: dict, regla: dict, ctx: Contexto) -> str | None:
    valor = fila.get(regla["campo"])
    if not valor:
        return None
    try:
        monto = int(valor)
    except ValueError:
        return f"monto no numérico: {valor!r}"
    return None if monto > 0 else f"monto no positivo: {monto}"


def _fecha_en_periodo(fila: dict, regla: dict, ctx: Contexto) -> str | None:
    valor = fila.get(regla["campo"])
    if not valor:
        return None
    try:
        fecha = date.fromisoformat(valor)
    except ValueError:
        return f"fecha inválida: {valor!r}"
    if (fecha.year, fecha.month) != (ctx.anio, ctx.mes):
        return f"fecha {valor} fuera del período {ctx.anio}-{ctx.mes:02d}"
    return None


def _existe_en_maestro(fila: dict, regla: dict, ctx: Contexto) -> str | None:
    valor = fila.get(regla["campo"])
    if not valor:
        return None
    return None if valor in ctx.claves[regla["maestro"]] else f"{valor} no existe en maestro de {regla['maestro']}"


def _producto_con_tarifa(fila: dict, regla: dict, ctx: Contexto) -> str | None:
    valor = fila.get(regla["campo"])
    if not valor:
        return None
    if valor not in ctx.tarifas:
        return f"producto {valor} no existe en el tarifario"
    tarifa = ctx.tarifas[valor]
    try:
        if float(tarifa) > 0:
            return None
    except ValueError:
        pass
    return f"producto {valor} sin tarifa de comisión vigente"


def _dominio(fila: dict, regla: dict, ctx: Contexto) -> str | None:
    valor = fila.get(regla["campo"])
    if not valor:
        return None
    return None if valor in regla["valores"] else f"{regla['campo']} fuera de dominio: {valor!r}"


EVALUADORES: dict[str, Callable[[dict, dict, Contexto], str | None]] = {
    "obligatorio": _obligatorio,
    "unico": _unico,
    "monto_positivo": _monto_positivo,
    "fecha_en_periodo": _fecha_en_periodo,
    "existe_en_maestro": _existe_en_maestro,
    "producto_con_tarifa": _producto_con_tarifa,
    "dominio": _dominio,
}


def validar(ventas: list[dict], maestros: dict[str, list[dict]], reglas: list[dict],
            periodo: str) -> ResultadoValidacion:
    """Aplica todas las reglas a cada fila y separa válidas de rechazadas."""
    ctx = Contexto(periodo, maestros)
    validas, rechazos = [], []
    for fila in ventas:
        motivos = []
        for regla in reglas:
            motivo = EVALUADORES[regla["tipo"]](fila, regla, ctx)
            if motivo:
                motivos.append(Rechazo(fila["_linea"], fila.get("id_operacion", ""), regla["id"], motivo))
        if motivos:
            rechazos.extend(motivos)
        else:
            validas.append({**fila, "monto_clp": int(fila["monto_clp"])})
    return ResultadoValidacion(validas=validas, rechazos=rechazos, filas_leidas=len(ventas))
