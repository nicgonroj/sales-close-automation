"""KPIs del cierre, calculados con SQL sobre el modelo dimensional.

Son las mismas definiciones que se publican en Power BI como medidas DAX (ver README):
- Cumplimiento % = Ventas del período / Meta del período.
- Var % vs mes anterior = (Ventas del período − Ventas del mes anterior) / Ventas del mes anterior.
- Mix % = Ventas del producto / Ventas totales del alcance (período y, si aplica, segmento).
"""

from __future__ import annotations

import sqlite3

from .calendario import periodo_anterior


def _razon(numerador: float, denominador: float) -> float | None:
    """División segura: sin denominador no hay indicador (no se informa 0 % ni infinito)."""
    return numerador / denominador if denominador else None


def _var(actual: float, anterior: float | None) -> float | None:
    return _razon(actual - anterior, anterior) if anterior else None


def resumen_periodo(conn: sqlite3.Connection, periodo: str, id_segmento: str | None = None) -> dict:
    """Totales del período (opcionalmente de un segmento) y su variación vs el mes anterior."""

    def totales(p: str) -> sqlite3.Row:
        sql = """SELECT COUNT(*) AS operaciones, COALESCE(SUM(f.monto_clp), 0) AS monto,
                        COALESCE(SUM(f.comision_clp), 0) AS comision
                 FROM fact_ventas f JOIN dim_segmento s ON s.segmento_key = f.segmento_key
                 WHERE f.periodo = ? AND (? IS NULL OR s.id_segmento = ?)"""
        return conn.execute(sql, (p, id_segmento, id_segmento)).fetchone()

    act, ant = totales(periodo), totales(periodo_anterior(periodo))
    return {
        "periodo": periodo,
        "operaciones": act["operaciones"],
        "monto_clp": act["monto"],
        "comision_clp": act["comision"],
        "ticket_medio_clp": _razon(act["monto"], act["operaciones"]),
        "monto_mes_anterior_clp": ant["monto"] or None,
        "var_vs_mes_anterior": _var(act["monto"], ant["monto"]),
    }


def cumplimiento_ejecutivos(conn: sqlite3.Connection, periodo: str) -> list[dict]:
    """Ventas vs meta por ejecutivo (todos los que tienen meta, aunque no hayan vendido)."""
    sql = """
        SELECT e.id_ejecutivo, e.nombre, s.nombre AS sucursal,
               COALESCE(v.monto, 0) AS monto_clp, m.meta_clp
        FROM fact_meta_ejecutivo m
        JOIN dim_ejecutivo e ON e.ejecutivo_key = m.ejecutivo_key
        JOIN dim_sucursal  s ON s.sucursal_key  = e.sucursal_key
        LEFT JOIN (SELECT ejecutivo_key, SUM(monto_clp) AS monto
                   FROM fact_ventas WHERE periodo = ? GROUP BY ejecutivo_key) v
               ON v.ejecutivo_key = m.ejecutivo_key
        WHERE m.periodo = ?"""
    filas = [dict(r) | {"cumplimiento": _razon(r["monto_clp"], r["meta_clp"])}
             for r in conn.execute(sql, (periodo, periodo))]
    return sorted(filas, key=lambda f: (-(f["cumplimiento"] or 0), f["id_ejecutivo"]))


def cumplimiento_sucursales(conn: sqlite3.Connection, periodo: str) -> list[dict]:
    """La meta de la sucursal es la suma de las metas de su dotación."""
    acumulado: dict[str, dict] = {}
    for f in cumplimiento_ejecutivos(conn, periodo):
        s = acumulado.setdefault(f["sucursal"], {"sucursal": f["sucursal"], "monto_clp": 0, "meta_clp": 0})
        s["monto_clp"] += f["monto_clp"]
        s["meta_clp"] += f["meta_clp"]
    filas = [s | {"cumplimiento": _razon(s["monto_clp"], s["meta_clp"])} for s in acumulado.values()]
    return sorted(filas, key=lambda f: (-(f["cumplimiento"] or 0), f["sucursal"]))


def mix_productos(conn: sqlite3.Connection, periodo: str, id_segmento: str | None = None) -> list[dict]:
    sql = """
        SELECT p.id_producto, p.nombre AS producto, p.familia,
               COUNT(*) AS operaciones, SUM(f.monto_clp) AS monto_clp
        FROM fact_ventas f
        JOIN dim_producto p ON p.producto_key = f.producto_key
        JOIN dim_segmento s ON s.segmento_key = f.segmento_key
        WHERE f.periodo = ? AND (? IS NULL OR s.id_segmento = ?)
        GROUP BY p.id_producto, p.nombre, p.familia
        ORDER BY monto_clp DESC"""
    filas = [dict(r) for r in conn.execute(sql, (periodo, id_segmento, id_segmento))]
    total = sum(f["monto_clp"] for f in filas)
    return [f | {"participacion": _razon(f["monto_clp"], total)} for f in filas]


