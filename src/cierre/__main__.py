"""CLI del cierre comercial.

  PYTHONPATH=src python -m cierre --periodo 2026-09            # dry-run (por defecto)
  PYTHONPATH=src python -m cierre --periodo 2026-09 --no-dry-run
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import RAIZ, REGLAS_POR_DEFECTO, ejecutar


def main() -> None:
    p = argparse.ArgumentParser(prog="cierre", description="Automatización del cierre comercial mensual")
    p.add_argument("--periodo", required=True, help="período a cerrar, AAAA-MM")
    p.add_argument("--fuente", type=Path, default=RAIZ / "data" / "fuente", help="carpeta con los CSV fuente")
    p.add_argument("--db", type=Path, default=RAIZ / "output" / "cierre.sqlite", help="base SQLite del modelo")
    p.add_argument("--salida", type=Path, default=RAIZ / "output", help="carpeta de reportes")
    p.add_argument("--reglas", type=Path, default=REGLAS_POR_DEFECTO, help="reglas de negocio (JSON)")
    p.add_argument("--dry-run", action=argparse.BooleanOptionalAction, default=True,
                   help="simula el envío (por defecto). --no-dry-run arma los .eml, pero tampoco envía")
    p.add_argument("--sin-mes-anterior", action="store_true", help="no recargar el mes anterior")
    a = p.parse_args()

    m = ejecutar(a.periodo, a.fuente, a.db, a.salida, a.reglas, dry_run=a.dry_run,
                 incluir_anterior=not a.sin_mes_anterior)
    for c in m["cargas"]:
        print(f"[{c['periodo']}] {c['filas_leidas']} leídas · {c['filas_cargadas']} cargadas · "
              f"{c['filas_rechazadas']} rechazadas · {c['segundos']} s")
        for regla, n in c["rechazos_por_regla"].items():
            print(f"    {regla}: {n}")
    modo = "dry-run" if m["dry_run"] else ".eml listos, sin envío"
    print(f"Reportes por segmento: {m['reportes_por_segmento']} ({modo}) · "
          f"envío programado: {m['fecha_programada_envio']}")
    print(f"Tiempo total del pipeline: {m['segundos_total']} s")


if __name__ == "__main__":
    main()
