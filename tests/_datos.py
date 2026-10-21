"""Datos mínimos para los tests: un caso pequeño que se puede calcular a mano."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ / "src") not in sys.path:
    sys.path.insert(0, str(RAIZ / "src"))

COLUMNAS = ["id_operacion", "fecha_operacion", "id_ejecutivo", "id_sucursal", "id_producto",
            "id_segmento", "id_cliente", "canal", "monto_clp"]

MAESTROS = {
    "sucursales": [{"id_sucursal": "S1", "nombre": "Norte", "region": "R1"},
                   {"id_sucursal": "S2", "nombre": "Sur", "region": "R2"}],
    "ejecutivos": [{"id_ejecutivo": "E1", "nombre": "Ejecutivo 1", "id_sucursal": "S1"},
                   {"id_ejecutivo": "E2", "nombre": "Ejecutivo 2", "id_sucursal": "S1"},
                   {"id_ejecutivo": "E3", "nombre": "Ejecutivo 3", "id_sucursal": "S2"}],
    "productos": [{"id_producto": "P1", "nombre": "Crédito", "familia": "Créditos", "tarifa_comision": "0.01"},
                  {"id_producto": "P2", "nombre": "Seguro", "familia": "Seguros", "tarifa_comision": "0.10"},
                  {"id_producto": "P3", "nombre": "Leasing", "familia": "Créditos", "tarifa_comision": ""}],
    "segmentos": [{"id_segmento": "G1", "nombre": "Personas", "lista_distribucion": "personas@empresa.example"},
                  {"id_segmento": "G2", "nombre": "Pyme", "lista_distribucion": "pyme@empresa.example"}],
}


def op(id_op, fecha, ej, suc, prod, seg, monto, canal="Sucursal"):
    return {"id_operacion": id_op, "fecha_operacion": fecha, "id_ejecutivo": ej, "id_sucursal": suc,
            "id_producto": prod, "id_segmento": seg, "id_cliente": "CLI-1", "canal": canal,
            "monto_clp": str(monto)}


# Agosto (mes anterior): total 2.000 → Personas 500, Pyme 1.500.
VENTAS_AGOSTO = [
    op("A1", "2026-08-10", "E1", "S1", "P1", "G1", 500),
    op("A2", "2026-08-11", "E3", "S2", "P2", "G2", 1500),
]
# Septiembre: 4 válidas (total 3.800) + 1 rechazada por monto negativo.
VENTAS_SEPTIEMBRE = [
    op("B1", "2026-09-01", "E1", "S1", "P1", "G1", 600),
    op("B2", "2026-09-02", "E1", "S1", "P2", "G1", 300),
    op("B3", "2026-09-03", "E2", "S1", "P1", "G2", 2500),
    op("B4", "2026-09-04", "E3", "S2", "P2", "G2", 400),
    op("B5", "2026-09-07", "E3", "S2", "P1", "G1", -100),
]
METAS = {"2026-08": {"E1": 800, "E2": 1000, "E3": 1000},
         "2026-09": {"E1": 1000, "E2": 2000, "E3": 1000}}


def _escribir(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def escribir_fuente(destino: Path) -> Path:
    """Escribe los CSV del caso pequeño con el mismo formato que los sistemas fuente."""
    destino.mkdir(parents=True, exist_ok=True)
    for nombre, filas in MAESTROS.items():
        _escribir(destino / f"maestro_{nombre}.csv", list(filas[0].keys()), filas)
    _escribir(destino / "colocaciones_2026-08.csv", COLUMNAS, VENTAS_AGOSTO)
    _escribir(destino / "colocaciones_2026-09.csv", COLUMNAS, VENTAS_SEPTIEMBRE)
    for periodo, metas in METAS.items():
        _escribir(destino / f"metas_{periodo}.csv", ["id_ejecutivo", "meta_clp"],
                  [{"id_ejecutivo": k, "meta_clp": v} for k, v in metas.items()])
    return destino
