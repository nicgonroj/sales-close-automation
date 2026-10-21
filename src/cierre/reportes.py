"""Reportes del cierre: uno por segmento (HTML + CSV) y un resumen ejecutivo general.

El HTML es autocontenido (estilos en línea, sin JavaScript ni recursos externos) para que
se pueda adjuntar o pegar como cuerpo de un correo sin que se rompa.
"""

from __future__ import annotations

import csv
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from html import escape
from pathlib import Path

from . import kpis
from .calendario import periodo_anterior

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]


@dataclass
class Reporte:
    id_segmento: str
    segmento: str
    destinatarios: str
    html: Path
    csv: Path


# ───────────── Formato chileno ─────────────

def clp(valor: float | None) -> str:
    return "—" if valor is None else "$" + f"{round(valor):,}".replace(",", ".")


def entero(valor: int | None) -> str:
    return "—" if valor is None else f"{valor:,}".replace(",", ".")


def pct(valor: float | None, signo: bool = False) -> str:
    if valor is None:
        return "—"
    texto = f"{valor * 100:+.1f}" if signo else f"{valor * 100:.1f}"
    return texto.replace(".", ",") + " %"


def nombre_periodo(periodo: str) -> str:
    anio, mes = periodo.split("-")
    return f"{MESES[int(mes) - 1]} {anio}"


def slug(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", base.lower()).strip("-")


# ───────────── Piezas HTML ─────────────

ESTILO = """
body{font-family:Segoe UI,Helvetica,Arial,sans-serif;color:#1f2933;max-width:960px;margin:24px auto;padding:0 16px}
h1{font-size:22px;margin:0 0 4px} h2{font-size:16px;margin:28px 0 8px;border-bottom:2px solid #e4e7eb;padding-bottom:4px}
.sub{color:#616e7c;margin:0 0 20px} .kpis{display:flex;flex-wrap:wrap;gap:12px}
.kpi{border:1px solid #e4e7eb;border-radius:6px;padding:10px 14px;min-width:150px}
.kpi b{display:block;font-size:18px} .kpi span{color:#616e7c;font-size:12px}
table{border-collapse:collapse;width:100%;font-size:13px} th,td{padding:6px 8px;border-bottom:1px solid #e4e7eb}
th{text-align:left;background:#f5f7fa} td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.pos{color:#1b7f3b} .neg{color:#b42318} .pie{color:#9aa5b1;font-size:12px;margin-top:28px}
"""


def _clase(valor: float | None, umbral: float = 0.0) -> str:
    if valor is None:
        return ""
    return "pos" if valor >= umbral else "neg"


def _tabla(columnas: list[tuple[str, bool]], filas: list[list[str]], clases: list[list[str]] | None = None) -> str:
    """columnas: (título, es_numérica). Las celdas ya vienen formateadas como texto."""
    cab = "".join(f'<th class="n">{escape(t)}</th>' if n else f"<th>{escape(t)}</th>" for t, n in columnas)
    cuerpo = []
    for i, fila in enumerate(filas):
        celdas = []
        for j, (valor, (_, num)) in enumerate(zip(fila, columnas)):
            clase = " ".join(c for c in ("n" if num else "", clases[i][j] if clases else "") if c)
            celdas.append(f'<td class="{clase}">{escape(valor)}</td>' if clase else f"<td>{escape(valor)}</td>")
        cuerpo.append("<tr>" + "".join(celdas) + "</tr>")
    return f"<table><thead><tr>{cab}</tr></thead><tbody>{''.join(cuerpo)}</tbody></table>"


def _kpis_html(res: dict) -> str:
    tarjetas = [
        ("Monto colocado", clp(res["monto_clp"])),
        ("Operaciones", entero(res["operaciones"])),
        ("Ticket medio", clp(res["ticket_medio_clp"])),
        ("Comisión", clp(res["comision_clp"])),
        ("Var. vs mes anterior", pct(res["var_vs_mes_anterior"], signo=True)),
    ]
    return '<div class="kpis">' + "".join(
        f'<div class="kpi"><span>{escape(t)}</span><b>{escape(v)}</b></div>' for t, v in tarjetas) + "</div>"


def _documento(titulo: str, subtitulo: str, cuerpo: str) -> str:
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape(titulo)}</title><style>{ESTILO}</style></head><body>"
            f"<h1>{escape(titulo)}</h1><p class=\"sub\">{escape(subtitulo)}</p>{cuerpo}"
            f'<p class="pie">Generado automáticamente por el proceso de cierre comercial. '
            f"Datos sintéticos de demostración.</p></body></html>")


