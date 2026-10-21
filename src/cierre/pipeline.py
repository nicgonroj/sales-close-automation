"""Orquestación del cierre: extracción → validación → carga → KPIs → reportes → envío simulado."""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import kpis
from .calendario import periodo_anterior
from .carga import conectar
from .carga import cargar_periodo
from .envio import preparar_envios
from .extraccion import extraer
from .reportes import generar_reporte_segmento, generar_resumen
from .validacion import cargar_reglas, validar

RAIZ = Path(__file__).resolve().parents[2]
REGLAS_POR_DEFECTO = RAIZ / "reglas" / "reglas_negocio.json"


def procesar_periodo(conn, dir_fuente: Path, periodo: str, reglas: list[dict]) -> dict:
    """Extrae, valida y carga un período. Devuelve sus métricas de calidad y tiempo."""
    t0 = time.perf_counter()
    ext = extraer(dir_fuente, periodo)
    res = validar(ext.ventas, ext.maestros, reglas, periodo)
    id_carga = cargar_periodo(conn, ext, res)
    en_modelo = conn.execute("SELECT COUNT(*) FROM fact_ventas WHERE periodo = ?", (periodo,)).fetchone()[0]
    return {
        "periodo": periodo,
        "id_carga": id_carga,
        "archivo": ext.archivo_ventas.name,
        "filas_leidas": res.filas_leidas,
        "filas_cargadas": len(res.validas),
        "filas_rechazadas": res.filas_rechazadas,
        "rechazos_por_regla": res.rechazos_por_regla(),
        "filas_en_modelo": en_modelo,
        "segundos": round(time.perf_counter() - t0, 3),
    }


def ejecutar(periodo: str, dir_fuente: Path, ruta_db: Path, dir_salida: Path,
             ruta_reglas: Path = REGLAS_POR_DEFECTO, dry_run: bool = True,
             incluir_anterior: bool = True) -> dict:
    """Corre el cierre completo de `periodo` y devuelve las métricas medidas.

    Si existe el archivo del mes anterior, también se (re)carga: la variación vs mes
    anterior necesita ambos meses en el modelo, y gracias a la idempotencia recargarlo
    no duplica nada.
    """
    inicio = time.perf_counter()
    dir_fuente, dir_salida = Path(dir_fuente), Path(dir_salida)
    reglas = cargar_reglas(ruta_reglas)
    conn = conectar(ruta_db)
    try:
        anterior = periodo_anterior(periodo)
        periodos = [periodo]
        if incluir_anterior and (dir_fuente / f"colocaciones_{anterior}.csv").exists():
            periodos.insert(0, anterior)
        cargas = [procesar_periodo(conn, dir_fuente, p, reglas) for p in periodos]
        actual = cargas[-1]

        t_rep = time.perf_counter()
        dir_segmentos = dir_salida / "por_segmento"
        reportes = [generar_reporte_segmento(conn, periodo, s, dir_segmentos) for s in kpis.segmentos(conn)]
        resumen = generar_resumen(conn, periodo, dir_salida, actual)
        manifiesto = preparar_envios(reportes, periodo, dir_segmentos, dry_run=dry_run)
        seg_reportes = round(time.perf_counter() - t_rep, 3)
    finally:
        conn.close()

    metricas = {
        "periodo": periodo,
        "cargas": cargas,
        "reportes_por_segmento": len(reportes),
        # HTML + CSV por segmento, resumen HTML + CSV de cumplimiento, manifiesto y, sin dry-run, los .eml.
        "archivos_generados": 2 * len(reportes) + 3 + (0 if dry_run else len(manifiesto["envios"])),
        "resumen": resumen.name,
        "dry_run": dry_run,
        "fecha_programada_envio": manifiesto["fecha_programada"],
        "segundos_reportes_y_envio": seg_reportes,
        "segundos_total": round(time.perf_counter() - inicio, 3),
    }
    (dir_salida / f"metricas_{periodo}.json").write_text(json.dumps(metricas, ensure_ascii=False, indent=2),
                                                         encoding="utf-8")
    return metricas
