"""Extracción: lectura de los CSV que entregan los sistemas fuente.

No transforma ni descarta nada; solo lee, agrega el número de línea de origen
(útil para el registro de rechazos) y recorta espacios.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Extraccion:
    """Todo lo que necesita un período: operaciones, metas y maestros."""

    periodo: str
    archivo_ventas: Path
    ventas: list[dict]
    metas: list[dict]
    maestros: dict[str, list[dict]] = field(default_factory=dict)


def leer_csv(ruta: Path) -> list[dict]:
    """Lee un CSV con encabezado. Cada fila incluye `_linea` (el encabezado es la línea 1)."""
    with Path(ruta).open(newline="", encoding="utf-8") as f:
        filas = []
        for n, fila in enumerate(csv.DictReader(f), start=2):
            limpia = {k.strip(): (v or "").strip() for k, v in fila.items() if k is not None}
            limpia["_linea"] = n
            filas.append(limpia)
        return filas


def leer_maestros(dir_fuente: Path) -> dict[str, list[dict]]:
    dir_fuente = Path(dir_fuente)
    return {nombre: leer_csv(dir_fuente / f"maestro_{nombre}.csv")
            for nombre in ("sucursales", "ejecutivos", "productos", "segmentos")}


def extraer(dir_fuente: Path, periodo: str) -> Extraccion:
    dir_fuente = Path(dir_fuente)
    archivo = dir_fuente / f"colocaciones_{periodo}.csv"
    if not archivo.exists():
        raise FileNotFoundError(f"No existe el archivo fuente del período: {archivo}")
    return Extraccion(
        periodo=periodo,
        archivo_ventas=archivo,
        ventas=leer_csv(archivo),
        metas=leer_csv(dir_fuente / f"metas_{periodo}.csv"),
        maestros=leer_maestros(dir_fuente),
    )