# ───────────── Reporte por segmento ─────────────

def generar_reporte_segmento(conn: sqlite3.Connection, periodo: str, segmento: dict, destino: Path) -> Reporte:
    seg_id, seg_nombre = segmento["id_segmento"], segmento["nombre"]
    carpeta = Path(destino) / slug(seg_nombre)
    carpeta.mkdir(parents=True, exist_ok=True)
    base = f"cierre_{periodo}_{slug(seg_nombre)}"

    res = kpis.resumen_periodo(conn, periodo, seg_id)
    suc = kpis.variacion_vs_anterior(conn, periodo, "sucursal", seg_id)
    mix = kpis.mix_productos(conn, periodo, seg_id)
    top = kpis.ranking_ejecutivos_segmento(conn, periodo, seg_id)
    ant = nombre_periodo(periodo_anterior(periodo))

    cuerpo = _kpis_html(res)
    cuerpo += "<h2>Monto por sucursal</h2>" + _tabla(
        [("Sucursal", False), ("Monto", True), (f"Monto {ant}", True), ("Var. %", True)],
        [[s["nombre"], clp(s["monto_clp"]), clp(s["monto_anterior_clp"] or None), pct(s["var_vs_mes_anterior"], True)]
         for s in suc],
        [["", "", "", _clase(s["var_vs_mes_anterior"])] for s in suc])
    cuerpo += "<h2>Mix de productos</h2>" + _tabla(
        [("Producto", False), ("Familia", False), ("Operaciones", True), ("Monto", True), ("Mix %", True)],
        [[m["producto"], m["familia"], entero(m["operaciones"]), clp(m["monto_clp"]), pct(m["participacion"])]
         for m in mix])
    cuerpo += "<h2>Ejecutivos con mayor colocación en el segmento</h2>" + _tabla(
        [("#", True), ("Ejecutivo", False), ("Sucursal", False), ("Operaciones", True), ("Monto", True)],
        [[str(i), t["nombre"], t["sucursal"], entero(t["operaciones"]), clp(t["monto_clp"])]
         for i, t in enumerate(top, start=1)])

    ruta_html = carpeta / f"{base}.html"
    ruta_html.write_text(_documento(f"Cierre comercial {nombre_periodo(periodo)} · Segmento {seg_nombre}",
                                    f"Comparado con {ant}. Montos en CLP.", cuerpo), encoding="utf-8")

    ruta_csv = carpeta / f"{base}.csv"
    detalle = kpis.detalle_segmento(conn, periodo, seg_id)
    columnas = ["periodo", "segmento", "sucursal", "producto", "familia", "operaciones", "monto_clp",
                "comision_clp", "monto_anterior_clp", "var_vs_mes_anterior"]
    with ruta_csv.open("w", newline="", encoding="utf-8-sig") as f:  # BOM: Excel abre bien los acentos
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        for d in detalle:
            w.writerow({"periodo": periodo, "segmento": seg_nombre, **d,
                        "comision_clp": round(d["comision_clp"]),
                        "var_vs_mes_anterior": "" if d["var_vs_mes_anterior"] is None
                        else round(d["var_vs_mes_anterior"], 4)})
    return Reporte(seg_id, seg_nombre, segmento["lista_distribucion"], ruta_html, ruta_csv)


