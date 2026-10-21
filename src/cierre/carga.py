"""Carga al modelo dimensional en SQLite.

Idempotencia:
- Las dimensiones se cargan con UPSERT por clave natural: la clave sustituta no cambia
  entre corridas, así los hechos ya cargados siguen apuntando a la fila correcta.
- Los hechos, las metas y los rechazos de un período se reemplazan completos dentro de
  una sola transacción (borrar período + insertar). Correr el cierre dos veces deja la
  base igual que correrlo una vez; si algo falla a mitad, no queda una carga parcial.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from .calendario import dias_del_periodo, es_habil
from .extraccion import Extraccion
from .validacion import ResultadoValidacion

DDL_POR_DEFECTO = Path(__file__).resolve().parents[2] / "sql" / "ddl_modelo_dimensional.sql"


def conectar(ruta_db: Path | str, ddl: Path = DDL_POR_DEFECTO) -> sqlite3.Connection:
    if str(ruta_db) != ":memory:":
        Path(ruta_db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta_db)
    conn.row_factory = sqlite3.Row
    conn.executescript(Path(ddl).read_text(encoding="utf-8"))
    return conn


def _tarifa(valor: str) -> float | None:
    try:
        return float(valor) if valor else None
    except ValueError:
        return None


def cargar_dimensiones(conn: sqlite3.Connection, maestros: dict[str, list[dict]], periodos: list[str]) -> None:
    """UPSERT de dimensiones por clave natural (SCD tipo 1: se sobrescriben atributos)."""
    filas_fecha = []
    for periodo in periodos:
        for d in dias_del_periodo(periodo):
            filas_fecha.append((int(d.strftime("%Y%m%d")), d.isoformat(), d.year, d.month, d.day,
                                periodo, d.isoweekday(), int(es_habil(d))))
    conn.executemany(
        """INSERT INTO dim_fecha VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT (fecha_key) DO UPDATE SET es_habil = excluded.es_habil""", filas_fecha)
    conn.executemany(
        """INSERT INTO dim_sucursal (id_sucursal, nombre, region) VALUES (?, ?, ?)
           ON CONFLICT (id_sucursal) DO UPDATE SET nombre = excluded.nombre, region = excluded.region""",
        [(f["id_sucursal"], f["nombre"], f["region"]) for f in maestros["sucursales"]])
    conn.executemany(
        """INSERT INTO dim_ejecutivo (id_ejecutivo, nombre, id_sucursal, sucursal_key)
           VALUES (?, ?, ?, (SELECT sucursal_key FROM dim_sucursal WHERE id_sucursal = ?))
           ON CONFLICT (id_ejecutivo) DO UPDATE SET nombre = excluded.nombre,
               id_sucursal = excluded.id_sucursal, sucursal_key = excluded.sucursal_key""",
        [(f["id_ejecutivo"], f["nombre"], f["id_sucursal"], f["id_sucursal"]) for f in maestros["ejecutivos"]])
    conn.executemany(
        """INSERT INTO dim_producto (id_producto, nombre, familia, tarifa_comision) VALUES (?, ?, ?, ?)
           ON CONFLICT (id_producto) DO UPDATE SET nombre = excluded.nombre, familia = excluded.familia,
               tarifa_comision = excluded.tarifa_comision""",
        [(f["id_producto"], f["nombre"], f["familia"], _tarifa(f.get("tarifa_comision", "")))
         for f in maestros["productos"]])
    conn.executemany(
        """INSERT INTO dim_segmento (id_segmento, nombre, lista_distribucion) VALUES (?, ?, ?)
           ON CONFLICT (id_segmento) DO UPDATE SET nombre = excluded.nombre,
               lista_distribucion = excluded.lista_distribucion""",
        [(f["id_segmento"], f["nombre"], f["lista_distribucion"]) for f in maestros["segmentos"]])


def _mapa(conn: sqlite3.Connection, tabla: str, natural: str, sustituta: str) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute(f"SELECT {natural}, {sustituta} FROM {tabla}")}


def cargar_periodo(conn: sqlite3.Connection, ext: Extraccion, res: ResultadoValidacion) -> str:
    """Reemplaza hechos, metas y rechazos del período en una transacción. Devuelve el id de carga."""
    id_carga = f"{ext.periodo}-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    archivo = ext.archivo_ventas.name
    with conn:  # transacción: commit al salir, rollback si hay excepción
        cargar_dimensiones(conn, ext.maestros, [ext.periodo])
        ej = _mapa(conn, "dim_ejecutivo", "id_ejecutivo", "ejecutivo_key")
        suc = _mapa(conn, "dim_sucursal", "id_sucursal", "sucursal_key")
        prod = _mapa(conn, "dim_producto", "id_producto", "producto_key")
        seg = _mapa(conn, "dim_segmento", "id_segmento", "segmento_key")
        tarifas = {r[0]: r[1] for r in conn.execute("SELECT id_producto, tarifa_comision FROM dim_producto")}

        conn.execute("DELETE FROM fact_ventas WHERE periodo = ?", (ext.periodo,))
        conn.execute("DELETE FROM fact_meta_ejecutivo WHERE periodo = ?", (ext.periodo,))
        conn.execute("DELETE FROM etl_rechazos WHERE periodo = ?", (ext.periodo,))

        conn.executemany(
            "INSERT INTO fact_ventas VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(f["id_operacion"], ext.periodo, int(f["fecha_operacion"].replace("-", "")),
              ej[f["id_ejecutivo"]], suc[f["id_sucursal"]], prod[f["id_producto"]], seg[f["id_segmento"]],
              f["canal"], f["monto_clp"], round(f["monto_clp"] * tarifas[f["id_producto"]], 2), id_carga)
             for f in res.validas])
        conn.executemany(
            "INSERT INTO fact_meta_ejecutivo VALUES (?, ?, ?)",
            [(ext.periodo, ej[m["id_ejecutivo"]], int(m["meta_clp"])) for m in ext.metas if m["id_ejecutivo"] in ej])
        conn.executemany(
            "INSERT INTO etl_rechazos VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(ext.periodo, archivo, r.linea, r.id_operacion, r.regla, r.motivo, id_carga) for r in res.rechazos])
        conn.execute(
            "INSERT INTO etl_cargas VALUES (?, ?, ?, ?, ?, ?, ?)",
            (id_carga, ext.periodo, archivo, datetime.now().isoformat(timespec="seconds"),
             res.filas_leidas, len(res.validas), res.filas_rechazadas))
    return id_carga
