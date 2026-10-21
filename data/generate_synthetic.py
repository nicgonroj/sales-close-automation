"""Genera los CSV sintéticos de los "sistemas fuente" para el cierre comercial.

Todo es inventado: sucursales, ejecutivos (identificados por código), productos, tarifas,
clientes y montos. El generador es determinista dada la semilla.

Salida en data/fuente/:
  maestro_sucursales.csv, maestro_ejecutivos.csv, maestro_productos.csv (tarifario),
  maestro_segmentos.csv, metas_AAAA-MM.csv, colocaciones_AAAA-MM.csv
  y _errores_inyectados_AAAA-MM.json (verdad de terreno para comprobar la validación).

Uso:
  python data/generate_synthetic.py --periodos 2026-08 2026-09 --seed 42
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from cierre.calendario import dias_del_periodo, es_habil  # noqa: E402

SUCURSALES = [
    ("SUC-01", "Santiago Centro", "Metropolitana"),
    ("SUC-02", "Providencia", "Metropolitana"),
    ("SUC-03", "Las Condes", "Metropolitana"),
    ("SUC-04", "Maipú", "Metropolitana"),
    ("SUC-05", "Viña del Mar", "Valparaíso"),
    ("SUC-06", "Concepción", "Biobío"),
    ("SUC-07", "Antofagasta", "Antofagasta"),
    ("SUC-08", "Temuco", "La Araucanía"),
]

# id, nombre, familia, tarifa de comisión (vacía = sin tarifa vigente), ticket medio en CLP
PRODUCTOS = [
    ("PR-CON", "Crédito de consumo", "Créditos", "0.020", 4_500_000),
    ("PR-HIP", "Crédito hipotecario", "Créditos", "0.008", 65_000_000),
    ("PR-AUT", "Crédito automotriz", "Créditos", "0.015", 12_000_000),
    ("PR-TDC", "Tarjeta de crédito (cupo)", "Medios de pago", "0.010", 1_500_000),
    ("PR-DAP", "Depósito a plazo", "Inversiones", "0.004", 8_000_000),
    ("PR-FMU", "Fondo mutuo", "Inversiones", "0.006", 6_000_000),
    ("PR-SDG", "Seguro de desgravamen", "Seguros", "0.120", 350_000),
    ("PR-SVI", "Seguro de vida", "Seguros", "0.150", 500_000),
    ("PR-LEA", "Leasing pyme", "Créditos", "", 25_000_000),  # en el tarifario, sin tarifa vigente
]

# id, nombre, multiplicador de ticket, pesos de producto (mismo orden que PRODUCTOS, sin leasing)
SEGMENTOS = [
    ("SEG-PER", "Personas", 1.0, [30, 6, 8, 26, 8, 6, 9, 7]),
    ("SEG-PRE", "Preferente", 2.2, [18, 14, 10, 14, 18, 16, 5, 5]),
    ("SEG-PYM", "Pyme", 3.0, [34, 3, 14, 12, 20, 9, 4, 4]),
    ("SEG-EMP", "Empresas", 6.0, [30, 2, 10, 8, 32, 14, 2, 2]),
]
PESO_SEGMENTOS = [55, 22, 15, 8]
CANALES = ["Sucursal", "Digital", "Telefónico"]
PESO_CANALES = [55, 35, 10]
EJECUTIVOS_POR_SUCURSAL = 5  # 40 ejecutivos ≈ 6.000 operaciones al mes

# Tasas de error inyectado sobre las filas válidas del mes (realistas para una extracción manual).
TASAS_ERROR = {
    "duplicado": 0.015,             # la misma operación extraída dos veces
    "monto_negativo": 0.008,        # reversa informada como monto negativo
    "fecha_fuera_periodo": 0.006,   # operación del mes anterior o siguiente
    "ejecutivo_inexistente": 0.005, # código de ejecutivo dado de baja o mal digitado
    "producto_sin_tarifa": 0.006,   # producto sin tarifa vigente en el tarifario
    "segmento_vacio": 0.003,        # campo obligatorio vacío
}

COLUMNAS_VENTAS = ["id_operacion", "fecha_operacion", "id_ejecutivo", "id_sucursal", "id_producto",
                   "id_segmento", "id_cliente", "canal", "monto_clp"]


def escribir_csv(ruta: Path, columnas: list[str], filas: list[dict]) -> None:
    with ruta.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columnas)
        w.writeheader()
        w.writerows(filas)


def generar_maestros(rng: random.Random, destino: Path, por_sucursal: int) -> list[dict]:
    """Escribe los maestros y devuelve los ejecutivos con su productividad (oculta)."""
    escribir_csv(destino / "maestro_sucursales.csv", ["id_sucursal", "nombre", "region"],
                 [dict(zip(["id_sucursal", "nombre", "region"], s)) for s in SUCURSALES])
    escribir_csv(destino / "maestro_productos.csv", ["id_producto", "nombre", "familia", "tarifa_comision"],
                 [dict(zip(["id_producto", "nombre", "familia", "tarifa_comision"], p[:4])) for p in PRODUCTOS])
    escribir_csv(destino / "maestro_segmentos.csv", ["id_segmento", "nombre", "lista_distribucion"],
                 [{"id_segmento": s[0], "nombre": s[1],
                   "lista_distribucion": f"cierre-{s[1].lower()}@empresa.example"} for s in SEGMENTOS])
    ejecutivos = []
    n = 0
    for id_suc, _, _ in SUCURSALES:
        for _ in range(por_sucursal):
            n += 1
            ejecutivos.append({"id_ejecutivo": f"EJ-{n:03d}", "nombre": f"Ejecutivo {n:03d}",
                               "id_sucursal": id_suc, "_productividad": rng.uniform(0.6, 1.4)})
    escribir_csv(destino / "maestro_ejecutivos.csv", ["id_ejecutivo", "nombre", "id_sucursal"],
                 [{k: v for k, v in e.items() if not k.startswith("_")} for e in ejecutivos])
    return ejecutivos


def generar_ventas_limpias(rng: random.Random, periodo: str, ejecutivos: list[dict],
                           estacionalidad: float) -> list[dict]:
    """Operaciones válidas: cada ejecutivo coloca entre 4 y 10 operaciones por día hábil."""
    habiles = [d for d in dias_del_periodo(periodo) if es_habil(d)]
    filas, correlativo = [], 0
    productos_vendibles = PRODUCTOS[:-1]  # el leasing solo aparece como error inyectado
    for dia in habiles:
        for ej in ejecutivos:
            n_ops = max(0, round(rng.gauss(7 * ej["_productividad"] * estacionalidad, 1.5)))
            for _ in range(n_ops):
                correlativo += 1
                seg = rng.choices(SEGMENTOS, weights=PESO_SEGMENTOS)[0]
                prod = rng.choices(productos_vendibles, weights=seg[3])[0]
                monto = prod[4] * seg[2] * rng.lognormvariate(0, 0.45)
                filas.append({
                    "id_operacion": f"OP-{periodo.replace('-', '')}-{correlativo:06d}",
                    "fecha_operacion": dia.isoformat(),
                    "id_ejecutivo": ej["id_ejecutivo"],
                    "id_sucursal": ej["id_sucursal"],
                    "id_producto": prod[0],
                    "id_segmento": seg[0],
                    "id_cliente": f"CLI-{rng.randint(1, 60_000):06d}",
                    "canal": rng.choices(CANALES, weights=PESO_CANALES)[0],
                    "monto_clp": str(int(round(monto, -3))),
                })
    return filas


def inyectar_errores(rng: random.Random, periodo: str, filas: list[dict]) -> tuple[list[dict], dict]:
    """Corrompe filas disjuntas (una sola falla por fila) y agrega duplicados; devuelve el conteo."""
    indices = list(range(len(filas)))
    rng.shuffle(indices)
    dias = dias_del_periodo(periodo)
    conteo, cursor, a_duplicar = {}, 0, []
    for tipo, tasa in TASAS_ERROR.items():
        k = round(len(filas) * tasa)
        elegidos, cursor = indices[cursor:cursor + k], cursor + k
        conteo[tipo] = k
        for i in elegidos:
            fila = filas[i]
            if tipo == "duplicado":
                a_duplicar.append(i)  # se copia una fila que queda válida
            elif tipo == "monto_negativo":
                fila["monto_clp"] = str(-int(fila["monto_clp"]))
            elif tipo == "fecha_fuera_periodo":
                fuera = (dias[0] - timedelta(days=rng.randint(1, 3)) if rng.random() < 0.5
                         else dias[-1] + timedelta(days=rng.randint(1, 3)))
                fila["fecha_operacion"] = fuera.isoformat()
            elif tipo == "ejecutivo_inexistente":
                fila["id_ejecutivo"] = f"EJ-B{rng.randint(100, 999)}"  # prefijo que nunca existe en el maestro
            elif tipo == "producto_sin_tarifa":
                fila["id_producto"] = "PR-LEA"
            elif tipo == "segmento_vacio":
                fila["id_segmento"] = ""
    # Cada copia aparece más adelante en el archivo, como en una extracción repetida.
    salida = list(filas)
    for i in sorted(a_duplicar, reverse=True):
        salida.insert(rng.randint(i + 1, len(salida)), dict(filas[i]))
    return salida, conteo


def generar_metas(rng: random.Random, ventas_limpias: list[dict], ejecutivos: list[dict]) -> list[dict]:
    """Meta = venta esperada del ejecutivo × un factor de exigencia (85 %–125 %), redondeada a millones."""
    por_ej = {e["id_ejecutivo"]: 0 for e in ejecutivos}
    for f in ventas_limpias:
        por_ej[f["id_ejecutivo"]] += int(f["monto_clp"])
    return [{"id_ejecutivo": ej, "meta_clp": str(int(round(total * rng.uniform(0.85, 1.25), -6)))}
            for ej, total in por_ej.items()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generador sintético del cierre comercial")
    parser.add_argument("--periodos", nargs="+", default=["2026-08", "2026-09"])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--destino", type=Path, default=RAIZ / "data" / "fuente")
    parser.add_argument("--ejecutivos-por-sucursal", type=int, default=EJECUTIVOS_POR_SUCURSAL,
                        help="escala del volumen: 50 genera ≈ 60.000 operaciones al mes")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    args.destino.mkdir(parents=True, exist_ok=True)
    ejecutivos = generar_maestros(rng, args.destino, args.ejecutivos_por_sucursal)
    for i, periodo in enumerate(args.periodos):
        estacionalidad = 1.0 + 0.04 * i * rng.choice([-1, 1])
        limpias = generar_ventas_limpias(rng, periodo, ejecutivos, estacionalidad)
        metas = generar_metas(rng, limpias, ejecutivos)
        n_limpias = len(limpias)
        filas, conteo = inyectar_errores(rng, periodo, [dict(f) for f in limpias])
        escribir_csv(args.destino / f"colocaciones_{periodo}.csv", COLUMNAS_VENTAS, filas)
        escribir_csv(args.destino / f"metas_{periodo}.csv", ["id_ejecutivo", "meta_clp"], metas)
        resumen = {"periodo": periodo, "seed": args.seed, "filas_originales": n_limpias,
                   "filas_en_archivo": len(filas), "errores_inyectados": conteo,
                   "filas_validas_esperadas": n_limpias - sum(v for k, v in conteo.items() if k != "duplicado")}
        (args.destino / f"_errores_inyectados_{periodo}.json").write_text(
            json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"{periodo}: {len(filas)} filas ({n_limpias} originales), errores inyectados: {conteo}")


if __name__ == "__main__":
    main()