# ───────────── Resumen general del cierre ─────────────

def generar_resumen(conn: sqlite3.Connection, periodo: str, destino: Path, metricas_calidad: dict) -> Path:
    res = kpis.resumen_periodo(conn, periodo)
    ejs = kpis.cumplimiento_ejecutivos(conn, periodo)
    sucs = kpis.cumplimiento_sucursales(conn, periodo)
    segs = kpis.variacion_vs_anterior(conn, periodo, "segmento")
    mix = kpis.mix_productos(conn, periodo)
    rech = kpis.rechazos_por_regla(conn, periodo)

    sobre_meta = sum(1 for e in ejs if (e["cumplimiento"] or 0) >= 1)
    cuerpo = _kpis_html(res)
    cuerpo += (f"<h2>Calidad de datos</h2><p>{entero(metricas_calidad['filas_leidas'])} filas leídas, "
               f"{entero(metricas_calidad['filas_cargadas'])} cargadas y "
               f"{entero(metricas_calidad['filas_rechazadas'])} rechazadas.</p>")
    cuerpo += _tabla([("Regla", False), ("Rechazos", True)], [[r["regla"], entero(r["rechazos"])] for r in rech])
    cuerpo += "<h2>Cumplimiento por sucursal</h2>" + _tabla(
        [("Sucursal", False), ("Monto", True), ("Meta", True), ("Cumplimiento", True)],
        [[s["sucursal"], clp(s["monto_clp"]), clp(s["meta_clp"]), pct(s["cumplimiento"])] for s in sucs],
        [["", "", "", _clase(s["cumplimiento"], 1.0)] for s in sucs])
    cuerpo += "<h2>Variación por segmento</h2>" + _tabla(
        [("Segmento", False), ("Monto", True), ("Mes anterior", True), ("Var. %", True)],
        [[s["nombre"], clp(s["monto_clp"]), clp(s["monto_anterior_clp"] or None), pct(s["var_vs_mes_anterior"], True)]
         for s in segs],
        [["", "", "", _clase(s["var_vs_mes_anterior"])] for s in segs])
    cuerpo += "<h2>Mix de productos</h2>" + _tabla(
        [("Producto", False), ("Monto", True), ("Mix %", True)],
        [[m["producto"], clp(m["monto_clp"]), pct(m["participacion"])] for m in mix])
    cuerpo += (f"<h2>Cumplimiento por ejecutivo</h2><p>{sobre_meta} de {len(ejs)} ejecutivos "
               f"alcanzan o superan su meta.</p>") + _tabla(
        [("Ejecutivo", False), ("Sucursal", False), ("Monto", True), ("Meta", True), ("Cumplimiento", True)],
        [[e["nombre"], e["sucursal"], clp(e["monto_clp"]), clp(e["meta_clp"]), pct(e["cumplimiento"])] for e in ejs],
        [["", "", "", "", _clase(e["cumplimiento"], 1.0)] for e in ejs])

    destino = Path(destino)
    destino.mkdir(parents=True, exist_ok=True)
    ruta = destino / f"resumen_cierre_{periodo}.html"
    ruta.write_text(_documento(f"Cierre comercial {nombre_periodo(periodo)} · Resumen",
                               f"Todos los segmentos. Comparado con {nombre_periodo(periodo_anterior(periodo))}.",
                               cuerpo), encoding="utf-8")

    # CSV de cumplimiento por ejecutivo: la tabla que más se consulta después del cierre.
    with (destino / f"cumplimiento_ejecutivos_{periodo}.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["periodo", "id_ejecutivo", "nombre", "sucursal", "monto_clp",
                                          "meta_clp", "cumplimiento"])
        w.writeheader()
        for e in ejs:
            w.writerow({"periodo": periodo, **e, "cumplimiento": round(e["cumplimiento"], 4)})
    return ruta