# Dimensiones por las que se puede abrir la variación vs mes anterior.
_DIMENSIONES = {
    "segmento": ("dim_segmento", "segmento_key", "nombre"),
    "sucursal": ("dim_sucursal", "sucursal_key", "nombre"),
    "producto": ("dim_producto", "producto_key", "nombre"),
}


def variacion_vs_anterior(conn: sqlite3.Connection, periodo: str, dimension: str,
                          id_segmento: str | None = None) -> list[dict]:
    """Ventas del período y del mes anterior abiertas por `dimension`, con su variación %."""
    tabla, clave, etiqueta = _DIMENSIONES[dimension]
    sql = f"""
        SELECT d.{etiqueta} AS nombre,
               SUM(CASE WHEN f.periodo = :act THEN f.monto_clp ELSE 0 END) AS monto_clp,
               SUM(CASE WHEN f.periodo = :ant THEN f.monto_clp ELSE 0 END) AS monto_anterior_clp
        FROM fact_ventas f
        JOIN {tabla} d ON d.{clave} = f.{clave}
        JOIN dim_segmento s ON s.segmento_key = f.segmento_key
        WHERE f.periodo IN (:act, :ant) AND (:seg IS NULL OR s.id_segmento = :seg)
        GROUP BY d.{etiqueta}
        ORDER BY monto_clp DESC"""
    params = {"act": periodo, "ant": periodo_anterior(periodo), "seg": id_segmento}
    return [dict(r) | {"var_vs_mes_anterior": _var(r["monto_clp"], r["monto_anterior_clp"])}
            for r in conn.execute(sql, params)]


def ranking_ejecutivos_segmento(conn: sqlite3.Connection, periodo: str, id_segmento: str,
                                limite: int = 10) -> list[dict]:
    sql = """
        SELECT e.id_ejecutivo, e.nombre, su.nombre AS sucursal,
               COUNT(*) AS operaciones, SUM(f.monto_clp) AS monto_clp
        FROM fact_ventas f
        JOIN dim_ejecutivo e  ON e.ejecutivo_key  = f.ejecutivo_key
        JOIN dim_sucursal  su ON su.sucursal_key  = e.sucursal_key
        JOIN dim_segmento  s  ON s.segmento_key   = f.segmento_key
        WHERE f.periodo = ? AND s.id_segmento = ?
        GROUP BY e.id_ejecutivo, e.nombre, su.nombre
        ORDER BY monto_clp DESC, e.id_ejecutivo
        LIMIT ?"""
    return [dict(r) for r in conn.execute(sql, (periodo, id_segmento, limite))]


def segmentos(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT id_segmento, nombre, lista_distribucion FROM dim_segmento ORDER BY id_segmento")]


def detalle_segmento(conn: sqlite3.Connection, periodo: str, id_segmento: str) -> list[dict]:
    """Tabla plana sucursal × producto del segmento: es el CSV que acompaña al reporte."""
    sql = """
        SELECT su.nombre AS sucursal, p.nombre AS producto, p.familia,
               SUM(CASE WHEN f.periodo = :act THEN 1 ELSE 0 END)           AS operaciones,
               SUM(CASE WHEN f.periodo = :act THEN f.monto_clp ELSE 0 END) AS monto_clp,
               SUM(CASE WHEN f.periodo = :act THEN f.comision_clp ELSE 0 END) AS comision_clp,
               SUM(CASE WHEN f.periodo = :ant THEN f.monto_clp ELSE 0 END) AS monto_anterior_clp
        FROM fact_ventas f
        JOIN dim_sucursal su ON su.sucursal_key = f.sucursal_key
        JOIN dim_producto p  ON p.producto_key  = f.producto_key
        JOIN dim_segmento s  ON s.segmento_key  = f.segmento_key
        WHERE f.periodo IN (:act, :ant) AND s.id_segmento = :seg
        GROUP BY su.nombre, p.nombre, p.familia
        ORDER BY su.nombre, monto_clp DESC"""
    params = {"act": periodo, "ant": periodo_anterior(periodo), "seg": id_segmento}
    return [dict(r) | {"var_vs_mes_anterior": _var(r["monto_clp"], r["monto_anterior_clp"])}
            for r in conn.execute(sql, params)]


def rechazos_por_regla(conn: sqlite3.Connection, periodo: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        """SELECT regla, COUNT(*) AS rechazos FROM etl_rechazos
           WHERE periodo = ? GROUP BY regla ORDER BY regla""", (periodo,))]
